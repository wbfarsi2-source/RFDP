from __future__ import annotations

import base64
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import websocket

import ctm_common_capture as common

BASE_URL = common.BASE_URL
PLAY_URL = common.PLAY_URL
REGION = "ember"
BROWSER_WAIT_SECONDS = 30.0
TRANSITION_WAIT_SECONDS = 2.0
REPLAY_CAPTURE_SECONDS = 10.0
MAX_CAPTURED_FRAMES = 800

SAFE_REPLAY_BLOCKED_TYPES = {
    "pos",
    "move",
    "act",
    "attack",
    "combat",
    "farm",
    "fish",
    "cook",
    "sell",
    "queue_join",
    "gc_ev",
    "drink",
    "trd",
    "shv_dig",
    "shv_claim",
}

_IDENTIFIER = r"[$A-Za-z_][$A-Za-z0-9_]*"
_FACTORY_RETURN_PATTERN = re.compile(
    rf"return a\((?P<enter>{_IDENTIFIER}),[\"']enterSpectatorMode[\"']\),"
    rf"\{{enterSpectatorMode:(?P=enter),readFanoutFetch:(?P<fetch>{_IDENTIFIER}),"
    rf"sendSpectatorRegionUpdate:(?P<send>{_IDENTIFIER}),"
    rf"trySpectatorRealmTransitionAt:(?P<transition>{_IDENTIFIER})\}}\}}"
    rf"a\((?P<factory>{_IDENTIFIER}),[\"']createSpectatorMode[\"']\);"
)


def patch_game_script(source: str) -> tuple[str, dict[str, Any]]:
    match = _FACTORY_RETURN_PATTERN.search(source)
    if not match:
        return source, {"patched": False, "error": "Spectator factory return marker was not found"}

    factory = match.group("factory")
    prefix = source[: match.start()]
    function_pattern = re.compile(rf"function\s+{re.escape(factory)}\((?P<arg>{_IDENTIFIER})\)\{{")
    function_matches = list(function_pattern.finditer(prefix))
    if not function_matches:
        return source, {"patched": False, "error": "Spectator factory parameter was not found"}

    dependency_arg = function_matches[-1].group("arg")
    enter_name = match.group("enter")
    fetch_name = match.group("fetch")
    send_name = match.group("send")
    transition_name = match.group("transition")

    original = match.group(0)
    injection = (
        "try{globalThis.__ctmSpectatorApi={"
        f"deps:{dependency_arg},"
        f"enterSpectatorMode:{enter_name},"
        f"readFanoutFetch:{fetch_name},"
        f"sendRegion:{send_name},"
        f"transition:{transition_name}"
        "}}catch{};"
        + original
    )
    patched = source[: match.start()] + injection + source[match.end() :]
    return patched, {
        "patched": True,
        "factory": factory,
        "dependency_arg": dependency_arg,
        "enter": enter_name,
        "send": send_name,
        "transition": transition_name,
    }


def response_headers_without_encoding(headers: list[dict[str, str]]) -> list[dict[str, str]]:
    blocked = {"content-length", "content-encoding", "transfer-encoding", "etag"}
    output: list[dict[str, str]] = []
    for row in headers:
        name = str(row.get("name") or "")
        if name.lower() in blocked:
            continue
        output.append({"name": name, "value": str(row.get("value") or "")})
    output.append({"name": "Cache-Control", "value": "no-store"})
    return output


def cdp_value(response: dict[str, Any]) -> Any:
    return response.get("result", {}).get("result", {}).get("value")


def runtime_eval(
    session: common.CdpSession,
    expression: str,
    *,
    await_promise: bool = False,
    timeout: float = 20.0,
) -> Any:
    response = session.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        },
        timeout=timeout,
    )
    return cdp_value(response)


def browser_state(session: common.CdpSession) -> dict[str, Any]:
    value = runtime_eval(
        session,
        """
        (() => {
          const api = globalThis.__ctmSpectatorApi;
          if (!api || !api.deps) return {available:false};
          const d = api.deps;
          const keys = Object.keys(d || {});
          const transitionKeys = keys.filter(k => /pond|beach|ember|portal|entry|return/i.test(k));
          return {
            available:true,
            spectatorMode:!!d.spectatorMode,
            spectatorReady:!!d.spectatorReady,
            gameState:String(d.gameState || ""),
            worldChatRegion:String(typeof d.worldChatRegionKey === "function" ? d.worldChatRegionKey() : ""),
            transitionKeys:transitionKeys.slice(0,300),
            hasEnterPond:typeof d.enterPond === "function",
            hasEnterBeach:typeof d.enterBeachFromPond === "function",
            hasEnterEmber:typeof d.enterEmberFromBeach === "function"
          };
        })()
        """,
    )
    return value if isinstance(value, dict) else {"available": False}


def wait_for_state(
    session: common.CdpSession,
    expected: str,
    timeout: float = 8.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = browser_state(session)
        if str(latest.get("gameState") or "").lower() == expected:
            return latest
        time.sleep(0.2)
    return latest


def invoke_transition(session: common.CdpSession, function_name: str) -> dict[str, Any]:
    expression = f"""
    (async () => {{
      const api = globalThis.__ctmSpectatorApi;
      if (!api || !api.deps) return {{ok:false,error:"Spectator API unavailable"}};
      const d = api.deps;
      const fn = d[{json.dumps(function_name)}];
      if (typeof fn !== "function") return {{ok:false,error:"Function unavailable",name:{json.dumps(function_name)}}};
      const before = String(d.gameState || "");
      try {{
        const result = fn();
        if (result && typeof result.then === "function") await result;
      }} catch (error) {{
        return {{ok:false,error:String(error && error.message || error),before}};
      }}
      await new Promise(resolve => setTimeout(resolve, {int(TRANSITION_WAIT_SECONDS * 1000)}));
      try {{ api.sendRegion(); }} catch (error) {{}}
      await new Promise(resolve => setTimeout(resolve, 500));
      return {{
        ok:true,
        before,
        after:String(d.gameState || ""),
        region:String(typeof d.worldChatRegionKey === "function" ? d.worldChatRegionKey() : "")
      }};
    }})()
    """
    value = runtime_eval(session, expression, await_promise=True, timeout=15.0)
    return value if isinstance(value, dict) else {"ok": False, "error": "No transition result"}


def parse_websocket_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    created: dict[str, str] = {}
    sent: list[dict[str, Any]] = []
    received: list[dict[str, Any]] = []
    headers: dict[str, Any] = {}

    for event in events:
        method = event.get("method")
        params = event.get("params") or {}
        if method == "Network.webSocketCreated":
            created[str(params.get("requestId"))] = str(params.get("url") or "")
        elif method == "Network.webSocketWillSendHandshakeRequest":
            request_id = str(params.get("requestId"))
            raw_headers = ((params.get("request") or {}).get("headers") or {})
            headers[request_id] = {
                key: ("<redacted>" if key.lower() in {"cookie", "authorization"} else value)
                for key, value in raw_headers.items()
            }
        elif method in {"Network.webSocketFrameSent", "Network.webSocketFrameReceived"}:
            frame = params.get("response") or {}
            entry = {
                "requestId": str(params.get("requestId")),
                "url": created.get(str(params.get("requestId")), ""),
                "opcode": frame.get("opcode"),
                "mask": frame.get("mask"),
                "payload": str(frame.get("payloadData") or "")[:50000],
                "at": params.get("timestamp"),
            }
            if method.endswith("FrameSent"):
                sent.append(entry)
            else:
                received.append(entry)

    return {
        "urls": sorted({row["url"] for row in sent + received if "/ws/spectate/" in row["url"]}),
        "request_headers": headers,
        "sent_frames": sent[-MAX_CAPTURED_FRAMES:],
        "received_frames": received[-MAX_CAPTURED_FRAMES:],
    }


def decode_payload_text(payload: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(payload)
    except Exception:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def summarize_frames(capture: dict[str, Any]) -> dict[str, Any]:
    sent_messages: list[dict[str, Any]] = []
    received_types: Counter[str] = Counter()
    received_regions: Counter[str] = Counter()
    snapshot_counts: Counter[str] = Counter()
    ember_player_counts: list[int] = []

    for frame in capture.get("sent_frames") or []:
        if "/ws/spectate/" not in str(frame.get("url") or ""):
            continue
        sent_messages.extend(decode_payload_text(str(frame.get("payload") or "")))

    for frame in capture.get("received_frames") or []:
        if "/ws/spectate/" not in str(frame.get("url") or ""):
            continue
        for message in decode_payload_text(str(frame.get("payload") or "")):
            message_type = str(message.get("t") or "<none>")
            region = str(message.get("region") or "<none>").lower()
            received_types[message_type] += 1
            received_regions[region] += 1
            if message_type == "snap":
                snapshot_counts[region] += 1
                if region == REGION:
                    ember_player_counts.append(common.player_count(message))

    return {
        "sent_messages": sent_messages,
        "received_types": dict(received_types),
        "received_regions": dict(received_regions),
        "snapshot_counts": dict(snapshot_counts),
        "ember_player_counts": ember_player_counts,
    }


def safe_transition_prelude(sent_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in sent_messages:
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("t") or "").strip().lower()
        if not message_type or message_type in SAFE_REPLAY_BLOCKED_TYPES:
            continue
        serialized = json.dumps(message, sort_keys=True, separators=(",", ":"))
        if serialized in seen:
            continue
        seen.add(serialized)
        output.append(message)
    return output[:30]


def browser_transition_capture(cookie: str) -> dict[str, Any]:
    browser = common.find_browser()
    if browser is None:
        return {"available": False, "error": "Chrome, Edge, or Chromium was not found"}

    user_data_dir = Path(tempfile.mkdtemp(prefix="ctm_ember_browser_"))
    process: subprocess.Popen[str] | None = None
    session: common.CdpSession | None = None
    patch_meta: dict[str, Any] = {"patched": False}
    transition_results: list[dict[str, Any]] = []
    processed_events = 0

    try:
        args = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_dir}",
            "about:blank",
        ]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        active_port_file = user_data_dir / "DevToolsActivePort"
        deadline = time.time() + 15.0
        while time.time() < deadline and not active_port_file.is_file():
            if process.poll() is not None:
                raise RuntimeError("Browser exited before DevTools became available")
            time.sleep(0.1)
        if not active_port_file.is_file():
            raise TimeoutError("DevToolsActivePort was not created")

        port = int(active_port_file.read_text(encoding="utf-8").splitlines()[0].strip())
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            targets = client.get(f"http://127.0.0.1:{port}/json/list").json()
        page = next((item for item in targets if item.get("type") == "page"), None)
        if not page:
            raise RuntimeError("No page target was found")

        session = common.CdpSession(str(page["webSocketDebuggerUrl"]))
        session.call("Network.enable")
        session.call("Runtime.enable")
        session.call("Page.enable")
        session.call("Network.setCacheDisabled", {"cacheDisabled": True})
        session.call("Network.setExtraHTTPHeaders", {"headers": {"User-Agent": common.USER_AGENT}})
        session.call(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*game.*.js*",
                        "requestStage": "Response",
                    }
                ]
            },
        )

        parsed_cookie = common.parse_cookie(cookie)
        if parsed_cookie:
            name, value = parsed_cookie
            session.call(
                "Network.setCookie",
                {
                    "name": name,
                    "value": value,
                    "url": BASE_URL,
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Strict",
                },
            )

        session.call("Page.navigate", {"url": PLAY_URL})
        started = time.time()
        api_ready = False

        while time.time() - started < BROWSER_WAIT_SECONDS:
            events_snapshot = list(session.events)
            while processed_events < len(events_snapshot):
                event = events_snapshot[processed_events]
                processed_events += 1
                if event.get("method") != "Fetch.requestPaused":
                    continue
                params = event.get("params") or {}
                request_id = str(params.get("requestId") or "")
                url = str((params.get("request") or {}).get("url") or "")
                try:
                    if "game." in Path(urlparse(url).path).name and params.get("responseStatusCode"):
                        body_response = session.call("Fetch.getResponseBody", {"requestId": request_id})
                        result = body_response.get("result") or {}
                        body = str(result.get("body") or "")
                        raw = base64.b64decode(body) if result.get("base64Encoded") else body.encode("utf-8")
                        source = raw.decode("utf-8", errors="replace")
                        patched_source, patch_meta = patch_game_script(source)
                        if patch_meta.get("patched"):
                            headers = response_headers_without_encoding(params.get("responseHeaders") or [])
                            session.call(
                                "Fetch.fulfillRequest",
                                {
                                    "requestId": request_id,
                                    "responseCode": int(params.get("responseStatusCode") or 200),
                                    "responsePhrase": str(params.get("responseStatusText") or "OK"),
                                    "responseHeaders": headers,
                                    "body": base64.b64encode(patched_source.encode("utf-8")).decode("ascii"),
                                },
                            )
                        else:
                            session.call("Fetch.continueRequest", {"requestId": request_id})
                    else:
                        session.call("Fetch.continueRequest", {"requestId": request_id})
                except Exception:
                    try:
                        session.call("Fetch.continueRequest", {"requestId": request_id})
                    except Exception:
                        pass

            if patch_meta.get("patched"):
                try:
                    state = browser_state(session)
                    if state.get("available") and state.get("spectatorReady"):
                        api_ready = True
                        break
                except Exception:
                    pass
            time.sleep(0.1)

        initial_state = browser_state(session) if api_ready else {"available": False}
        if api_ready:
            steps = [
                ("pond", "enterPond"),
                ("beach", "enterBeachFromPond"),
                ("ember", "enterEmberFromBeach"),
            ]
            for expected_state, function_name in steps:
                result = invoke_transition(session, function_name)
                result["expected_state"] = expected_state
                state = wait_for_state(session, expected_state, timeout=8.0)
                result["observed_state"] = state
                transition_results.append(result)
                if str(state.get("gameState") or "").lower() != expected_state:
                    break
            time.sleep(6.0)

        capture = parse_websocket_events(list(session.events))
        frame_summary = summarize_frames(capture)
        return {
            "available": True,
            "browser": str(browser),
            "patch": patch_meta,
            "api_ready": api_ready,
            "initial_state": initial_state,
            "transition_results": transition_results,
            "final_state": browser_state(session) if api_ready else {"available": False},
            "capture": capture,
            "frame_summary": frame_summary,
            "event_count": len(session.events),
        }
    except Exception as exc:
        return {
            "available": True,
            "browser": str(browser),
            "patch": patch_meta,
            "transition_results": transition_results,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if session is not None:
            try:
                session.call("Fetch.disable", timeout=2.0)
            except Exception:
                pass
            session.close()
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        shutil.rmtree(user_data_dir, ignore_errors=True)


def websocket_headers(cookie: str) -> list[str]:
    headers = [
        f"User-Agent: {common.USER_AGENT}",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
    ]
    if cookie:
        headers.append(f"Cookie: {cookie}")
    return headers


def replay_server(
    server: dict[str, Any],
    cookie: str,
    prelude: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = common.fanout_spectate_endpoint(server)
    token = common.fetch_connect_token(server, cookie, purpose="spectate")
    endpoint_with_token = common.append_token(endpoint, token)
    result: dict[str, Any] = {
        "server": str(server.get("name") or "?"),
        "number": common.server_number(server),
        "endpoint": endpoint,
        "token_present": bool(token),
        "connected": False,
        "sent": [],
        "regions": {},
        "snapshots": {},
        "ember_counts": [],
        "error": "",
    }
    ws = None
    try:
        ws = websocket.create_connection(
            endpoint_with_token,
            timeout=12,
            origin=BASE_URL,
            enable_multithread=True,
            header=websocket_headers(cookie),
        )
        ws.settimeout(0.5)
        result["connected"] = True
        started = time.time()
        sent = False
        region_counts: Counter[str] = Counter()
        snapshot_counts: Counter[str] = Counter()

        while time.time() - started < REPLAY_CAPTURE_SECONDS:
            if not sent:
                for index, message in enumerate(prelude):
                    if index:
                        time.sleep(random.uniform(0.12, 0.28))
                    ws.send(json.dumps(message, separators=(",", ":")))
                    result["sent"].append(message)
                sent = True
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            for message in common.decode_frame(raw):
                region = str(message.get("region") or "<none>").strip().lower() or "<none>"
                region_counts[region] += 1
                if str(message.get("t") or "") == "snap":
                    snapshot_counts[region] += 1
                    if region == REGION:
                        result["ember_counts"].append(common.player_count(message))

        result["regions"] = dict(region_counts)
        result["snapshots"] = dict(snapshot_counts)
        if not result["ember_counts"]:
            result["error"] = "No Ember snapshot received"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    return result


def full_scan(
    servers: list[dict[str, Any]],
    cookie: str,
    prelude: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for index, server in enumerate(servers):
        if index:
            time.sleep(random.uniform(0.12, 0.30))
        row = replay_server(server, cookie, prelude)
        rows.append(row)
        print(
            f"[{row['server']}] connected={row['connected']} "
            f"ember={(row.get('snapshots') or {}).get('ember', 0)} "
            f"players={str((row.get('ember_counts') or [None])[-1])} "
            f"error={row.get('error') or '-'}"
        )

    verified = [row for row in rows if row.get("ember_counts")]
    top3 = sorted(
        (
            {
                "server": row["server"],
                "number": row["number"],
                "players": int(row["ember_counts"][-1]),
                "samples": len(row["ember_counts"]),
            }
            for row in verified
        ),
        key=lambda row: (-row["players"], row["number"]),
    )[:3]
    return rows, top3


def redact(value: Any) -> Any:
    return common.redact_payload(value)


def write_summary(report: dict[str, Any]) -> str:
    browser = report.get("browser_transition") or {}
    frame_summary = browser.get("frame_summary") or {}
    lines = [
        "KINTARA COME TO MOLTEN OFFICIAL EMBER TRANSITION PROBE",
        "=" * 88,
        f"Created: {report['created_at']}",
        f"Project root: {report['project_root']}",
        f"Cookie loaded: {report['cookie_present']}",
        f"Normal servers: {report['server_list'].get('normal_servers', 0)}",
        "",
        "OFFICIAL CLIENT TRANSITION",
        "-" * 88,
        f"Browser available: {browser.get('available', False)}",
        f"Runtime patch applied: {(browser.get('patch') or {}).get('patched', False)}",
        f"Spectator API ready: {browser.get('api_ready', False)}",
        f"Initial state: {(browser.get('initial_state') or {}).get('gameState', '-')}",
        f"Final state: {(browser.get('final_state') or {}).get('gameState', '-')}",
    ]

    for row in browser.get("transition_results") or []:
        observed = row.get("observed_state") or {}
        lines.append(
            f"{row.get('expected_state','?'):<8} call={row.get('ok', False)} "
            f"state={observed.get('gameState', '-')} region={observed.get('worldChatRegion', '-')} "
            f"error={row.get('error') or '-'}"
        )

    lines.extend(
        [
            "",
            "CAPTURED SPECTATOR TRAFFIC",
            "-" * 88,
            f"Sent messages: {len(frame_summary.get('sent_messages') or [])}",
            f"Received regions: {frame_summary.get('received_regions') or {}}",
            f"Snapshot counts: {frame_summary.get('snapshot_counts') or {}}",
            f"Ember player samples: {frame_summary.get('ember_player_counts') or []}",
            "",
            "REPLAY AND FULL SCAN",
            "-" * 88,
            f"Safe transition prelude: {report.get('transition_prelude') or []}",
            f"Representative replay verified: {report.get('representative_verified', False)}",
        ]
    )

    if report.get("top3"):
        lines.append("")
        lines.append("TOP 3 VERIFIED EMBER SERVERS")
        lines.append("-" * 88)
        for index, row in enumerate(report["top3"], 1):
            lines.append(f"{index}. {row['server']} - {row['players']} player(s)")
    else:
        lines.append("")
        lines.append("No verified Top 3 was produced. Review transition and frame details in the JSON report.")

    lines.append("")
    lines.append(f"Full report: {report['report_path']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print("=" * 88)
    print("KINTARA COME TO MOLTEN OFFICIAL EMBER TRANSITION PROBE")
    print("=" * 88)
    print("This test uses the official spectator client and moves its local spectator view")
    print("through Mainland, The Pond, The Shores, and The Emberstone automatically.")
    print("It does not require manual game entry and does not send movement, combat, farming,")
    print("inventory, purchase, or account-changing messages.")
    print("It does not request terms.html.")
    print("-" * 88)

    project_root = common.find_project_root()
    env_path = project_root / ".env"
    env = common.load_env(env_path)
    cookie = common.normalize_cookie(env)
    print(f"Project root: {project_root}")
    print(f"Environment file: {env_path}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    if not cookie:
        print("The test requires KINTARA_EMBER_COOKIE or KINTARA_COOKIE in the project .env file.")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_official_ember_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    status, server_payload, server_route = common.get_json("/api/servers", cookie)
    all_servers = [row for row in server_payload.get("servers") or [] if isinstance(row, dict)]
    normal_servers = sorted(
        [row for row in all_servers if common.server_number(row) >= 1],
        key=common.server_number,
    )
    print(f"/api/servers: status={status} normal_servers={len(normal_servers)}")
    print("Starting the instrumented official spectator client...")

    browser_transition = browser_transition_capture(cookie)
    frame_summary = browser_transition.get("frame_summary") or {}
    transition_prelude = safe_transition_prelude(frame_summary.get("sent_messages") or [])

    print(
        "Official client result: "
        f"patch={(browser_transition.get('patch') or {}).get('patched', False)} "
        f"final_state={(browser_transition.get('final_state') or {}).get('gameState', '-')} "
        f"ember_snapshots={(frame_summary.get('snapshot_counts') or {}).get('ember', 0)}"
    )

    representative_results: list[dict[str, Any]] = []
    representative_verified = False
    scan_rows: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []

    if transition_prelude:
        representatives = common.representative_servers(normal_servers)
        print("Replaying the captured official transition on representative servers...")
        for index, server in enumerate(representatives):
            if index:
                time.sleep(random.uniform(0.15, 0.30))
            row = replay_server(server, cookie, transition_prelude)
            representative_results.append(row)
            print(
                f"[{row['server']}] connected={row['connected']} "
                f"ember={(row.get('snapshots') or {}).get('ember', 0)} "
                f"players={str((row.get('ember_counts') or [None])[-1])} "
                f"error={row.get('error') or '-'}"
            )
        representative_verified = any(row.get("ember_counts") for row in representative_results)

    if representative_verified:
        print("Verified Ember data was found. Running the controlled 25-server scan...")
        scan_rows, top3 = full_scan(normal_servers, cookie, transition_prelude)

    report_path = output_dir / "official_ember_report.json"
    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "cookie_present": bool(cookie),
        "server_list": {
            "status": status,
            "route": server_route,
            "all_entries": len(all_servers),
            "normal_servers": len(normal_servers),
            "servers": [
                {
                    "name": row.get("name"),
                    "number": common.server_number(row),
                    "zone": row.get("zone"),
                    "controllerId": row.get("controllerId"),
                    "routeShardId": common.route_shard(row),
                    "fanoutOrigin": row.get("fanoutOrigin"),
                    "wsBaseUrl": row.get("wsBaseUrl"),
                }
                for row in normal_servers
            ],
        },
        "browser_transition": browser_transition,
        "transition_prelude": transition_prelude,
        "representative_results": representative_results,
        "representative_verified": representative_verified,
        "full_scan": scan_rows,
        "top3": top3,
        "report_path": str(report_path),
    }

    safe_report = redact(report)
    report_path.write_text(json.dumps(safe_report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = write_summary(safe_report)
    (output_dir / "summary.txt").write_text(summary, encoding="utf-8")

    print("-" * 88)
    print(summary)
    print(f"Output folder: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
