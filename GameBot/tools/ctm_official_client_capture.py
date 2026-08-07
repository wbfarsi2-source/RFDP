from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
import websocket

BASE_URL = "https://kintara.gg"
PLAY_URL = BASE_URL + "/play?spectate=1"
REGION = "ember"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
MAX_SCRIPT_BYTES = 10 * 1024 * 1024
BROWSER_CAPTURE_SECONDS = 18.0
REPLAY_CAPTURE_SECONDS = 8.0
REPLAY_SERVER_LIMIT = 4
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
}


def _candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []

    def add(value: Path | str | None) -> None:
        if not value:
            return
        try:
            path = Path(value).expanduser().resolve()
        except Exception:
            return
        if path not in candidates:
            candidates.append(path)

    add(os.environ.get("GAMEBOT_PROJECT_ROOT"))
    args = list(sys.argv[1:])
    if "--project-root" in args:
        index = args.index("--project-root")
        if index + 1 < len(args):
            add(args[index + 1])

    cwd = Path.cwd()
    script = Path(__file__).resolve()
    add(cwd)
    for parent in cwd.parents:
        add(parent)
    add(script.parent)
    for parent in script.parents:
        add(parent)

    home = Path.home()
    for desktop in (home / "Desktop", home / "OneDrive" / "Desktop"):
        add(desktop / "Start")
        if desktop.exists():
            try:
                for child in desktop.iterdir():
                    if child.is_dir() and child.name.lower() == "start":
                        add(child)
            except OSError:
                pass

    for base in list(candidates):
        add(base / "Start")
        add(base.parent / "Start")
    return candidates


def _project_score(path: Path) -> int:
    score = 0
    if (path / ".env").is_file():
        score += 10
    if (path / "games" / "kintara").is_dir():
        score += 8
    if (path / "START_GAMEBOT.bat").is_file():
        score += 5
    if (path / "app.py").is_file():
        score += 3
    if (path / "data" / "gamebot.db").is_file():
        score += 2
    return score


def find_project_root() -> Path:
    ranked = sorted(
        ((path, _project_score(path)) for path in _candidate_project_roots()),
        key=lambda row: (-row[1], len(str(row[0]))),
    )
    if ranked and ranked[0][1] >= 18:
        return ranked[0][0]
    checked = "\n".join(f"  - {path} (score={score})" for path, score in ranked[:15])
    raise RuntimeError(
        "Could not locate the GameBot project root. The correct folder must contain "
        ".env and games\\kintara.\nChecked locations:\n" + checked
    )


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value.strip()
    return values


def normalize_cookie(env: dict[str, str]) -> str:
    value = str(env.get("KINTARA_EMBER_COOKIE") or env.get("KINTARA_COOKIE") or "").strip()
    if not value:
        return ""
    if "=" not in value:
        return f"__Host-kintara_session={value}"
    return value


def request_headers(cookie: str, accept: str = "application/json,text/plain,*/*") -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/play",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def get_with_fallback(url: str, cookie: str, accept: str) -> tuple[httpx.Response, str]:
    errors: list[str] = []
    for trust_env, route in ((True, "system-route"), (False, "direct-fallback")):
        try:
            with httpx.Client(
                timeout=HTTP_TIMEOUT,
                headers=request_headers(cookie, accept=accept),
                trust_env=trust_env,
                follow_redirects=True,
            ) as client:
                response = client.get(url)
                return response, route
        except Exception as exc:
            errors.append(f"{route}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def get_json(path: str, cookie: str) -> tuple[int, dict[str, Any], str]:
    response, route = get_with_fallback(BASE_URL + path, cookie, "application/json,text/plain,*/*")
    try:
        payload = response.json() if response.content else {}
    except Exception:
        payload = {"raw_preview": response.text[:300]}
    if not isinstance(payload, dict):
        payload = {"value_type": type(payload).__name__, "value": payload}
    return response.status_code, payload, route


def server_number(server: dict[str, Any]) -> int:
    match = re.fullmatch(r"Server\s+(\d+)", str(server.get("name") or "").strip())
    return int(match.group(1)) if match else -1


def route_shard(server: dict[str, Any]) -> int:
    for key in ("routeShardId", "localShardId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def controller_id(server: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(server.get("controllerId") or "").lower())[:24]


def ws_origin(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https:", "wss:", value, flags=re.I)
    value = re.sub(r"^http:", "ws:", value, flags=re.I)
    return value.rstrip("/")


def fanout_spectate_endpoint(server: dict[str, Any]) -> str:
    base = ws_origin(str(server.get("fanoutOrigin") or ""))
    controller = controller_id(server)
    shard = route_shard(server)
    if not base or not controller or shard <= 0:
        raise RuntimeError("Missing fanoutOrigin, controllerId, or routeShardId")
    return f"{base}/ws/spectate/{controller}/s{shard}"


def append_token(url: str, token: str) -> str:
    token = str(token or "").strip()
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}kt={quote(token, safe='')}"


def fetch_connect_token(server: dict[str, Any], cookie: str, purpose: str = "spectate") -> str:
    shard = route_shard(server)
    zone = str(server.get("zone") or "").strip().lower()
    path = f"/api/lobby/connect-token?shard={shard}&purpose={quote(purpose)}"
    if zone:
        path += f"&zone={quote(zone)}"
    status, payload, _route = get_json(path, cookie)
    if status == 200 and payload.get("ok") is not False:
        return str(payload.get("token") or "").strip()
    return ""


def decode_frame(raw: Any) -> list[dict[str, Any]]:
    try:
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if data and data[0] == 1:
                data = gzip.decompress(data[1:])
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        payload = json.loads(text)
    except Exception:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def player_count(message: dict[str, Any]) -> int:
    seen: set[int] = set()
    for player in message.get("players") or []:
        if not isinstance(player, dict):
            continue
        try:
            player_id = int(float(player.get("id") or 0))
        except Exception:
            continue
        if player_id <= 0:
            continue
        if any(bool(player.get(key)) for key in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")):
            continue
        seen.add(player_id)
    return len(seen)


def extract_scripts(html: str, base_url: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(base_url, match.group(1))
        if url not in found:
            found.append(url)
    return found


def context_block(text: str, pattern: str, radius: int = 700, max_items: int = 12) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(pattern, text, flags=re.I):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        block = text[start:end]
        if block not in blocks:
            blocks.append(block)
        if len(blocks) >= max_items:
            break
    return blocks


def static_scan(play_html: str, scripts: list[tuple[str, str]]) -> dict[str, Any]:
    combined = "\n".join(text for _url, text in scripts)
    api_paths = sorted(set(re.findall(r"[\"'`](/api/[A-Za-z0-9_?&=/${}.%:+\-]+)", combined)))
    ws_paths = sorted(set(re.findall(r"[\"'`](/ws/[A-Za-z0-9_?&=/${}.%:+\-]+)", combined)))
    message_types = sorted(
        set(
            re.findall(
                r"\.send\(JSON\.stringify\(\{\s*t\s*:\s*[\"']([^\"']+)[\"']",
                combined,
            )
        )
    )
    quoted_terms = sorted(
        set(
            value
            for value in re.findall(r"[\"']([A-Za-z0-9_./?&=:+\-]{3,90})[\"']", combined)
            if any(token in value.lower() for token in ("ember", "molten", "boss", "cave", "spect", "presence"))
        )
    )
    keywords = [
        "buildSpectateWsUrl",
        "pickSpectateTarget",
        "sendSpectatorRegionUpdate",
        "spec_reg",
        "spectatorReady",
        "new WebSocket",
        "presenceWs",
        "worldChatRegionKey",
        "enterEmberFromBeach",
        "bossCaveActive",
        "bossCaveCapacity",
        "molten",
        "ember",
    ]
    contexts = {keyword: context_block(combined, re.escape(keyword)) for keyword in keywords}
    return {
        "play_html_bytes": len(play_html.encode("utf-8", errors="replace")),
        "api_paths": api_paths,
        "ws_paths": ws_paths,
        "message_types": message_types,
        "quoted_terms": quoted_terms[:500],
        "contexts": contexts,
    }


def find_browser() -> Path | None:
    explicit = os.environ.get("CTM_BROWSER_EXE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_paths = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    for base in env_paths:
        if not base:
            continue
        root = Path(base)
        candidates.extend(
            [
                root / "Google" / "Chrome" / "Application" / "chrome.exe",
                root / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                root / "Chromium" / "Application" / "chrome.exe",
            ]
        )
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe", "chromium", "chromium.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


class CdpSession:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=10, enable_multithread=True)
        self.ws.settimeout(0.5)
        self._next_id = 1
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if "id" in message:
                with self._lock:
                    self._responses[int(message["id"])] = message
            elif "method" in message:
                self.events.append(message)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            call_id = self._next_id
            self._next_id += 1
        payload = {"id": call_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(payload, separators=(",", ":")))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                response = self._responses.pop(call_id, None)
            if response is not None:
                return response
            time.sleep(0.03)
        raise TimeoutError(f"CDP call timed out: {method}")

    def close(self) -> None:
        self._stop.set()
        try:
            self.ws.close()
        except Exception:
            pass
        self._thread.join(timeout=1.0)


def parse_cookie(cookie: str) -> tuple[str, str] | None:
    first = str(cookie or "").split(";", 1)[0].strip()
    if "=" not in first:
        return None
    name, value = first.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not name:
        return None
    return name, value


def browser_capture(cookie: str, output_dir: Path) -> dict[str, Any]:
    browser = find_browser()
    if browser is None:
        return {"available": False, "error": "Chrome, Edge, or Chromium was not found"}

    user_data_dir = Path(tempfile.mkdtemp(prefix="ctm_browser_"))
    process: subprocess.Popen[str] | None = None
    session: CdpSession | None = None
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
        session = CdpSession(str(page["webSocketDebuggerUrl"]))
        session.call("Network.enable")
        session.call("Runtime.enable")
        session.call("Page.enable")
        session.call("Network.setCacheDisabled", {"cacheDisabled": True})
        session.call("Network.setExtraHTTPHeaders", {"headers": {"User-Agent": USER_AGENT}})

        parsed_cookie = parse_cookie(cookie)
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
        while time.time() - started < BROWSER_CAPTURE_SECONDS:
            time.sleep(0.2)

        eval_result = session.call(
            "Runtime.evaluate",
            {
                "expression": """
                (() => ({
                  href: location.href,
                  title: document.title,
                  readyState: document.readyState,
                  globalKeys: Object.getOwnPropertyNames(window)
                    .filter(k => /spect|ember|molten|region|presence|boss|cave/i.test(k))
                    .slice(0, 300),
                  localStorageKeys: Object.keys(localStorage || {}).slice(0, 200),
                  sessionStorageKeys: Object.keys(sessionStorage || {}).slice(0, 200)
                }))()
                """,
                "returnByValue": True,
            },
        )
        runtime_state = (
            eval_result.get("result", {})
            .get("result", {})
            .get("value", {})
        )

        created: dict[str, str] = {}
        sent_frames: list[dict[str, Any]] = []
        received_frames: list[dict[str, Any]] = []
        request_headers: dict[str, Any] = {}
        for event in session.events:
            method = event.get("method")
            params = event.get("params") or {}
            if method == "Network.webSocketCreated":
                created[str(params.get("requestId"))] = str(params.get("url") or "")
            elif method == "Network.webSocketWillSendHandshakeRequest":
                request_id = str(params.get("requestId"))
                request_headers[request_id] = {
                    key: ("<redacted>" if key.lower() in {"cookie", "authorization"} else value)
                    for key, value in ((params.get("request") or {}).get("headers") or {}).items()
                }
            elif method in {"Network.webSocketFrameSent", "Network.webSocketFrameReceived"}:
                frame = params.get("response") or {}
                payload_data = str(frame.get("payloadData") or "")
                entry = {
                    "requestId": str(params.get("requestId")),
                    "url": created.get(str(params.get("requestId")), ""),
                    "opcode": frame.get("opcode"),
                    "mask": frame.get("mask"),
                    "payload": payload_data[:20000],
                    "at": params.get("timestamp"),
                }
                if method.endswith("FrameSent"):
                    sent_frames.append(entry)
                else:
                    received_frames.append(entry)

        spectator_urls = sorted({row["url"] for row in sent_frames + received_frames if "/ws/spectate/" in row["url"]})
        return {
            "available": True,
            "browser": str(browser),
            "runtime_state": runtime_state,
            "websocket_urls": spectator_urls,
            "request_headers": request_headers,
            "sent_frames": sent_frames,
            "received_frames_sample": received_frames[:120],
            "event_count": len(session.events),
        }
    except Exception as exc:
        return {
            "available": True,
            "browser": str(browser),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if session is not None:
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


def parse_json_payload(payload: str) -> dict[str, Any] | None:
    try:
        value = json.loads(payload)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def safe_official_prelude(browser_report: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for frame in browser_report.get("sent_frames") or []:
        if "/ws/spectate/" not in str(frame.get("url") or ""):
            continue
        message = parse_json_payload(str(frame.get("payload") or ""))
        if not message:
            continue
        message_type = str(message.get("t") or "").strip().lower()
        if message_type in SAFE_REPLAY_BLOCKED_TYPES:
            continue
        serialized = json.dumps(message, sort_keys=True, separators=(",", ":"))
        if serialized in seen:
            continue
        seen.add(serialized)
        messages.append(message)
    return messages[:20]


def websocket_headers(cookie: str) -> list[str]:
    headers = [
        f"User-Agent: {USER_AGENT}",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
    ]
    if cookie:
        headers.append(f"Cookie: {cookie}")
    return headers


def replay_server(
    server: dict[str, Any],
    cookie: str,
    official_prelude: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = fanout_spectate_endpoint(server)
    token = fetch_connect_token(server, cookie, purpose="spectate")
    endpoint_with_token = append_token(endpoint, token)
    result: dict[str, Any] = {
        "server": str(server.get("name") or "?"),
        "number": server_number(server),
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
        sent_prelude = False
        sent_ember = False
        first_inbound = False
        region_counts: Counter[str] = Counter()
        snapshot_counts: Counter[str] = Counter()
        while time.time() - started < REPLAY_CAPTURE_SECONDS:
            if not sent_prelude:
                for message in official_prelude:
                    safe_message = dict(message)
                    if str(safe_message.get("t") or "").strip().lower() == "spec_reg":
                        safe_message["region"] = "world"
                    ws.send(json.dumps(safe_message, separators=(",", ":")))
                    result["sent"].append(safe_message)
                sent_prelude = True
            if first_inbound and not sent_ember:
                ember_message = {"t": "spec_reg", "region": REGION}
                ws.send(json.dumps(ember_message, separators=(",", ":")))
                result["sent"].append(ember_message)
                sent_ember = True
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            first_inbound = True
            for message in decode_frame(raw):
                region = str(message.get("region") or "<none>").strip().lower() or "<none>"
                region_counts[region] += 1
                if str(message.get("t") or "") == "snap":
                    snapshot_counts[region] += 1
                    if region == REGION:
                        result["ember_counts"].append(player_count(message))
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


def representative_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for server in servers:
        key = (str(server.get("zone") or ""), controller_id(server))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        chosen.append(server)
        if len(chosen) >= REPLAY_SERVER_LIMIT:
            break
    if not chosen and servers:
        chosen.append(servers[0])
    return chosen


def full_scan_if_winner(
    servers: list[dict[str, Any]],
    cookie: str,
    official_prelude: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for index, server in enumerate(servers):
        if index:
            time.sleep(random.uniform(0.12, 0.28))
        row = replay_server(server, cookie, official_prelude)
        rows.append(row)
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


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"cookie", "token", "connecttoken", "authorization"}:
                output[key] = "<redacted>"
            else:
                output[key] = redact_payload(item)
        return output
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"([?&]kt=)[^&\s]+", r"\1<redacted>", value)
        value = re.sub(r"(__Host-kintara_session=)[^;\s]+", r"\1<redacted>", value)
        return value
    return value


def write_summary(report: dict[str, Any]) -> str:
    lines = [
        "KINTARA COME TO MOLTEN OFFICIAL CLIENT CAPTURE",
        "=" * 86,
        f"Created: {report['created_at']}",
        f"Project root: {report['project_root']}",
        f"Cookie loaded: {report['cookie_present']}",
        f"Normal servers: {report['server_list'].get('normal_servers', 0)}",
        f"Frontend scripts: {len(report['frontend'].get('scripts', []))}",
        "",
        "OFFICIAL BROWSER CAPTURE",
        "-" * 86,
    ]
    browser = report.get("browser_capture") or {}
    lines.append(f"Browser available: {browser.get('available', False)}")
    if browser.get("browser"):
        lines.append(f"Browser: {browser.get('browser')}")
    if browser.get("error"):
        lines.append(f"Browser error: {browser.get('error')}")
    lines.append(f"Spectator WebSocket URLs: {len(browser.get('websocket_urls') or [])}")
    for url in browser.get("websocket_urls") or []:
        lines.append(f"  {url}")
    prelude = report.get("official_prelude") or []
    lines.append(f"Unique safe outbound spectator messages: {len(prelude)}")
    for message in prelude:
        lines.append("  " + json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    lines.extend(["", "REPLAY RESULTS", "-" * 86])
    for row in report.get("replay_results") or []:
        lines.append(
            f"{row.get('server','?'):<13} connected={str(row.get('connected')):<5} "
            f"world={int((row.get('snapshots') or {}).get('world',0)):>3} "
            f"ember={int((row.get('snapshots') or {}).get('ember',0)):>3} "
            f"players={str((row.get('ember_counts') or [None])[-1]):>4} "
            f"error={row.get('error') or '-'}"
        )

    lines.extend(["", "RESULT", "-" * 86])
    if report.get("top3"):
        for index, row in enumerate(report["top3"], 1):
            lines.append(f"{index}. {row['server']} - {row['players']} player(s)")
    elif report.get("winner_found"):
        lines.append("An official spectator prelude produced Ember snapshots, but the full scan was incomplete.")
    else:
        lines.append("The captured official spectator handshake did not produce an Ember snapshot during replay.")
        lines.append("The report still contains the exact current WebSocket URL, outbound frames, source paths, and contexts.")
    lines.append("")
    lines.append(f"Full report: {report['report_path']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print("=" * 88)
    print("KINTARA COME TO MOLTEN OFFICIAL CLIENT AND SERVER-ONLY PROTOCOL CAPTURE")
    print("=" * 88)
    print("This test does not require entering the game manually.")
    print("It opens only /play?spectate=1, current JavaScript files, /api/servers,")
    print("/api/lobby/connect-token, and official read-only spectator WebSockets.")
    print("It does not request terms.html and does not send movement or account-changing messages.")
    print("-" * 88)

    project_root = find_project_root()
    env_path = project_root / ".env"
    env = load_env(env_path)
    cookie = normalize_cookie(env)
    print(f"Project root: {project_root}")
    print(f"Environment file: {env_path}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    if not cookie:
        print("The test requires KINTARA_EMBER_COOKIE or KINTARA_COOKIE in the project .env file.")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_official_capture_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    status, server_payload, server_route = get_json("/api/servers", cookie)
    all_servers = [row for row in server_payload.get("servers") or [] if isinstance(row, dict)]
    normal_servers = sorted(
        [row for row in all_servers if server_number(row) >= 1],
        key=server_number,
    )
    print(f"/api/servers: status={status} normal_servers={len(normal_servers)}")

    play_response, play_route = get_with_fallback(PLAY_URL, cookie, "text/html,application/xhtml+xml")
    play_html = play_response.text
    script_urls = extract_scripts(play_html, PLAY_URL)
    scripts: list[tuple[str, str]] = []
    script_meta: list[dict[str, Any]] = []
    total_script_bytes = 0
    for url in script_urls:
        try:
            response, route = get_with_fallback(url, cookie, "application/javascript,text/javascript,*/*")
            content = response.content[:MAX_SCRIPT_BYTES]
            total_script_bytes += len(content)
            text = content.decode("utf-8", errors="replace")
            scripts.append((url, text))
            script_meta.append(
                {
                    "url": url,
                    "status": response.status_code,
                    "route": route,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(urlparse(url).path).name or "script.js")
            (output_dir / safe_name).write_bytes(content)
        except Exception as exc:
            script_meta.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    frontend_scan = static_scan(play_html, scripts)
    frontend_scan["scripts"] = script_meta
    frontend_scan["play_route"] = play_route
    frontend_scan["play_status"] = play_response.status_code
    (output_dir / "play.html").write_text(play_html, encoding="utf-8", errors="replace")

    print(f"Frontend scripts downloaded: {len(scripts)}")
    print("Starting official headless browser capture...")
    browser_report = browser_capture(cookie, output_dir)
    official_prelude = safe_official_prelude(browser_report)
    print(f"Official outbound spectator messages captured: {len(official_prelude)}")

    replay_targets = representative_servers(normal_servers)
    replay_results: list[dict[str, Any]] = []
    for index, server in enumerate(replay_targets):
        if index:
            time.sleep(random.uniform(0.15, 0.30))
        row = replay_server(server, cookie, official_prelude)
        replay_results.append(row)
        print(
            f"[{row['server']}] connected={row['connected']} "
            f"world={(row.get('snapshots') or {}).get('world', 0)} "
            f"ember={(row.get('snapshots') or {}).get('ember', 0)} "
            f"error={row.get('error') or '-'}"
        )

    winner_found = any(row.get("ember_counts") for row in replay_results)
    full_scan: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []
    if winner_found:
        print("A verified Ember method was found. Running the controlled 25-server scan...")
        full_scan, top3 = full_scan_if_winner(normal_servers, cookie, official_prelude)

    report_path = output_dir / "official_client_report.json"
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
                    "number": server_number(row),
                    "zone": row.get("zone"),
                    "controllerId": row.get("controllerId"),
                    "routeShardId": route_shard(row),
                    "fanoutOrigin": row.get("fanoutOrigin"),
                    "wsBaseUrl": row.get("wsBaseUrl"),
                }
                for row in normal_servers
            ],
        },
        "frontend": frontend_scan,
        "browser_capture": browser_report,
        "official_prelude": official_prelude,
        "replay_results": replay_results,
        "winner_found": winner_found,
        "full_scan": full_scan,
        "top3": top3,
        "report_path": str(report_path),
    }
    redacted_report = redact_payload(report)
    report_path.write_text(json.dumps(redacted_report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = write_summary(redacted_report)
    (output_dir / "summary.txt").write_text(summary, encoding="utf-8")

    print("-" * 88)
    print(summary)
    print(f"Output folder: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
