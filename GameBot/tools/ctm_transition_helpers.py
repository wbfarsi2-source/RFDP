from __future__ import annotations

import base64
import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
STATE_WAIT_SECONDS = 8.0
POST_EMBER_CAPTURE_SECONDS = 6.0
REPLAY_CAPTURE_SECONDS = 9.0
MAX_CAPTURED_FRAMES = 1200
MAX_FULL_SCAN_WORKERS = 5

_IDENTIFIER = r"[$A-Za-z_][$A-Za-z0-9_]*"
_FACTORY_RETURN_PATTERN = re.compile(
    rf"return a\((?P<enter>{_IDENTIFIER}),[\"']enterSpectatorMode[\"']\),"
    rf"\{{enterSpectatorMode:(?P=enter),readFanoutFetch:(?P<fetch>{_IDENTIFIER}),"
    rf"sendSpectatorRegionUpdate:(?P<send>{_IDENTIFIER}),"
    rf"trySpectatorRealmTransitionAt:(?P<transition>{_IDENTIFIER})\}}\}}"
    rf"a\((?P<factory>{_IDENTIFIER}),[\"']createSpectatorMode[\"']\);"
)

ALLOWED_REPLAY_TYPES = {"spec_reg", "hopt"}
PORTAL_SET_BY_STATE = {
    "world": "pondPortalWorldSet",
    "pond": "pondBeachEntryTileSet",
    "beach": "beachEmberEntryTileSet",
}
EXPECTED_NEXT_STATE = {
    "world": "pond",
    "pond": "beach",
    "beach": "ember",
}


def patch_game_script(source: str) -> tuple[str, dict[str, Any]]:
    match = _FACTORY_RETURN_PATTERN.search(source)
    if not match:
        return source, {"patched": False, "error": "Spectator factory return marker was not found"}

    factory = match.group("factory")
    prefix = source[: match.start()]
    function_pattern = re.compile(rf"function\s+{re.escape(factory)}\((?P<arg>{_IDENTIFIER})\)\{{")
    function_matches = list(function_pattern.finditer(prefix))
    if not function_matches:
        return source, {"patched": False, "error": "Spectator factory dependency parameter was not found"}

    dependency_arg = function_matches[-1].group("arg")
    original = match.group(0)
    injection = (
        "try{globalThis.__ctmOfficialSpectatorApi={"
        f"deps:{dependency_arg},"
        f"enterSpectatorMode:{match.group('enter')},"
        f"readFanoutFetch:{match.group('fetch')},"
        f"sendRegion:{match.group('send')},"
        f"transition:{match.group('transition')}"
        "}}catch{};"
        + original
    )
    patched = source[: match.start()] + injection + source[match.end() :]
    return patched, {
        "patched": True,
        "factory": factory,
        "dependency_arg": dependency_arg,
        "enter": match.group("enter"),
        "send": match.group("send"),
        "transition": match.group("transition"),
    }


def response_headers_without_encoding(headers: list[dict[str, str]]) -> list[dict[str, str]]:
    blocked = {"content-length", "content-encoding", "transfer-encoding", "etag"}
    output = [
        {"name": str(row.get("name") or ""), "value": str(row.get("value") or "")}
        for row in headers
        if str(row.get("name") or "").lower() not in blocked
    ]
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
          const api = globalThis.__ctmOfficialSpectatorApi;
          if (!api || !api.deps) return {available:false};
          const d = api.deps;
          const state = String(d.gameState || "").toLowerCase();
          const setName = ({world:"pondPortalWorldSet",pond:"pondBeachEntryTileSet",beach:"beachEmberEntryTileSet"})[state] || "";
          const rawSet = setName ? d[setName] : null;
          const portalTiles = rawSet && typeof rawSet[Symbol.iterator] === "function" ? Array.from(rawSet).map(String).slice(0,30) : [];
          return {
            available:true,
            spectatorMode:!!d.spectatorMode,
            spectatorReady:!!d.spectatorReady,
            gameState:String(d.gameState || ""),
            worldChatRegion:String(typeof d.worldChatRegionKey === "function" ? d.worldChatRegionKey() : ""),
            portalSetName:setName,
            portalTiles,
            transitionType:typeof api.transition,
            transitionArity:typeof api.transition === "function" ? api.transition.length : null,
            transitionSource:typeof api.transition === "function" ? String(api.transition).slice(0,12000) : ""
          };
        })()
        """,
    )
    return value if isinstance(value, dict) else {"available": False}


def wait_for_state(session: common.CdpSession, expected: str, timeout: float = STATE_WAIT_SECONDS) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = browser_state(session)
        if str(latest.get("gameState") or "").lower() == expected:
            return latest
        time.sleep(0.15)
    return latest


def invoke_official_portal_transition(session: common.CdpSession) -> dict[str, Any]:
    expression = """
    (async () => {
      const api = globalThis.__ctmOfficialSpectatorApi;
      if (!api || !api.deps || typeof api.transition !== "function") {
        return {ok:false,error:"Official spectator transition API unavailable"};
      }
      const d = api.deps;
      const before = String(d.gameState || "").toLowerCase();
      const setName = ({world:"pondPortalWorldSet",pond:"pondBeachEntryTileSet",beach:"beachEmberEntryTileSet"})[before];
      const expected = ({world:"pond",pond:"beach",beach:"ember"})[before];
      const rawSet = setName ? d[setName] : null;
      const values = rawSet && typeof rawSet[Symbol.iterator] === "function" ? Array.from(rawSet).map(String) : [];
      const attempts = [];
      for (const raw of values.slice(0,20)) {
        const parts = raw.split(",");
        const col = Number(parts[0]);
        const row = Number(parts[1]);
        if (!Number.isFinite(col) || !Number.isFinite(row)) continue;
        let returned = null;
        let error = "";
        try {
          returned = api.transition(col, row);
          if (returned && typeof returned.then === "function") returned = await returned;
        } catch (e) {
          error = String(e && e.message || e);
        }
        attempts.push({raw,col,row,returned,error,state:String(d.gameState || "")});
        if (String(d.gameState || "").toLowerCase() === expected) break;
        await new Promise(resolve => setTimeout(resolve, 180));
      }
      return {
        ok:String(d.gameState || "").toLowerCase() === expected,
        before,
        after:String(d.gameState || "").toLowerCase(),
        expected,
        setName,
        values:values.slice(0,30),
        attempts,
        transitionArity:api.transition.length,
        transitionSource:String(api.transition).slice(0,12000)
      };
    })()
    """
    value = runtime_eval(session, expression, await_promise=True, timeout=20.0)
    return value if isinstance(value, dict) else {"ok": False, "error": "No transition result"}


def parse_websocket_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    created: dict[str, str] = {}
    sent: list[dict[str, Any]] = []
    received: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []

    for event in events:
        method = event.get("method")
        params = event.get("params") or {}
        request_id = str(params.get("requestId") or "")
        if method == "Network.webSocketCreated":
            created[request_id] = str(params.get("url") or "")
        elif method in {"Network.webSocketFrameSent", "Network.webSocketFrameReceived"}:
            frame = params.get("response") or {}
            entry = {
                "requestId": request_id,
                "url": created.get(request_id, ""),
                "opcode": frame.get("opcode"),
                "mask": frame.get("mask"),
                "payload": str(frame.get("payloadData") or "")[:50000],
                "at": params.get("timestamp"),
            }
            (sent if method.endswith("FrameSent") else received).append(entry)
        elif method == "Network.webSocketClosed":
            closed.append({"requestId": request_id, "url": created.get(request_id, ""), "at": params.get("timestamp")})

    urls = sorted(set(created.values()))
    return {
        "urls": urls,
        "spectator_urls": [url for url in urls if "/ws/spectate/" in url],
        "presence_urls": [url for url in urls if "/ws/presence" in url or "presence" in url.lower()],
        "other_websocket_urls": [url for url in urls if "/ws/spectate/" not in url and "presence" not in url.lower()],
        "sent_frames": sent[-MAX_CAPTURED_FRAMES:],
        "received_frames": received[-MAX_CAPTURED_FRAMES:],
        "closed": closed,
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

    final_hop_present = any(
        str(message.get("t") or "").lower() == "hopt"
        and str(message.get("fr") or "").lower() == "beach"
        and str(message.get("to") or "").lower() == "ember"
        for message in sent_messages
    )
    return {
        "sent_messages": sent_messages,
        "received_types": dict(received_types),
        "received_regions": dict(received_regions),
        "snapshot_counts": dict(snapshot_counts),
        "ember_player_counts": ember_player_counts,
        "final_beach_to_ember_hopt_present": final_hop_present,
    }


def safe_transition_prelude(sent_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in sent_messages:
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("t") or "").strip().lower()
        if message_type not in ALLOWED_REPLAY_TYPES:
            continue
        serialized = json.dumps(message, sort_keys=True, separators=(",", ":"))
        if serialized in seen:
            continue
        seen.add(serialized)
        output.append(message)
    return output[:30]


def browser_transition_capture() -> dict[str, Any]:
    browser = common.find_browser()
    if browser is None:
        return {"available": False, "error": "Chrome, Edge, or Chromium was not found"}

    user_data_dir = Path(tempfile.mkdtemp(prefix="ctm_anon_transition_"))
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
        session.call("Network.setBlockedURLs", {"urls": ["*terms.html*"]})
        session.call("Network.setExtraHTTPHeaders", {"headers": {"User-Agent": common.USER_AGENT}})
        session.call(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*game.*.js*", "requestStage": "Response"}]},
        )

        # Deliberately do not load or set any account cookie.
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
                            session.call(
                                "Fetch.fulfillRequest",
                                {
                                    "requestId": request_id,
                                    "responseCode": int(params.get("responseStatusCode") or 200),
                                    "responsePhrase": str(params.get("responseStatusText") or "OK"),
                                    "responseHeaders": response_headers_without_encoding(params.get("responseHeaders") or []),
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
            for _index in range(3):
                before = str(browser_state(session).get("gameState") or "").lower()
                expected = EXPECTED_NEXT_STATE.get(before)
                if not expected:
                    break
                result = invoke_official_portal_transition(session)
                observed = wait_for_state(session, expected)
                result["observed_state"] = observed
                transition_results.append(result)
                if str(observed.get("gameState") or "").lower() != expected:
                    break
            time.sleep(POST_EMBER_CAPTURE_SECONDS)

        capture = parse_websocket_events(list(session.events))
        frame_summary = summarize_frames(capture)
        no_presence = not capture.get("presence_urls")
        only_spectator = no_presence and not capture.get("other_websocket_urls")
        return {
            "available": True,
            "browser": str(browser),
            "account_cookie_used": False,
            "presence_allowed": False,
            "terms_blocked": True,
            "patch": patch_meta,
            "api_ready": api_ready,
            "initial_state": initial_state,
            "transition_results": transition_results,
            "final_state": browser_state(session) if api_ready else {"available": False},
            "capture": capture,
            "frame_summary": frame_summary,
            "no_presence_socket_observed": no_presence,
            "only_spectator_websockets_observed": only_spectator,
            "event_count": len(session.events),
        }
    except Exception as exc:
        return {
            "available": True,
            "browser": str(browser),
            "account_cookie_used": False,
            "presence_allowed": False,
            "terms_blocked": True,
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


def websocket_headers() -> list[str]:
    return [
        f"User-Agent: {common.USER_AGENT}",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
    ]


def replay_server(server: dict[str, Any], prelude: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint = common.fanout_spectate_endpoint(server)
    result: dict[str, Any] = {
        "server": str(server.get("name") or "?"),
        "number": common.server_number(server),
        "endpoint": endpoint,
        "account_cookie_used": False,
        "token_used": False,
        "connected": False,
        "sent": [],
        "regions": {},
        "snapshots": {},
        "ember_counts": [],
        "final_count": None,
        "error": "",
    }
    ws = None
    try:
        ws = websocket.create_connection(
            endpoint,
            timeout=12,
            origin=BASE_URL,
            enable_multithread=True,
            header=websocket_headers(),
        )
        ws.settimeout(0.5)
        result["connected"] = True
        for index, message in enumerate(prelude):
            if index:
                time.sleep(random.uniform(0.08, 0.18))
            ws.send(json.dumps(message, separators=(",", ":")))
            result["sent"].append(message)

        started = time.time()
        region_counts: Counter[str] = Counter()
        snapshot_counts: Counter[str] = Counter()
        while time.time() - started < REPLAY_CAPTURE_SECONDS:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for message in common.decode_frame(raw):
                region = str(message.get("region") or "<none>").lower()
                region_counts[region] += 1
                if str(message.get("t") or "") == "snap":
                    snapshot_counts[region] += 1
                    if region == REGION:
                        count = common.player_count(message)
                        result["ember_counts"].append(count)
                        result["final_count"] = count
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


def top_three(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [row for row in rows if isinstance(row.get("final_count"), int)]
    valid.sort(key=lambda row: (-int(row["final_count"]), int(row.get("number") or 9999)))
    return [
        {"server": row["server"], "number": row["number"], "players": row["final_count"]}
        for row in valid[:3]
    ]


def build_summary(report: dict[str, Any]) -> str:
    browser = report.get("browser_transition") or {}
    frame_summary = browser.get("frame_summary") or {}
    capture = browser.get("capture") or {}
    lines = [
        "KINTARA COME TO MOLTEN ANONYMOUS OFFICIAL TRANSITION PROBE",
        "=" * 92,
        f"Created: {report.get('created_at')}",
        f"Project root: {report.get('project_root')}",
        "Account cookie used: False",
        "Presence allowed: False",
        "terms.html blocked: True",
        "",
        "OFFICIAL SPECTATOR TRANSITION",
        "-" * 92,
        f"Runtime patch applied: {(browser.get('patch') or {}).get('patched', False)}",
        f"Spectator API ready: {browser.get('api_ready', False)}",
        f"Initial state: {(browser.get('initial_state') or {}).get('gameState', '-')}",
        f"Final state: {(browser.get('final_state') or {}).get('gameState', '-')}",
        f"Presence WebSocket observed: {bool(capture.get('presence_urls'))}",
        f"Other non-spectator WebSocket observed: {bool(capture.get('other_websocket_urls'))}",
    ]
    for row in browser.get("transition_results") or []:
        lines.append(
            f"{row.get('before', '?'):8s} -> {row.get('expected', '?'):8s} "
            f"ok={row.get('ok')} after={row.get('after')} set={row.get('setName')} "
            f"attempts={len(row.get('attempts') or [])}"
        )
    lines.extend(
        [
            "",
            "CAPTURED SPECTATOR TRAFFIC",
            "-" * 92,
            f"Sent messages: {len(frame_summary.get('sent_messages') or [])}",
            f"Received regions: {frame_summary.get('received_regions') or {}}",
            f"Snapshot counts: {frame_summary.get('snapshot_counts') or {}}",
            f"Final beach->ember hopt present: {frame_summary.get('final_beach_to_ember_hopt_present', False)}",
            f"Ember player samples: {frame_summary.get('ember_player_counts') or []}",
            "",
            "ANONYMOUS REPLAY AND FULL SCAN",
            "-" * 92,
            f"Captured passive prelude: {report.get('transition_prelude') or []}",
            f"Representative verified: {report.get('representative_verified', False)}",
        ]
    )
    for row in report.get("representative_results") or []:
        lines.append(
            f"{row.get('server', '?'):12s} connected={row.get('connected')} "
            f"ember={row.get('ember_counts') or []} error={row.get('error') or '-'}"
        )
    lines.append("")
    if report.get("top3"):
        lines.append("VERIFIED TOP 3")
        lines.append("-" * 92)
        for index, row in enumerate(report["top3"], start=1):
            lines.append(f"{index}. {row['server']} — {row['players']} players")
    else:
        lines.append("No verified Top 3 was produced.")
    lines.extend(["", f"Full report: {report.get('report_path')}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    print("=" * 92)
    print("KINTARA COME TO MOLTEN ANONYMOUS OFFICIAL TRANSITION PROBE")
    print("=" * 92)
    project_root = common.find_project_root()
    print(f"Project root: {project_root}")
    print("Account cookie: NOT USED")
    print("Presence: BLOCKED / NOT USED")
    print("Only the official anonymous Spectator connection is inspected.")
    print("terms.html is blocked.")
    print("-" * 92)

    status, server_payload, route = common.get_json("/api/servers", "")
    normal_servers = [
        dict(row)
        for row in server_payload.get("servers") or []
        if isinstance(row, dict) and common.server_number(row) > 0
    ]
    normal_servers.sort(key=common.server_number)
    print(f"/api/servers: status={status} route={route} normal_servers={len(normal_servers)}")

    print("Capturing the official anonymous portal-transition logic...")
    browser_transition = browser_transition_capture()
    frame_summary = browser_transition.get("frame_summary") or {}
    transition_prelude = safe_transition_prelude(frame_summary.get("sent_messages") or [])
    safe_browser = bool(browser_transition.get("no_presence_socket_observed")) and bool(
        browser_transition.get("only_spectator_websockets_observed")
    )
    browser_ember = bool(frame_summary.get("ember_player_counts"))
    print(
        f"Browser final_state={(browser_transition.get('final_state') or {}).get('gameState', '-')} "
        f"final_hopt={frame_summary.get('final_beach_to_ember_hopt_present', False)} "
        f"ember_snapshots={(frame_summary.get('snapshot_counts') or {}).get('ember', 0)} "
        f"presence_observed={not bool(browser_transition.get('no_presence_socket_observed', False))}"
    )

    representative_results: list[dict[str, Any]] = []
    representative_verified = False
    full_scan: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []

    has_final_hopt = bool(frame_summary.get("final_beach_to_ember_hopt_present"))
    if safe_browser and transition_prelude and has_final_hopt:
        representative_numbers = {4, 12, 23, 26}
        representative_servers = [row for row in normal_servers if common.server_number(row) in representative_numbers]
        print("Replaying only the captured passive Spectator messages on representative servers...")
        for server in representative_servers:
            row = replay_server(server, transition_prelude)
            representative_results.append(row)
            print(
                f"{row['server']}: connected={row['connected']} "
                f"ember={row['ember_counts']} error={row['error'] or '-'}"
            )
        representative_verified = any(row.get("ember_counts") for row in representative_results)

    if safe_browser and (browser_ember or representative_verified):
        print("Verified Ember data. Scanning all 25 normal servers anonymously...")
        with ThreadPoolExecutor(max_workers=MAX_FULL_SCAN_WORKERS) as executor:
            future_map = {executor.submit(replay_server, server, transition_prelude): server for server in normal_servers}
            for future in as_completed(future_map):
                row = future.result()
                full_scan.append(row)
                print(
                    f"{row['server']}: count={row.get('final_count')} "
                    f"error={row.get('error') or '-'}"
                )
        full_scan.sort(key=lambda row: int(row.get("number") or 9999))
        top3 = top_three(full_scan)

    created_at = datetime.now().isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_anonymous_transition_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "anonymous_transition_report.json"
    summary_path = output_dir / "summary.txt"

    report = {
        "created_at": created_at,
        "project_root": str(project_root),
        "account_cookie_used": False,
        "presence_allowed": False,
        "terms_blocked": True,
        "server_list": {
            "status": status,
            "route": route,
            "normal_servers": len(normal_servers),
        },
        "browser_transition": browser_transition,
        "transition_prelude": transition_prelude,
        "representative_results": representative_results,
        "representative_verified": representative_verified,
        "full_scan": full_scan,
        "top3": top3,
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(build_summary(report), encoding="utf-8")

    print("-" * 92)
    if top3:
        print("VERIFIED TOP 3")
        for index, row in enumerate(top3, start=1):
            print(f"{index}. {row['server']} — {row['players']} players")
    else:
        print("No verified Top 3 was produced.")
        print("The report includes the exact official transition function, portal tiles, sent frames, and server responses.")
    print(f"Summary: {summary_path}")
    print(f"Full report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
