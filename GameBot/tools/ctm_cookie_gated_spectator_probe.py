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
import ctm_transition_helpers as helpers

BASE_URL = common.BASE_URL
PLAY_URL = common.PLAY_URL
REGION = "ember"
BROWSER_WAIT_SECONDS = 35.0
ACCOUNT_SETTLE_SECONDS = 4.0
STATE_WAIT_SECONDS = 6.0
POST_TRANSITION_CAPTURE_SECONDS = 8.0
REPLAY_CAPTURE_SECONDS = 10.0
MAX_FULL_SCAN_WORKERS = 3
REPLAY_MODES = ("anonymous", "cookie", "spectate-token")


WEBSOCKET_GUARD_SCRIPT = r"""
(() => {
  const NativeWebSocket = globalThis.WebSocket;
  const blocked = [];
  const allowed = [];
  Object.defineProperty(globalThis, "__ctmBlockedWebSockets", {
    value: blocked,
    configurable: false,
    enumerable: false,
    writable: false
  });
  Object.defineProperty(globalThis, "__ctmAllowedWebSockets", {
    value: allowed,
    configurable: false,
    enumerable: false,
    writable: false
  });

  function cleanUrl(value) {
    return String(value || "").replace(/([?&](?:kt|token|auth|key)=)[^&]+/gi, "$1<redacted>");
  }

  function GuardedWebSocket(url, protocols) {
    const raw = String(url || "");
    const safe = cleanUrl(raw);
    if (!/\/ws\/spectate\//i.test(raw)) {
      blocked.push(safe);
      throw new DOMException("Blocked by spectator-only diagnostic", "SecurityError");
    }
    allowed.push(safe);
    if (protocols === undefined) return new NativeWebSocket(url);
    return new NativeWebSocket(url, protocols);
  }

  GuardedWebSocket.prototype = NativeWebSocket.prototype;
  Object.setPrototypeOf(GuardedWebSocket, NativeWebSocket);
  for (const key of ["CONNECTING", "OPEN", "CLOSING", "CLOSED"]) {
    try { Object.defineProperty(GuardedWebSocket, key, {value: NativeWebSocket[key]}); } catch {}
  }
  globalThis.WebSocket = GuardedWebSocket;
})();
"""


def extended_browser_state(session: common.CdpSession) -> dict[str, Any]:
    state = helpers.browser_state(session)
    extra = helpers.runtime_eval(
        session,
        """
        (() => {
          const api = globalThis.__ctmOfficialSpectatorApi;
          const d = api && api.deps;
          if (!d) return {available:false};
          const scalar = (value) => {
            if (value === null || value === undefined) return null;
            if (typeof value === "number" || typeof value === "string" || typeof value === "boolean") return value;
            return null;
          };
          return {
            available:true,
            localAvgLevelInt:scalar(d.localAvgLevelInt),
            beachMinAvgLevel:scalar(d.BEACH_MIN_AVG_LEVEL),
            emberMinAvgLevel:scalar(d.EMBER_MIN_AVG_LEVEL),
            localPlayerId:scalar(d.localPlayerId),
            localPlayerIsClubMember:scalar(d.localPlayerIsClubMember),
            authReady:!!(d.localPlayerId || d.localAvgLevelInt),
            canEnterEmberType:typeof d.canEnterEmberOrToast,
            canEnterEmberSource:typeof d.canEnterEmberOrToast === "function" ? String(d.canEnterEmberOrToast).slice(0,12000) : "",
            blockedWebSockets:Array.isArray(globalThis.__ctmBlockedWebSockets) ? globalThis.__ctmBlockedWebSockets.slice() : [],
            allowedWebSockets:Array.isArray(globalThis.__ctmAllowedWebSockets) ? globalThis.__ctmAllowedWebSockets.slice() : []
          };
        })()
        """,
    )
    if isinstance(extra, dict):
        state.update(extra)
    return state


def wait_for_extended_state(
    session: common.CdpSession,
    expected: str,
    timeout: float = STATE_WAIT_SECONDS,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = extended_browser_state(session)
        if str(latest.get("gameState") or "").lower() == expected:
            return latest
        time.sleep(0.15)
    return latest


def invoke_portal_tile(
    session: common.CdpSession,
    raw_tile: str,
) -> dict[str, Any]:
    parts = str(raw_tile).split(",", 1)
    if len(parts) != 2:
        return {"raw": raw_tile, "returned": None, "error": "Invalid portal tile"}
    try:
        col = int(parts[0].strip())
        row = int(parts[1].strip())
    except Exception:
        return {"raw": raw_tile, "returned": None, "error": "Invalid portal coordinates"}

    expression = f"""
    (async () => {{
      const api = globalThis.__ctmOfficialSpectatorApi;
      if (!api || typeof api.transition !== "function") return {{returned:null,error:"Transition API unavailable"}};
      try {{
        let value = api.transition({col}, {row});
        if (value && typeof value.then === "function") value = await value;
        return {{returned:value,error:""}};
      }} catch (e) {{
        return {{returned:null,error:String(e && e.message || e)}};
      }}
    }})()
    """
    value = helpers.runtime_eval(session, expression, await_promise=True, timeout=15.0)
    output = value if isinstance(value, dict) else {"returned": None, "error": "No transition result"}
    output.update({"raw": raw_tile, "col": col, "row": row})
    return output


def official_transition_step(session: common.CdpSession) -> dict[str, Any]:
    before_state = extended_browser_state(session)
    before = str(before_state.get("gameState") or "").lower()
    expected = helpers.EXPECTED_NEXT_STATE.get(before)
    set_name = helpers.PORTAL_SET_BY_STATE.get(before)
    if not expected or not set_name:
        return {
            "ok": False,
            "before": before,
            "expected": expected or "",
            "after": before,
            "setName": set_name or "",
            "attempts": [],
            "error": "No supported next transition",
        }

    portal_values = helpers.runtime_eval(
        session,
        f"""
        (() => {{
          const api = globalThis.__ctmOfficialSpectatorApi;
          const d = api && api.deps;
          const value = d && d[{json.dumps(set_name)}];
          return value && typeof value[Symbol.iterator] === "function" ? Array.from(value).map(String).slice(0,30) : [];
        }})()
        """,
    )
    values = portal_values if isinstance(portal_values, list) else []
    attempts: list[dict[str, Any]] = []
    observed = before_state

    for raw_tile in values[:6]:
        attempt = invoke_portal_tile(session, str(raw_tile))
        observed = wait_for_extended_state(session, expected, timeout=3.0)
        attempt["state"] = str(observed.get("gameState") or "")
        attempts.append(attempt)
        if str(observed.get("gameState") or "").lower() == expected:
            break

    after = str(observed.get("gameState") or "").lower()
    return {
        "ok": after == expected,
        "before": before,
        "expected": expected,
        "after": after,
        "setName": set_name,
        "values": [str(value) for value in values],
        "attempts": attempts,
        "beforeState": before_state,
        "observedState": observed,
    }


def browser_transition_capture(cookie: str) -> dict[str, Any]:
    browser = common.find_browser()
    if browser is None:
        return {"available": False, "error": "Chrome, Edge, or Chromium was not found"}

    user_data_dir = Path(tempfile.mkdtemp(prefix="ctm_cookie_spectator_"))
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
        session.call("Page.addScriptToEvaluateOnNewDocument", {"source": WEBSOCKET_GUARD_SCRIPT})
        session.call(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*game.*.js*", "requestStage": "Response"}]},
        )

        parsed_cookie = common.parse_cookie(cookie)
        if not parsed_cookie:
            raise RuntimeError("The Kintara session cookie could not be parsed")
        cookie_name, cookie_value = parsed_cookie
        cookie_result = session.call(
            "Network.setCookie",
            {
                "name": cookie_name,
                "value": cookie_value,
                "url": BASE_URL,
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict",
            },
        )
        cookie_set = bool((cookie_result.get("result") or {}).get("success", True))

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
                        patched_source, patch_meta = helpers.patch_game_script(source)
                        if patch_meta.get("patched"):
                            session.call(
                                "Fetch.fulfillRequest",
                                {
                                    "requestId": request_id,
                                    "responseCode": int(params.get("responseStatusCode") or 200),
                                    "responsePhrase": str(params.get("responseStatusText") or "OK"),
                                    "responseHeaders": helpers.response_headers_without_encoding(params.get("responseHeaders") or []),
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
                    state = extended_browser_state(session)
                    if state.get("available") and state.get("spectatorReady"):
                        api_ready = True
                        break
                except Exception:
                    pass
            time.sleep(0.1)

        if api_ready:
            time.sleep(ACCOUNT_SETTLE_SECONDS)
        initial_state = extended_browser_state(session) if api_ready else {"available": False}

        if api_ready:
            for _index in range(3):
                before = str(extended_browser_state(session).get("gameState") or "").lower()
                if before not in helpers.EXPECTED_NEXT_STATE:
                    break
                result = official_transition_step(session)
                transition_results.append(result)
                if not result.get("ok"):
                    break
            time.sleep(POST_TRANSITION_CAPTURE_SECONDS)

        capture = helpers.parse_websocket_events(list(session.events))
        frame_summary = helpers.summarize_frames(capture)
        final_state = extended_browser_state(session) if api_ready else {"available": False}
        blocked_websockets = final_state.get("blockedWebSockets") or []
        allowed_websockets = final_state.get("allowedWebSockets") or []
        presence_observed = bool(capture.get("presence_urls")) or any("presence" in str(url).lower() for url in blocked_websockets)
        non_spectator_created = bool(capture.get("other_websocket_urls"))

        return {
            "available": True,
            "browser": str(browser),
            "cookie_set": cookie_set,
            "account_cookie_used_for_page_gate": True,
            "presence_allowed": False,
            "terms_blocked": True,
            "websocket_guard_installed": True,
            "patch": patch_meta,
            "api_ready": api_ready,
            "initial_state": initial_state,
            "transition_results": transition_results,
            "final_state": final_state,
            "capture": capture,
            "frame_summary": frame_summary,
            "blocked_websockets": blocked_websockets,
            "allowed_websockets": allowed_websockets,
            "presence_socket_created": bool(capture.get("presence_urls")),
            "non_spectator_socket_created": non_spectator_created,
            "spectator_only_verified": not bool(capture.get("presence_urls")) and not non_spectator_created,
            "event_count": len(session.events),
        }
    except Exception as exc:
        return {
            "available": True,
            "browser": str(browser),
            "account_cookie_used_for_page_gate": True,
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


def websocket_headers(cookie: str, include_cookie: bool) -> list[str]:
    headers = [
        f"User-Agent: {common.USER_AGENT}",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
    ]
    if include_cookie and cookie:
        headers.append(f"Cookie: {cookie}")
    return headers


def replay_server(
    server: dict[str, Any],
    prelude: list[dict[str, Any]],
    cookie: str,
    mode: str,
) -> dict[str, Any]:
    endpoint = common.fanout_spectate_endpoint(server)
    token = ""
    include_cookie = mode in {"cookie", "spectate-token"}
    if mode == "spectate-token":
        token = common.fetch_connect_token(server, cookie, purpose="spectate")
    endpoint_with_token = common.append_token(endpoint, token) if token else endpoint

    result: dict[str, Any] = {
        "server": str(server.get("name") or "?"),
        "number": common.server_number(server),
        "mode": mode,
        "endpoint": endpoint,
        "cookie_header_used": include_cookie,
        "spectate_token_used": bool(token),
        "presence_used": False,
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
            endpoint_with_token,
            timeout=12,
            origin=BASE_URL,
            enable_multithread=True,
            header=websocket_headers(cookie, include_cookie),
        )
        ws.settimeout(0.5)
        result["connected"] = True
        for index, message in enumerate(prelude):
            if index:
                time.sleep(random.uniform(0.10, 0.22))
            safe_message = dict(message)
            message_type = str(safe_message.get("t") or "").strip().lower()
            if message_type not in helpers.ALLOWED_REPLAY_TYPES:
                continue
            ws.send(json.dumps(safe_message, separators=(",", ":")))
            result["sent"].append(safe_message)

        started = time.time()
        region_counts: Counter[str] = Counter()
        snapshot_counts: Counter[str] = Counter()
        while time.time() - started < REPLAY_CAPTURE_SECONDS:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
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


def choose_representative_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target_numbers = {4, 12, 23, 26}
    selected = [server for server in servers if common.server_number(server) in target_numbers]
    return selected or servers[:4]


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
        "KINTARA COME TO MOLTEN COOKIE-GATED SPECTATOR PROBE",
        "=" * 92,
        f"Created: {report.get('created_at')}",
        f"Project root: {report.get('project_root')}",
        "Account cookie used: page authentication gate only",
        "Presence allowed: False",
        "Only /ws/spectate/ WebSockets are allowed",
        "terms.html blocked: True",
        "",
        "AUTHENTICATION CHECK",
        "-" * 92,
        f"/api/auth/me status: {(report.get('auth_check') or {}).get('status')}",
        f"Session valid: {(report.get('auth_check') or {}).get('valid')}",
        "",
        "OFFICIAL COOKIE-GATED SPECTATOR TRANSITION",
        "-" * 92,
        f"Runtime patch applied: {(browser.get('patch') or {}).get('patched', False)}",
        f"Spectator API ready: {browser.get('api_ready', False)}",
        f"Cookie set in temporary browser: {browser.get('cookie_set', False)}",
        f"Initial state: {(browser.get('initial_state') or {}).get('gameState', '-')}",
        f"Final state: {(browser.get('final_state') or {}).get('gameState', '-')}",
        f"Initial account level signal: {(browser.get('initial_state') or {}).get('localAvgLevelInt')}",
        f"Presence WebSocket created: {browser.get('presence_socket_created', False)}",
        f"Other non-spectator WebSocket created: {browser.get('non_spectator_socket_created', False)}",
        f"Blocked WebSockets: {browser.get('blocked_websockets') or []}",
        f"Allowed WebSockets: {browser.get('allowed_websockets') or []}",
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
            "SPECTATOR-ONLY REPLAY",
            "-" * 92,
            f"Captured prelude: {report.get('transition_prelude') or []}",
            f"Winning replay mode: {report.get('winning_mode') or '-'}",
        ]
    )
    for row in report.get("representative_results") or []:
        lines.append(
            f"{row.get('mode', '?'):15s} {row.get('server', '?'):12s} "
            f"connected={row.get('connected')} ember={row.get('ember_counts') or []} "
            f"error={row.get('error') or '-'}"
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


def auth_valid(payload: dict[str, Any]) -> bool:
    if payload.get("ok") is False:
        return False
    candidates = [
        payload.get("user"),
        payload.get("account"),
        payload.get("player"),
        payload.get("id"),
        payload.get("playerId"),
        payload.get("authenticated"),
    ]
    return any(bool(value) for value in candidates)


def main() -> int:
    print("=" * 92)
    print("KINTARA COME TO MOLTEN COOKIE-GATED SPECTATOR PROBE")
    print("=" * 92)
    project_root = common.find_project_root()
    env = common.load_env(project_root / ".env")
    cookie = common.normalize_cookie(env)
    print(f"Project root: {project_root}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    print("Presence: HARD-BLOCKED")
    print("Only /ws/spectate/ WebSockets are allowed.")
    print("The account is not placed into a gameplay Presence session.")
    print("terms.html is blocked.")
    print("-" * 92)

    if not cookie:
        print("No Kintara session cookie was found in .env.")
        return 2

    auth_status, auth_payload, auth_route = common.get_json("/api/auth/me", cookie)
    valid_session = auth_status == 200 and auth_valid(auth_payload)
    print(f"/api/auth/me: status={auth_status} route={auth_route} valid={valid_session}")
    if not valid_session:
        print("The cookie is not accepted as an authenticated Kintara session.")
        return 3

    status, server_payload, route = common.get_json("/api/servers", cookie)
    normal_servers = [
        dict(row)
        for row in server_payload.get("servers") or []
        if isinstance(row, dict) and common.server_number(row) > 0
    ]
    normal_servers.sort(key=common.server_number)
    print(f"/api/servers: status={status} route={route} normal_servers={len(normal_servers)}")

    print("Running the official Spectator transition with the authenticated page gate...")
    browser_transition = browser_transition_capture(cookie)
    frame_summary = browser_transition.get("frame_summary") or {}
    transition_prelude = helpers.safe_transition_prelude(frame_summary.get("sent_messages") or [])
    browser_safe = bool(browser_transition.get("spectator_only_verified"))
    browser_ember = bool(frame_summary.get("ember_player_counts"))
    final_state = (browser_transition.get("final_state") or {}).get("gameState", "-")
    print(
        f"Browser final_state={final_state} "
        f"ember_snapshots={(frame_summary.get('snapshot_counts') or {}).get('ember', 0)} "
        f"presence_socket={browser_transition.get('presence_socket_created', False)} "
        f"other_socket={browser_transition.get('non_spectator_socket_created', False)}"
    )

    representative_results: list[dict[str, Any]] = []
    winning_mode = ""
    full_scan: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []

    has_ember_request = any(
        str(message.get("t") or "").lower() == "spec_reg"
        and str(message.get("region") or "").lower() == REGION
        for message in transition_prelude
        if isinstance(message, dict)
    )

    if browser_safe and transition_prelude and has_ember_request:
        representatives = choose_representative_servers(normal_servers)
        for mode in REPLAY_MODES:
            print(f"Testing spectator-only replay mode: {mode}")
            mode_rows: list[dict[str, Any]] = []
            for server in representatives:
                row = replay_server(server, transition_prelude, cookie, mode)
                representative_results.append(row)
                mode_rows.append(row)
                print(
                    f"{row['server']}: connected={row['connected']} "
                    f"ember={row['ember_counts']} error={row['error'] or '-'}"
                )
                time.sleep(random.uniform(0.12, 0.30))
            if any(row.get("ember_counts") for row in mode_rows):
                winning_mode = mode
                break

    if browser_safe and (browser_ember or winning_mode):
        scan_mode = winning_mode or "cookie"
        print(f"Verified Ember data. Scanning all 25 normal servers with mode={scan_mode}...")
        with ThreadPoolExecutor(max_workers=MAX_FULL_SCAN_WORKERS) as executor:
            future_map = {
                executor.submit(replay_server, server, transition_prelude, cookie, scan_mode): server
                for server in normal_servers
            }
            for future in as_completed(future_map):
                row = future.result()
                full_scan.append(row)
                print(f"{row['server']}: count={row.get('final_count')} error={row.get('error') or '-'}")
        full_scan.sort(key=lambda row: int(row.get("number") or 9999))
        top3 = top_three(full_scan)

    created_at = datetime.now().isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_cookie_spectator_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "cookie_spectator_report.json"
    summary_path = output_dir / "summary.txt"

    report = {
        "created_at": created_at,
        "project_root": str(project_root),
        "cookie_present": True,
        "cookie_value_saved": False,
        "account_cookie_scope": "Temporary browser page authentication and optional Spectator-only replay",
        "presence_allowed": False,
        "terms_blocked": True,
        "auth_check": {
            "status": auth_status,
            "route": auth_route,
            "valid": valid_session,
        },
        "server_list": {
            "status": status,
            "route": route,
            "normal_servers": len(normal_servers),
        },
        "browser_transition": browser_transition,
        "transition_prelude": transition_prelude,
        "representative_results": representative_results,
        "winning_mode": winning_mode,
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
        print("The report records the authenticated gate state, exact Spectator frames, and all server responses.")
    print(f"Summary: {summary_path}")
    print(f"Full report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
