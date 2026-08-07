from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError as exc:
    raise SystemExit("Missing dependency: httpx. Run this test from the GameBot project environment.") from exc

try:
    import websocket
except ImportError as exc:
    raise SystemExit("Missing dependency: websocket-client. Run this test from the GameBot project environment.") from exc

BASE_DEFAULT = "https://kintara.gg"
ORIGIN_DEFAULT = "https://kintara.gg"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

CONNECT_TIMEOUT_SECONDS = 12.0
SOCKET_READ_TIMEOUT_SECONDS = 0.35
INITIAL_WORLD_TIMEOUT_SECONDS = 9.0
DIRECT_CAPTURE_SECONDS = 8.0
PATH_PHASE_SECONDS = 3.5
START_STAGGER_MIN_SECONDS = 0.12
START_STAGGER_MAX_SECONDS = 0.35
MAX_WORKERS = 6
MAX_SCRIPT_FILES = 8
MAX_SCRIPT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_SCRIPT_BYTES = 16 * 1024 * 1024

SENSITIVE_TOKENS = (
    "cookie",
    "token",
    "secret",
    "authorization",
    "proof",
    "session",
    "password",
)

PLAYER_MARKER_FIELDS = (
    "id",
    "pid",
    "playerId",
    "player_id",
    "type",
    "kind",
    "entityType",
    "entity_type",
    "npcType",
    "npc_type",
    "mobType",
    "mob_type",
    "isNpc",
    "isNPC",
    "npc",
    "isMob",
    "isBoss",
    "isPet",
    "populationBotGroup",
    "name",
    "username",
    "displayName",
    "region",
)

_print_lock = threading.Lock()


def safe_print(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".env").exists() or (candidate / "START_GAMEBOT.bat").exists():
            return candidate
    return start


def hash_value(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]


def redact_scalar(key: str, value: Any) -> Any:
    low = key.lower()
    if any(token in low for token in SENSITIVE_TOKENS):
        return "<redacted>"
    if key in ("name", "username", "displayName") and value not in (None, ""):
        return f"<name:{hash_value(value)}>"
    if key in ("id", "pid", "playerId", "player_id") and value not in (None, ""):
        return f"<id:{hash_value(value)}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def sanitized_player(player: Any) -> dict[str, Any]:
    if not isinstance(player, dict):
        return {"value_type": type(player).__name__}
    result: dict[str, Any] = {
        "keys": sorted(str(key) for key in player.keys()),
        "types": {str(key): type(value).__name__ for key, value in sorted(player.items(), key=lambda row: str(row[0]))},
    }
    markers: dict[str, Any] = {}
    for key in PLAYER_MARKER_FIELDS:
        if key in player:
            markers[key] = redact_scalar(key, player.get(key))
    if markers:
        result["markers"] = markers
    return result


def sanitized_message(message: dict[str, Any], at_ms: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "at_ms": at_ms,
        "t": str(message.get("t") or ""),
        "region": str(message.get("region") or ""),
        "keys": sorted(str(key) for key in message.keys()),
    }
    for key in ("onlineTotal", "n", "evt", "kind", "full", "queueLength", "npcHostId"):
        if key in message:
            result[key] = redact_scalar(key, message.get(key))
    players = message.get("players")
    if isinstance(players, list):
        result["players_count"] = len(players)
        result["player_shapes"] = [sanitized_player(row) for row in players[:8]]
    return result


def decode_frames(raw: Any) -> list[dict[str, Any]]:
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
        return [item for item in payload if isinstance(item, dict)]
    return []


def server_number(server: dict[str, Any]) -> int:
    match = re.fullmatch(r"Server\s+(\d+)", str(server.get("name") or "").strip())
    return int(match.group(1)) if match else -1


def route_shard_id(server: dict[str, Any]) -> int:
    for key in ("routeShardId", "localShardId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def spectator_url(server: dict[str, Any]) -> str:
    shard = route_shard_id(server)
    if shard <= 0:
        raise RuntimeError("Invalid spectator shard")
    base = str(server.get("wsBaseUrl") or "").strip()
    if not base:
        base = BASE_DEFAULT
    if not base.startswith(("ws://", "wss://")):
        base = re.sub(r"^http", "ws", base, flags=re.I)
    return base.rstrip("/") + f"/ws/spectate/s{shard}"


def connect_ws(server: dict[str, Any]):
    endpoint = spectator_url(server)
    common = {
        "timeout": CONNECT_TIMEOUT_SECONDS,
        "origin": ORIGIN_DEFAULT,
        "enable_multithread": True,
        "header": [
            f"User-Agent: {USER_AGENT}",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
        ],
    }
    try:
        return websocket.create_connection(endpoint, **common)
    except Exception as first_error:
        try:
            return websocket.create_connection(
                endpoint,
                **common,
                http_proxy_host=None,
                http_proxy_port=None,
                proxy_type=None,
                http_no_proxy=["*"],
            )
        except Exception as second_error:
            raise RuntimeError(
                f"WebSocket connection failed through the system route and direct fallback: "
                f"{type(first_error).__name__}: {first_error} | "
                f"{type(second_error).__name__}: {second_error}"
            ) from second_error


def send_region(ws, region: str, events: list[dict[str, Any]], started: float, label: str) -> None:
    payload = {"t": "spec_reg", "region": region}
    ws.send(json.dumps(payload, separators=(",", ":")))
    events.append(
        {
            "at_ms": int((time.monotonic() - started) * 1000),
            "direction": "out",
            "label": label,
            "payload": payload,
        }
    )


def receive_until(
    ws,
    *,
    started: float,
    duration: float,
    events: list[dict[str, Any]],
    message_counts: Counter[str],
    region_counts: Counter[str],
    snapshot_counts: Counter[str],
    latest_players: dict[str, int],
    stop_condition: Callable[[], bool] | None = None,
    max_saved_events: int = 80,
) -> None:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if stop_condition is not None and stop_condition():
            return
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        if raw in (None, ""):
            raise RuntimeError("Spectator socket closed")
        for message in decode_frames(raw):
            msg_type = str(message.get("t") or "<none>")
            region = str(message.get("region") or "").strip().lower() or "<none>"
            message_counts[msg_type] += 1
            region_counts[region] += 1
            if msg_type == "snap":
                snapshot_counts[region] += 1
                players = message.get("players")
                if isinstance(players, list):
                    latest_players[region] = len(players)
            if len(events) < max_saved_events:
                events.append(
                    {
                        "direction": "in",
                        **sanitized_message(message, int((time.monotonic() - started) * 1000)),
                    }
                )


def run_direct_probe(server: dict[str, Any]) -> dict[str, Any]:
    name = str(server.get("name") or "?")
    result: dict[str, Any] = {
        "scenario": "delayed-direct-ember",
        "server": name,
        "endpoint": spectator_url(server),
        "connected": False,
        "message_counts": {},
        "region_counts": {},
        "snapshot_counts": {},
        "latest_players": {},
        "first_world_ms": None,
        "first_ember_ms": None,
        "events": [],
        "error": "",
    }
    ws = None
    started = time.monotonic()
    message_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    snapshot_counts: Counter[str] = Counter()
    latest_players: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    try:
        ws = connect_ws(server)
        ws.settimeout(SOCKET_READ_TIMEOUT_SECONDS)
        result["connected"] = True

        first_world_seen = False

        def world_ready() -> bool:
            return snapshot_counts.get("world", 0) >= 1

        receive_until(
            ws,
            started=started,
            duration=INITIAL_WORLD_TIMEOUT_SECONDS,
            events=events,
            message_counts=message_counts,
            region_counts=region_counts,
            snapshot_counts=snapshot_counts,
            latest_players=latest_players,
            stop_condition=world_ready,
        )
        first_world_seen = world_ready()
        if first_world_seen:
            for event in events:
                if event.get("direction") == "in" and event.get("t") == "snap" and event.get("region") == "world":
                    result["first_world_ms"] = event.get("at_ms")
                    break

        time.sleep(random.uniform(0.18, 0.34))
        send_region(ws, "ember", events, started, "after-first-world")
        time.sleep(random.uniform(0.22, 0.42))
        send_region(ws, "ember", events, started, "confirmation")

        def ember_ready() -> bool:
            return snapshot_counts.get("ember", 0) >= 2

        receive_until(
            ws,
            started=started,
            duration=DIRECT_CAPTURE_SECONDS / 2,
            events=events,
            message_counts=message_counts,
            region_counts=region_counts,
            snapshot_counts=snapshot_counts,
            latest_players=latest_players,
            stop_condition=ember_ready,
        )
        if not ember_ready():
            send_region(ws, "ember", events, started, "single-retry")
            receive_until(
                ws,
                started=started,
                duration=DIRECT_CAPTURE_SECONDS / 2,
                events=events,
                message_counts=message_counts,
                region_counts=region_counts,
                snapshot_counts=snapshot_counts,
                latest_players=latest_players,
                stop_condition=ember_ready,
            )

        for event in events:
            if event.get("direction") == "in" and event.get("t") == "snap" and event.get("region") == "ember":
                result["first_ember_ms"] = event.get("at_ms")
                break
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass

    result["message_counts"] = dict(message_counts)
    result["region_counts"] = dict(region_counts)
    result["snapshot_counts"] = dict(snapshot_counts)
    result["latest_players"] = dict(latest_players)
    result["events"] = events
    safe_print(
        f"[{name}] direct test: world={snapshot_counts.get('world', 0)} "
        f"ember={snapshot_counts.get('ember', 0)} error={result['error'] or '-'}"
    )
    return result


def run_path_probe(server: dict[str, Any]) -> dict[str, Any]:
    name = str(server.get("name") or "?")
    result: dict[str, Any] = {
        "scenario": "official-realm-order",
        "server": name,
        "endpoint": spectator_url(server),
        "connected": False,
        "phases": [],
        "message_counts": {},
        "region_counts": {},
        "snapshot_counts": {},
        "latest_players": {},
        "events": [],
        "error": "",
    }
    ws = None
    started = time.monotonic()
    message_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    snapshot_counts: Counter[str] = Counter()
    latest_players: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    try:
        ws = connect_ws(server)
        ws.settimeout(SOCKET_READ_TIMEOUT_SECONDS)
        result["connected"] = True

        receive_until(
            ws,
            started=started,
            duration=INITIAL_WORLD_TIMEOUT_SECONDS,
            events=events,
            message_counts=message_counts,
            region_counts=region_counts,
            snapshot_counts=snapshot_counts,
            latest_players=latest_players,
            stop_condition=lambda: snapshot_counts.get("world", 0) >= 1,
            max_saved_events=140,
        )

        for region in ("pond", "beach", "ember"):
            before = snapshot_counts.get(region, 0)
            time.sleep(random.uniform(0.18, 0.36))
            send_region(ws, region, events, started, f"path-{region}")
            receive_until(
                ws,
                started=started,
                duration=PATH_PHASE_SECONDS,
                events=events,
                message_counts=message_counts,
                region_counts=region_counts,
                snapshot_counts=snapshot_counts,
                latest_players=latest_players,
                stop_condition=lambda region=region, before=before: snapshot_counts.get(region, 0) >= before + 2,
                max_saved_events=140,
            )
            result["phases"].append(
                {
                    "region": region,
                    "snapshots_received": snapshot_counts.get(region, 0) - before,
                    "latest_players": latest_players.get(region),
                }
            )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass

    result["message_counts"] = dict(message_counts)
    result["region_counts"] = dict(region_counts)
    result["snapshot_counts"] = dict(snapshot_counts)
    result["latest_players"] = dict(latest_players)
    result["events"] = events
    safe_print(
        f"[{name}] path test: pond={snapshot_counts.get('pond', 0)} "
        f"beach={snapshot_counts.get('beach', 0)} ember={snapshot_counts.get('ember', 0)} "
        f"error={result['error'] or '-'}"
    )
    return result


def request_json_with_fallback(base_url: str, cookie: str) -> tuple[dict[str, Any], str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Origin": base_url,
        "Referer": base_url + "/play",
    }
    if cookie:
        headers["Cookie"] = cookie
    errors: list[str] = []
    for trust_env, route in ((True, "system-route"), (False, "direct-fallback")):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=12.0),
                headers=headers,
                trust_env=trust_env,
                follow_redirects=True,
            ) as client:
                response = client.get(base_url + "/api/servers")
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("Server list response is not an object")
                return payload, route
        except Exception as exc:
            errors.append(f"{route}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def request_text(client: httpx.Client, url: str, max_bytes: int) -> tuple[int, str]:
    response = client.get(url)
    status = response.status_code
    if status >= 400:
        return status, ""
    data = response.content[:max_bytes]
    return status, data.decode("utf-8", errors="replace")


def same_origin_scripts(html: str, page_url: str, base_url: str) -> list[str]:
    found: list[str] = []
    base_host = urlparse(base_url).netloc
    for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(page_url, match.group(1))
        parsed = urlparse(url)
        if parsed.netloc != base_host:
            continue
        if "terms" in parsed.path.lower():
            continue
        if url not in found:
            found.append(url)
    return found


def contexts(text: str, needle: str, radius: int = 600, limit: int = 20) -> list[str]:
    output: list[str] = []
    start = 0
    while len(output) < limit:
        index = text.find(needle, start)
        if index < 0:
            break
        output.append(text[max(0, index - radius): min(len(text), index + len(needle) + radius)])
        start = index + len(needle)
    return output


def static_frontend_scan(base_url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for trust_env, route in ((True, "system-route"), (False, "direct-fallback")):
        result: dict[str, Any] = {
            "route": route,
            "pages": [],
            "scripts": [],
            "world_chat_region_function": [],
            "spec_reg_contexts": [],
            "spectator_update_alias": "",
            "spectator_update_call_contexts": [],
            "realm_transition_contexts": [],
            "spectate_api_contexts": [],
        }
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/javascript,*/*"}
        script_urls: list[str] = []
        try:
            with httpx.Client(
                timeout=httpx.Timeout(25.0, connect=12.0),
                headers=headers,
                trust_env=trust_env,
                follow_redirects=True,
            ) as client:
                for path in ("/", "/play"):
                    url = base_url + path
                    status, text = request_text(client, url, 512 * 1024)
                    result["pages"].append({"url": url, "status": status, "bytes": len(text.encode('utf-8'))})
                    if status < 400:
                        script_urls.extend(same_origin_scripts(text, url, base_url))
                    time.sleep(random.uniform(0.18, 0.38))

                total = 0
                for url in script_urls[:MAX_SCRIPT_FILES]:
                    remaining = MAX_TOTAL_SCRIPT_BYTES - total
                    if remaining <= 0:
                        break
                    status, text = request_text(client, url, min(MAX_SCRIPT_BYTES, remaining))
                    total += len(text.encode("utf-8"))
                    result["scripts"].append({"url": url, "status": status, "bytes": len(text.encode('utf-8'))})
                    if not text:
                        continue

                    for item in contexts(text, 'a(Zw,"worldChatRegionKey")', radius=1400, limit=3):
                        result["world_chat_region_function"].append({"url": url, "context": item})
                    for item in contexts(text, '"spec_reg"', radius=900, limit=12):
                        result["spec_reg_contexts"].append({"url": url, "context": item})
                    for item in contexts(text, "trySpectatorRealmTransitionAt", radius=1000, limit=8):
                        result["realm_transition_contexts"].append({"url": url, "context": item})
                    for needle in ("/api/spectate/", "/ws/spectate/"):
                        for item in contexts(text, needle, radius=900, limit=12):
                            result["spectate_api_contexts"].append({"url": url, "needle": needle, "context": item})

                    alias_match = re.search(r"sendSpectatorRegionUpdate:([A-Za-z_$][A-Za-z0-9_$]*)", text)
                    if alias_match:
                        alias = alias_match.group(1)
                        result["spectator_update_alias"] = alias
                        for item in contexts(text, alias + "(", radius=900, limit=20):
                            result["spectator_update_call_contexts"].append({"url": url, "alias": alias, "context": item})
                    time.sleep(random.uniform(0.18, 0.38))
            return result
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def build_summary(report: dict[str, Any]) -> str:
    direct = report.get("direct_probes") or []
    path = report.get("path_probes") or []
    connected = sum(1 for row in direct if row.get("connected"))
    direct_success = sum(1 for row in direct if int((row.get("snapshot_counts") or {}).get("ember", 0)) >= 1)
    lines = [
        "KINTARA COME TO MOLTEN DEEP PROTOCOL PROBE",
        "=" * 84,
        f"Created: {report.get('created_at')}",
        f"Numbered servers: {report.get('server_list', {}).get('count', 0)}",
        f"Direct probes connected: {connected}/{len(direct)}",
        f"Direct delayed Ember subscriptions: {direct_success}/{len(direct)}",
        "",
        "DIRECT PROBE RESULTS",
        "-" * 84,
    ]
    for row in direct:
        counts = row.get("snapshot_counts") or {}
        players = row.get("latest_players") or {}
        lines.append(
            f"{str(row.get('server') or '?'):<12} "
            f"world={int(counts.get('world', 0)):>3} "
            f"ember={int(counts.get('ember', 0)):>3} "
            f"ember_players={str(players.get('ember', '-')):>3} "
            f"first_ember_ms={str(row.get('first_ember_ms') or '-'):>6} "
            f"error={row.get('error') or '-'}"
        )
    lines.extend(["", "OFFICIAL REALM ORDER RESULTS", "-" * 84])
    for row in path:
        phase_text = ", ".join(
            f"{phase.get('region')}={phase.get('snapshots_received')} snap(s), players={phase.get('latest_players')}"
            for phase in (row.get("phases") or [])
        )
        lines.append(f"{row.get('server')}: {phase_text or '-'} | error={row.get('error') or '-'}")

    static = report.get("frontend_scan") or {}
    lines.extend(
        [
            "",
            "FRONTEND PROTOCOL SCAN",
            "-" * 84,
            f"Scripts checked: {len(static.get('scripts') or [])}",
            f"Region function blocks: {len(static.get('world_chat_region_function') or [])}",
            f"spec_reg contexts: {len(static.get('spec_reg_contexts') or [])}",
            f"Spectator update alias: {static.get('spectator_update_alias') or '-'}",
            f"Alias call contexts: {len(static.get('spectator_update_call_contexts') or [])}",
            f"Realm transition contexts: {len(static.get('realm_transition_contexts') or [])}",
            "",
            "Send summary.txt and deep_protocol_report.json for review.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    root = find_project_root(Path.cwd().resolve())
    load_env(root / ".env")
    base_url = str(os.environ.get("KINTARA_BASE_URL") or BASE_DEFAULT).rstrip("/")
    cookie = str(
        os.environ.get("KINTARA_EMBER_COOKIE")
        or os.environ.get("KINTARA_COOKIE")
        or ""
    ).strip()

    output_dir = root / "diagnostics" / ("ctm_deep_protocol_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("KINTARA COME TO MOLTEN DEEP PROTOCOL PROBE")
    print("=" * 84)
    print(f"Project root: {root}")
    print(f"Base URL: {base_url}")
    print(f"Cookie for /api/servers: {'loaded' if cookie else 'not found'}")
    print("Allowed HTTP paths: /, /play, discovered same-origin JavaScript, /api/servers")
    print("Allowed WebSocket path: /ws/spectate")
    print("The test never requests terms.html and never sends movement or gameplay actions.")
    print("Connections are staggered by 120-350 ms and each connection sends at most three region registrations.")
    print(f"Output: {output_dir}")
    print("-" * 84)

    payload, route = request_json_with_fallback(base_url, cookie)
    rows = [
        dict(row)
        for row in (payload.get("servers") or [])
        if isinstance(row, dict) and server_number(row) >= 1
    ]
    rows.sort(key=server_number)
    if not rows:
        raise RuntimeError("No numbered servers were returned")

    server_list = {
        "status": 200,
        "route": route,
        "count": len(rows),
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "server_field_sets": sorted({tuple(sorted(str(key) for key in row.keys())) for row in rows}),
        "servers": rows,
    }
    server_list["server_field_sets"] = [list(item) for item in server_list["server_field_sets"]]

    safe_print(f"Found {len(rows)} numbered servers. Starting staggered direct probes...")
    direct_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="ctm-probe") as executor:
        futures = []
        for row in rows:
            futures.append(executor.submit(run_direct_probe, row))
            time.sleep(random.uniform(START_STAGGER_MIN_SECONDS, START_STAGGER_MAX_SECONDS))
        for future in as_completed(futures):
            direct_results.append(future.result())
    direct_results.sort(key=lambda row: server_number({"name": row.get("server")}))

    representatives: list[dict[str, Any]] = []
    for wanted in (24, 4):
        match = next((row for row in rows if server_number(row) == wanted), None)
        if match is not None:
            representatives.append(match)
    if not representatives:
        representatives = rows[:2]

    safe_print("Starting official realm-order probes on representative servers...")
    path_results: list[dict[str, Any]] = []
    for row in representatives:
        path_results.append(run_path_probe(row))
        time.sleep(random.uniform(0.3, 0.5))

    safe_print("Scanning the current official frontend protocol...")
    frontend_scan: dict[str, Any]
    try:
        frontend_scan = static_frontend_scan(base_url)
    except Exception as exc:
        frontend_scan = {"error": f"{type(exc).__name__}: {exc}"}

    report = {
        "created_at": datetime.now().isoformat(),
        "base_url": base_url,
        "cookie_present": bool(cookie),
        "limits": {
            "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
            "initial_world_timeout_seconds": INITIAL_WORLD_TIMEOUT_SECONDS,
            "direct_capture_seconds": DIRECT_CAPTURE_SECONDS,
            "path_phase_seconds": PATH_PHASE_SECONDS,
            "start_stagger_seconds": [START_STAGGER_MIN_SECONDS, START_STAGGER_MAX_SECONDS],
            "max_workers": MAX_WORKERS,
            "max_region_messages_per_connection": 3,
        },
        "server_list": server_list,
        "direct_probes": direct_results,
        "path_probes": path_results,
        "frontend_scan": frontend_scan,
    }

    report_path = output_dir / "deep_protocol_report.json"
    summary_path = output_dir / "summary.txt"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(build_summary(report), encoding="utf-8")

    print("-" * 84)
    print(summary_path.read_text(encoding="utf-8"))
    print(f"Full report: {report_path}")
    print("Diagnostic completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Test cancelled.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"Fatal error: {type(exc).__name__}: {exc}")
        raise
