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
EMBER_MIN_LEVEL = 25
BROWSER_WAIT_SECONDS = 35.0
ACCOUNT_SETTLE_SECONDS = 4.0
POST_TRANSITION_CAPTURE_SECONDS = 8.0
REPLAY_CAPTURE_SECONDS = 10.0
MAX_FULL_SCAN_WORKERS = 3
REPLAY_MODES = ("anonymous", "cookie", "spectate-token")

WEBSOCKET_GUARD_SCRIPT = r"""
(() => {
  const NativeWebSocket = globalThis.WebSocket;
  const blocked = [];
  const allowed = [];
  Object.defineProperty(globalThis, "__ctmBlockedWebSockets", {value: blocked});
  Object.defineProperty(globalThis, "__ctmAllowedWebSockets", {value: allowed});
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


def as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number < 0 or number > 100000:
        return None
    return number


def normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def extract_account_level(payload: dict[str, Any]) -> tuple[int | None, list[dict[str, Any]]]:
    direct_priority = {
        "avg": 0,
        "avglevel": 1,
        "averagelevel": 2,
        "playeravglevel": 3,
        "localavglevelint": 4,
        "average": 5,
    }
    candidates: list[tuple[int, str, float]] = []
    skill_levels: list[float] = []

    def walk(node: Any, path: str = "root", in_skills: bool = False) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}"
                key_norm = normalized_key(key)
                number = as_number(child)
                if number is not None and key_norm in direct_priority:
                    candidates.append((direct_priority[key_norm], child_path, number))
                next_in_skills = in_skills or key_norm in {"skills", "skilllevels", "levels"}
                if next_in_skills and number is not None and key_norm in {
                    "level", "lvl", "currentlevel", "skilllevel"
                }:
                    skill_levels.append(number)
                walk(child, child_path, next_in_skills)
        elif isinstance(node, list):
            for index, child in enumerate(node[:200]):
                walk(child, f"{path}[{index}]", in_skills)

    player = payload.get("player") if isinstance(payload.get("player"), dict) else None
    if player is not None:
        walk(player, "player")
    else:
        walk(payload)

    report_candidates: list[dict[str, Any]] = []
    for priority, path, number in sorted(candidates, key=lambda row: (row[0], len(row[1]))):
        report_candidates.append({"path": path, "value": number, "kind": "direct"})

    chosen: int | None = None
    if candidates:
        _, _, number = sorted(candidates, key=lambda row: (row[0], len(row[1])))[0]
        chosen = int(number)
    elif skill_levels:
        average = sum(skill_levels) / len(skill_levels)
        chosen = int(average)
        report_candidates.append({
            "path": "player.skills[*].level",
            "value": average,
            "kind": "calculated_average",
            "count": len(skill_levels),
        })
    return chosen, report_candidates[:20]


def browser_state(session: common.CdpSession) -> dict[str, Any]:
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
            if (["number","string","boolean"].includes(typeof value)) return value;
            return null;
          };
          return {
            available:true,
            localAvgLevelInt:scalar(d.localAvgLevelInt),
            localPlayerIdPresent:!!d.localPlayerId,
            canEnterEmberType:typeof d.canEnterEmberOrToast,
            blockedWebSockets:Array.isArray(globalThis.__ctmBlockedWebSockets) ? globalThis.__ctmBlockedWebSockets.slice() : [],
            allowedWebSockets:Array.isArray(globalThis.__ctmAllowedWebSockets) ? globalThis.__ctmAllowedWebSockets.slice() : []
          };
        })()
        """,
    )
    if isinstance(extra, dict):
        state.update(extra)
    return state


def apply_eligible_gate(session: common.CdpSession, account_level: int) -> dict[str, Any]:
    eligible = int(account_level) >= EMBER_MIN_LEVEL
    expression = f"""
    (() => {{
      const api = globalThis.__ctmOfficialSpectatorApi;
      const d = api && api.deps;
      if (!d) return {{applied:false,error:"Spectator dependencies unavailable"}};
      const eligible = {str(eligible).lower()};
      let applied = false;
      let method = "";
      const gate = () => eligible;
      try {{
        d.canEnterEmberOrToast = gate;
        applied = d.canEnterEmberOrToast === gate || d.canEnterEmberOrToast() === eligible;
        if (applied) method = "assignment";
      }} catch (e) {{}}
      if (!applied) {{
        try {{
          Object.defineProperty(d, "canEnterEmberOrToast", {{value:gate,writable:true,configurable:true}});
          applied = d.canEnterEmberOrToast() === eligible;
          if (applied) method = "defineProperty";
        }} catch (e) {{}}
      }}
      try {{ d.localAvgLevelInt = {int(account_level)}; }} catch (e) {{}}
      return {{
        applied,
        method,
        eligible,
        accountLevel:{int(account_level)},
        requiredLevel:{EMBER_MIN_LEVEL},
        gateResult:typeof d.canEnterEmberOrToast === "function" ? !!d.canEnterEmberOrToast() : null,
        localAvgLevelInt:d.localAvgLevelInt ?? null
      }};
    }})()
    """
    value = helpers.runtime_eval(session, expression)
    return value if isinstance(value, dict) else {"applied": False, "error": "No gate result"}


def wait_for_state(session: common.CdpSession, expected: str, timeout: float = 6.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = browser_state(session)
        if str(latest.get("gameState") or "").lower() == expected:
            return latest
        time.sleep(0.15)
    return latest


def invoke_tile(session: common.CdpSession, raw_tile: str) -> dict[str, Any]:
    parts = str(raw_tile).split(",", 1)
    if len(parts) != 2:
        return {"raw": raw_tile, "returned": None, "error": "Invalid portal tile"}
    try:
        col = int(parts[0].strip())
        row = int(parts[1].strip())
    except Exception:
        return {"raw": raw_tile, "returned": None, "error": "Invalid portal coordinates"}
    value = helpers.runtime_eval(
        session,
        f"""
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
        """,
        await_promise=True,
        timeout=15.0,
    )
    output = value if isinstance(value, dict) else {"returned": None, "error": "No transition result"}
    output.update({"raw": raw_tile, "col": col, "row": row})
    return output


def transition_step(session: common.CdpSession) -> dict[str, Any]:
    before_state = browser_state(session)
    before = str(before_state.get("gameState") or "").lower()
    expected = helpers.EXPECTED_NEXT_STATE.get(before)
    set_name = helpers.PORTAL_SET_BY_STATE.get(before)
    if not expected or not set_name:
        return {"ok": False, "before": before, "expected": expected or "", "after": before, "error": "Unsupported transition"}
    values = helpers.runtime_eval(
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
    portal_values = values if isinstance(values, list) else []
    attempts: list[dict[str, Any]] = []
    observed = before_state
    started = time.time()
    for raw_tile in portal_values[:6]:
        attempt = invoke_tile(session, str(raw_tile))
        observed = wait_for_state(session, expected, timeout=3.0)
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
        "values": [str(value) for value in portal_values],
        "attempts": attempts,
        "elapsedMs": int((time.time() - started) * 1000),
        "beforeState": before_state,
        "observedState": observed,
    }


def browser_transition_capture(cookie: str, account_level: int) -> dict[str, Any]:
    browser = common.find_browser()
    if browser is None:
        return {"available": False, "error": "Chrome, Edge, or Chromium was not found"}
    user_data_dir = Path(tempfile.mkdtemp(prefix="ctm_eligible_spectator_"))
    process: subprocess.Popen[str] | None = None
    session: common.CdpSession | None = None
    patch_meta: dict[str, Any] = {"patched": False}
    transition_results: list[dict[str, Any]] = []
    processed_events = 0
    gate_patch: dict[str, Any] = {"applied": False}
    try:
        args = [
            str(browser), "--headless=new", "--disable-gpu", "--disable-background-networking",
            "--disable-component-update", "--disable-default-apps", "--disable-extensions", "--disable-sync",
            "--metrics-recording-only", "--no-first-run", "--no-default-browser-check",
            "--remote-allow-origins=*", "--remote-debugging-port=0", f"--user-data-dir={user_data_dir}", "about:blank",
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
        session.call("Fetch.enable", {"patterns": [{"urlPattern": "*game.*.js*", "requestStage": "Response"}]})

        parsed_cookie = common.parse_cookie(cookie)
        if not parsed_cookie:
            raise RuntimeError("The Kintara session cookie could not be parsed")
        cookie_name, cookie_value = parsed_cookie
        cookie_result = session.call("Network.setCookie", {
            "name": cookie_name, "value": cookie_value, "url": BASE_URL,
            "secure": True, "httpOnly": True, "sameSite": "Strict",
        })
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
                            session.call("Fetch.fulfillRequest", {
                                "requestId": request_id,
                                "responseCode": int(params.get("responseStatusCode") or 200),
                                "responsePhrase": str(params.get("responseStatusText") or "OK"),
                                "responseHeaders": helpers.response_headers_without_encoding(params.get("responseHeaders") or []),
                                "body": base64.b64encode(patched_source.encode("utf-8")).decode("ascii"),
                            })
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

        if api_ready:
            time.sleep(ACCOUNT_SETTLE_SECONDS)
        raw_initial_state = browser_state(session) if api_ready else {"available": False}
        if api_ready:
            gate_patch = apply_eligible_gate(session, account_level)
        patched_initial_state = browser_state(session) if api_ready else {"available": False}

        if api_ready and gate_patch.get("applied") and gate_patch.get("eligible"):
            for _index in range(3):
                before = str(browser_state(session).get("gameState") or "").lower()
                if before not in helpers.EXPECTED_NEXT_STATE:
                    break
                result = transition_step(session)
                transition_results.append(result)
                if not result.get("ok"):
                    break
            time.sleep(POST_TRANSITION_CAPTURE_SECONDS)

        capture = helpers.parse_websocket_events(list(session.events))
        frame_summary = helpers.summarize_frames(capture)
        final_state = browser_state(session) if api_ready else {"available": False}
        blocked_websockets = final_state.get("blockedWebSockets") or []
        allowed_websockets = final_state.get("allowedWebSockets") or []
        non_spectator_created = bool(capture.get("other_websocket_urls"))
        safe_capture = {
            "urls": capture.get("urls") or [],
            "spectator_urls": capture.get("spectator_urls") or [],
            "presence_urls": capture.get("presence_urls") or [],
            "other_websocket_urls": capture.get("other_websocket_urls") or [],
            "sent_messages": frame_summary.get("sent_messages") or [],
        }
        return {
            "available": True,
            "browser": str(browser),
            "cookie_set": cookie_set,
            "presence_allowed": False,
            "terms_blocked": True,
            "patch": patch_meta,
            "api_ready": api_ready,
            "raw_initial_state": raw_initial_state,
            "gate_patch": gate_patch,
            "patched_initial_state": patched_initial_state,
            "transition_results": transition_results,
            "final_state": final_state,
            "capture": safe_capture,
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
            "presence_allowed": False,
            "terms_blocked": True,
            "patch": patch_meta,
            "gate_patch": gate_patch,
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
    headers = [f"User-Agent: {common.USER_AGENT}", "Pragma: no-cache", "Cache-Control: no-cache"]
    if include_cookie and cookie:
        headers.append(f"Cookie: {cookie}")
    return headers


def final_hopt(template: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict(template or {})
    ms = int(source.get("ms") or 360)
    cms = int(source.get("cms") or max(20, ms // 10))
    sms = int(source.get("sms") or max(1, ms - cms))
    if cms + sms != ms:
        ms = cms + sms
    return {
        "t": "hopt", "k": "biome", "ms": ms, "cms": cms, "sms": sms,
        "g": str(source.get("g") or "nosession"), "fr": "beach", "to": "ember",
    }


def build_variants(messages: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    hopt_template: dict[str, Any] | None = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("t") or "").lower()
        if message_type not in helpers.ALLOWED_REPLAY_TYPES:
            continue
        if message_type == "hopt":
            hopt_template = message
        if message_type == "hopt" and str(message.get("fr") or "").lower() == "beach" and str(message.get("to") or "").lower() == "ember":
            continue
        if message_type == "spec_reg" and str(message.get("region") or "").lower() == "ember":
            continue
        key = json.dumps(message, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            clean.append(dict(message))
    spec = {"t": "spec_reg", "region": "ember"}
    hop = final_hopt(hopt_template)
    candidates = [
        ("spec_then_hopt", clean + [spec, hop]),
        ("hopt_then_spec", clean + [hop, spec]),
        ("spec_hopt_spec", clean + [spec, hop, spec]),
    ]
    return candidates


def replay_server(server: dict[str, Any], prelude: list[dict[str, Any]], cookie: str, mode: str, variant: str) -> dict[str, Any]:
    endpoint = common.fanout_spectate_endpoint(server)
    token = ""
    include_cookie = mode in {"cookie", "spectate-token"}
    if mode == "spectate-token":
        token = common.fetch_connect_token(server, cookie, purpose="spectate")
    endpoint_with_token = common.append_token(endpoint, token) if token else endpoint
    result: dict[str, Any] = {
        "server": str(server.get("name") or "?"), "number": common.server_number(server),
        "mode": mode, "variant": variant, "endpoint": endpoint,
        "cookie_header_used": include_cookie, "spectate_token_used": bool(token),
        "presence_used": False, "connected": False, "sent": [], "regions": {}, "snapshots": {},
        "ember_counts": [], "final_count": None, "error": "",
    }
    ws = None
    try:
        ws = websocket.create_connection(
            endpoint_with_token, timeout=12, origin=BASE_URL, enable_multithread=True,
            header=websocket_headers(cookie, include_cookie),
        )
        ws.settimeout(0.5)
        result["connected"] = True
        for index, message in enumerate(prelude):
            if index:
                time.sleep(random.uniform(0.12, 0.28))
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


def top_three(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [row for row in rows if isinstance(row.get("final_count"), int)]
    valid.sort(key=lambda row: (-int(row["final_count"]), int(row.get("number") or 9999)))
    return [{"server": row["server"], "number": row["number"], "players": row["final_count"]} for row in valid[:3]]


def build_summary(report: dict[str, Any]) -> str:
    browser = report.get("browser_transition") or {}
    frames = browser.get("frame_summary") or {}
    lines = [
        "KINTARA COME TO MOLTEN ELIGIBLE SPECTATOR EMBER PROBE",
        "=" * 96,
        f"Created: {report.get('created_at')}",
        f"Project root: {report.get('project_root')}",
        "Presence allowed: False",
        "Only /ws/spectate/ WebSockets are allowed",
        "terms.html blocked: True",
        "Cookie/token values saved: False",
        "Player name/id saved: False",
        "",
        "ACCOUNT ELIGIBILITY",
        "-" * 96,
        f"Auth valid: {(report.get('auth_check') or {}).get('valid')}",
        f"Detected account average level: {(report.get('account_level') or {}).get('value')}",
        f"Required Ember level from current client: {EMBER_MIN_LEVEL}",
        f"Eligible: {(report.get('account_level') or {}).get('eligible')}",
        f"Level source candidates: {(report.get('account_level') or {}).get('candidates') or []}",
        "",
        "OFFICIAL SPECTATOR TRANSITION",
        "-" * 96,
        f"Runtime patch applied: {(browser.get('patch') or {}).get('patched', False)}",
        f"Gate hydration applied: {(browser.get('gate_patch') or {}).get('applied', False)}",
        f"Gate result: {(browser.get('gate_patch') or {}).get('gateResult')}",
        f"Raw client level signal: {(browser.get('raw_initial_state') or {}).get('localAvgLevelInt')}",
        f"Final state: {(browser.get('final_state') or {}).get('gameState', '-')}",
        f"Presence WebSocket created: {browser.get('presence_socket_created', False)}",
        f"Other non-spectator WebSocket created: {browser.get('non_spectator_socket_created', False)}",
    ]
    for row in browser.get("transition_results") or []:
        lines.append(
            f"{row.get('before', '?'):8s} -> {row.get('expected', '?'):8s} "
            f"ok={row.get('ok')} after={row.get('after')} attempts={len(row.get('attempts') or [])}"
        )
    lines.extend([
        "",
        "CAPTURED SPECTATOR TRAFFIC",
        "-" * 96,
        f"Sent messages: {frames.get('sent_messages') or []}",
        f"Snapshot counts: {frames.get('snapshot_counts') or {}}",
        f"Ember player samples: {frames.get('ember_player_counts') or []}",
        "",
        "SPECTATOR-ONLY REPLAY",
        "-" * 96,
        f"Winning mode: {report.get('winning_mode') or '-'}",
        f"Winning variant: {report.get('winning_variant') or '-'}",
    ])
    for row in report.get("probe_results") or []:
        lines.append(
            f"{row.get('mode', '?'):15s} {row.get('variant', '?'):17s} {row.get('server', '?'):12s} "
            f"connected={row.get('connected')} ember={row.get('ember_counts') or []} error={row.get('error') or '-'}"
        )
    lines.append("")
    if report.get("top3"):
        lines.append("VERIFIED TOP 3")
        lines.append("-" * 96)
        for index, row in enumerate(report["top3"], start=1):
            lines.append(f"{index}. {row['server']} — {row['players']} players")
    else:
        lines.append("No verified Top 3 was produced.")
    lines.extend([
        f"Full scan verified servers: {report.get('verified_server_count', 0)}/25",
        "",
        f"Full report: {report.get('report_path')}",
    ])
    return "\n".join(lines) + "\n"


def auth_valid(payload: dict[str, Any]) -> bool:
    if payload.get("ok") is False:
        return False
    return any(bool(payload.get(key)) for key in ("user", "account", "player", "id", "playerId", "authenticated"))


def main() -> int:
    print("=" * 96)
    print("KINTARA COME TO MOLTEN ELIGIBLE SPECTATOR EMBER PROBE")
    print("=" * 96)
    project_root = common.find_project_root()
    env = common.load_env(project_root / ".env")
    cookie = common.normalize_cookie(env)
    print(f"Project root: {project_root}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    print("Presence: HARD-BLOCKED")
    print("Only /ws/spectate/ WebSockets are allowed.")
    print("terms.html is blocked.")
    print("-" * 96)
    if not cookie:
        print("No Kintara session cookie was found in .env.")
        return 2

    auth_status, auth_payload, auth_route = common.get_json("/api/auth/me", cookie)
    valid_session = auth_status == 200 and auth_valid(auth_payload)
    account_level, level_candidates = extract_account_level(auth_payload)
    eligible = account_level is not None and account_level >= EMBER_MIN_LEVEL
    print(f"/api/auth/me: status={auth_status} route={auth_route} valid={valid_session}")
    print(f"Detected account average level: {account_level}")
    print(f"Required Ember level: {EMBER_MIN_LEVEL}")
    print(f"Eligible: {eligible}")

    status, server_payload, route = common.get_json("/api/servers", cookie)
    normal_servers = [
        dict(row) for row in server_payload.get("servers") or []
        if isinstance(row, dict) and common.server_number(row) > 0
    ]
    normal_servers.sort(key=common.server_number)
    print(f"/api/servers: status={status} route={route} normal_servers={len(normal_servers)}")

    browser_transition: dict[str, Any] = {}
    probe_results: list[dict[str, Any]] = []
    verification_results: list[dict[str, Any]] = []
    full_scan: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []
    winning_mode = ""
    winning_variant = ""
    variants: list[tuple[str, list[dict[str, Any]]]] = []

    if valid_session and eligible and account_level is not None:
        print("Running official Spectator transition with the real account eligibility hydrated locally...")
        browser_transition = browser_transition_capture(cookie, account_level)
        frames = browser_transition.get("frame_summary") or {}
        sent_messages = frames.get("sent_messages") or []
        variants = build_variants(sent_messages)
        print(
            f"Browser final_state={(browser_transition.get('final_state') or {}).get('gameState', '-')} "
            f"ember_snapshots={(frames.get('snapshot_counts') or {}).get('ember', 0)} "
            f"presence_socket={browser_transition.get('presence_socket_created', False)}"
        )
        safe = bool(browser_transition.get("spectator_only_verified"))
        has_ember_spec = any(
            str(message.get("t") or "").lower() == "spec_reg" and str(message.get("region") or "").lower() == REGION
            for message in sent_messages if isinstance(message, dict)
        )
        if safe and has_ember_spec and normal_servers:
            primary = next((row for row in normal_servers if common.server_number(row) == 4), normal_servers[0])
            found = False
            for mode in REPLAY_MODES:
                for variant_name, prelude in variants:
                    print(f"Testing {mode} / {variant_name} on {primary.get('name')}")
                    row = replay_server(primary, prelude, cookie, mode, variant_name)
                    probe_results.append(row)
                    print(f"connected={row['connected']} ember={row['ember_counts']} error={row['error'] or '-'}")
                    if row.get("ember_counts"):
                        winning_mode = mode
                        winning_variant = variant_name
                        found = True
                        break
                    time.sleep(random.uniform(0.15, 0.35))
                if found:
                    break

            if winning_mode and winning_variant:
                winning_prelude = next(prelude for name, prelude in variants if name == winning_variant)
                verify_numbers = {12, 23, 26}
                verify_servers = [row for row in normal_servers if common.server_number(row) in verify_numbers]
                for server in verify_servers:
                    row = replay_server(server, winning_prelude, cookie, winning_mode, winning_variant)
                    verification_results.append(row)
                    print(f"Verify {row['server']}: count={row.get('final_count')} error={row.get('error') or '-'}")
                verification_ok = all(isinstance(row.get("final_count"), int) for row in verification_results)
                if verification_ok:
                    print("Protocol verified on representative servers. Scanning all 25 normal servers...")
                    with ThreadPoolExecutor(max_workers=MAX_FULL_SCAN_WORKERS) as executor:
                        future_map = {
                            executor.submit(replay_server, server, winning_prelude, cookie, winning_mode, winning_variant): server
                            for server in normal_servers
                        }
                        for future in as_completed(future_map):
                            row = future.result()
                            full_scan.append(row)
                            print(f"{row['server']}: count={row.get('final_count')} error={row.get('error') or '-'}")
                    full_scan.sort(key=lambda row: int(row.get("number") or 9999))
                    if len(full_scan) == 25 and all(isinstance(row.get("final_count"), int) for row in full_scan):
                        top3 = top_three(full_scan)
    else:
        if not valid_session:
            print("The authenticated session is not valid; no Spectator transition was attempted.")
        elif account_level is None:
            print("The account average level could not be read; no gate hydration was attempted.")
        else:
            print("The account is below the current Ember level requirement; no gate hydration was attempted.")

    created_at = datetime.now().isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_eligible_spectator_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "eligible_spectator_report.json"
    summary_path = output_dir / "summary.txt"
    verified_server_count = sum(1 for row in full_scan if isinstance(row.get("final_count"), int))
    report = {
        "created_at": created_at,
        "project_root": str(project_root),
        "presence_allowed": False,
        "terms_blocked": True,
        "cookie_or_token_values_saved": False,
        "player_identity_saved": False,
        "auth_check": {"status": auth_status, "route": auth_route, "valid": valid_session},
        "account_level": {"value": account_level, "required": EMBER_MIN_LEVEL, "eligible": eligible, "candidates": level_candidates},
        "server_list": {"status": status, "route": route, "normal_servers": len(normal_servers)},
        "browser_transition": browser_transition,
        "replay_variants": [{"name": name, "messages": prelude} for name, prelude in variants],
        "probe_results": probe_results,
        "winning_mode": winning_mode,
        "winning_variant": winning_variant,
        "verification_results": verification_results,
        "full_scan": full_scan,
        "verified_server_count": verified_server_count,
        "top3": top3,
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(build_summary(report), encoding="utf-8")
    print("-" * 96)
    if top3:
        print("VERIFIED TOP 3")
        for index, row in enumerate(top3, start=1):
            print(f"{index}. {row['server']} — {row['players']} players")
    else:
        print("No verified Top 3 was produced.")
    print(f"Summary: {summary_path}")
    print(f"Full report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
