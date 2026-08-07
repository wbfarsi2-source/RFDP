#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sequential authenticated Ember population scan.

This module is intentionally limited to:
- GET /api/auth/me
- GET /api/servers
- GET /api/lobby/connect-token
- Queue WebSocket keepalive (q_ping) when required
- One exact, non-moving Presence position frame per server
- Receiving Presence frames and counting account-shaped players

No fishing, combat, inventory, marketplace, mining, or other gameplay action is sent.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

try:
    import websocket
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("websocket-client is required") from exc

BASE_URL = "https://kintara.gg"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

# Locked F12 payload. Do not replace with guessed coordinates.
EMBER_POSITION = {
    "t": "pos",
    "region": "ember",
    "x": -4.5,
    "y": 0.215,
    "z": 18.5,
    "ry": 1.5707963267948966,
    "mov": False,
    "le": 2,
    "outfit": None,
}

SERVER_START_GAP_SECONDS = 5.0
PRESENCE_CAPTURE_SECONDS = 3.6
QUEUE_MAX_WAIT_SECONDS = 12.0
QUEUE_ZERO_STABLE_SECONDS = 2.5


@dataclass
class ServerResult:
    server: str
    number: int
    count: int | None
    ok: bool
    snapshot_seen: bool
    own_account_removed: bool
    started_at: float
    finished_at: float
    error: str = ""


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "app.py").exists() and (parent / "games" / "kintara").exists():
            return parent
    return Path.cwd().resolve()


def _read_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = root / ".env"
    if not env_file.exists():
        return values
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _cookie(root: Path) -> str:
    values = _read_env(root)
    value = (
        os.environ.get("KINTARA_EMBER_COOKIE", "").strip()
        or values.get("KINTARA_EMBER_COOKIE", "").strip()
        or os.environ.get("KINTARA_COOKIE", "").strip()
        or values.get("KINTARA_COOKIE", "").strip()
    )
    if not value or "=" not in value:
        raise RuntimeError("KINTARA_EMBER_COOKIE/KINTARA_COOKIE is missing or incomplete in .env")
    return value


def _proxy_openers(root: Path) -> list[urllib.request.OpenerDirector]:
    values = _read_env(root)
    configured = (
        os.environ.get("GAMEBOT_PROXY_URL", "").strip()
        or values.get("GAMEBOT_PROXY_URL", "").strip()
        or "auto"
    )
    openers: list[urllib.request.OpenerDirector] = []
    if configured.lower() not in {"", "auto", "direct", "none", "off"}:
        openers.append(urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": configured, "https": configured})
        ))
    elif configured.lower() == "auto":
        proxies = urllib.request.getproxies()
        if proxies:
            openers.append(urllib.request.build_opener(urllib.request.ProxyHandler(proxies)))
    openers.append(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    return openers


def _http_get(root: Path, path: str, cookie: str, timeout: float = 12.0) -> tuple[int, Any, str]:
    if "terms" in path.lower():
        raise RuntimeError("Blocked path")
    req = urllib.request.Request(
        urllib.parse.urljoin(BASE_URL + "/", path.lstrip("/")),
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/play",
            "Cookie": cookie,
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        },
    )
    last_error: Exception | None = None
    for opener in _proxy_openers(root):
        try:
            with opener.open(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw or "{}")
                except Exception:
                    payload = {}
                return int(response.status), payload, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {}
            return int(exc.code), payload, raw
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"network request failed: {last_error}")


def _positive_int(value: Any) -> int:
    try:
        number = int(float(value or 0))
        return number if number > 0 else 0
    except Exception:
        return 0


def _server_number(server: dict[str, Any]) -> int:
    match = re.fullmatch(r"Server\s+(\d+)", str(server.get("name") or ""))
    return int(match.group(1)) if match else -1


def _route_shard(server: dict[str, Any]) -> int:
    return (
        _positive_int(server.get("routeShardId"))
        or _positive_int(server.get("localShardId"))
        or _positive_int(server.get("id"))
    )


def _zone(server: dict[str, Any]) -> str:
    return str(server.get("zone") or server.get("region") or "").strip().lower()


def _ws_base(server: dict[str, Any]) -> str:
    return str(server.get("wsBaseUrl") or "").strip().rstrip("/")


def _ws_url(server: dict[str, Any], purpose: str) -> str:
    base = _ws_base(server) or "wss://kintara.gg"
    if base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    return f"{base}/ws/{purpose}/s{_route_shard(server)}"


def _append_token(url: str, token: str) -> str:
    token = str(token or "").strip()
    if not token:
        return url
    return url + ("&" if "?" in url else "?") + "kt=" + urllib.parse.quote(token, safe="")


def _extract_token(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("connectToken", "token", "kt"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("data", "result"):
            nested = _extract_token(payload.get(key))
            if nested:
                return nested
    return ""


def _connect_token(root: Path, server: dict[str, Any], purpose: str, cookie: str) -> str:
    params = {
        "shard": str(_route_shard(server)),
        "purpose": str(purpose),
    }
    zone = _zone(server)
    if zone:
        params["zone"] = zone
    status, payload, raw = _http_get(
        root,
        "/api/lobby/connect-token?" + urllib.parse.urlencode(params),
        cookie,
        timeout=8.0,
    )
    if status == 404:
        return ""
    if status != 200:
        raise RuntimeError(f"connect-token {purpose} failed: HTTP {status} {raw[:120]}")
    token = _extract_token(payload)
    if not token and _ws_base(server) and "kintara.gg" not in _ws_base(server):
        raise RuntimeError(f"connect-token {purpose} response had no token")
    return token


def _ws_proxy_attempts(root: Path) -> list[dict[str, Any]]:
    values = _read_env(root)
    configured = (
        os.environ.get("GAMEBOT_PROXY_URL", "").strip()
        or values.get("GAMEBOT_PROXY_URL", "").strip()
        or "auto"
    )
    attempts: list[dict[str, Any]] = []
    candidates: list[str] = []
    if configured.lower() not in {"", "auto", "direct", "none", "off"}:
        candidates.append(configured)
    elif configured.lower() == "auto":
        proxies = urllib.request.getproxies()
        value = str(proxies.get("https") or proxies.get("http") or "").strip()
        if value:
            candidates.append(value)
    for value in candidates:
        parsed = urllib.parse.urlparse(value)
        if parsed.hostname and parsed.port:
            row: dict[str, Any] = {
                "http_proxy_host": parsed.hostname,
                "http_proxy_port": int(parsed.port),
                "proxy_type": "socks5" if parsed.scheme.lower().startswith("socks") else "http",
            }
            if parsed.username:
                row["http_proxy_auth"] = (
                    urllib.parse.unquote(parsed.username),
                    urllib.parse.unquote(parsed.password or ""),
                )
            attempts.append(row)
    attempts.append({"http_no_proxy": ["*"]})
    return attempts


def _open_ws(root: Path, url: str, cookie: str, timeout: float = 10.0):
    last_error: Exception | None = None
    for options in _ws_proxy_attempts(root):
        try:
            return websocket.create_connection(
                url,
                timeout=max(5.0, float(timeout)),
                cookie=cookie,
                origin=BASE_URL,
                enable_multithread=True,
                header=[
                    f"User-Agent: {USER_AGENT}",
                    "Pragma: no-cache",
                    "Cache-Control: no-cache",
                ],
                **options,
            )
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"WebSocket connection failed: {last_error}")


def _queue_presence_token(root: Path, server: dict[str, Any], cookie: str) -> str:
    queue_token = _connect_token(root, server, "queue", cookie)
    queue_url = _append_token(_ws_url(server, "queue"), queue_token)
    ws = _open_ws(root, queue_url, cookie, timeout=10.0)
    ws.settimeout(1.0)
    started = time.monotonic()
    last_ping = 0.0
    zero_since: float | None = None
    try:
        while time.monotonic() - started < QUEUE_MAX_WAIT_SECONDS:
            now = time.monotonic()
            if now - last_ping >= 5.0:
                last_ping = now
                try:
                    ws.send(json.dumps({"t": "q_ping"}, separators=(",", ":")))
                except Exception:
                    pass
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                if zero_since is not None and now - zero_since >= QUEUE_ZERO_STABLE_SECONDS:
                    break
                continue
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if not isinstance(message, dict):
                continue
            msg_type = str(message.get("t") or "")
            if msg_type == "queue_ready":
                return str(message.get("connectToken") or "").strip()
            if msg_type == "queue_pos":
                ahead = _positive_int(message.get("ahead"))
                try:
                    pos = int(float(message.get("pos") or 0))
                except Exception:
                    pos = 999
                if ahead == 0 and pos <= 1:
                    zero_since = zero_since or now
                    if now - zero_since >= QUEUE_ZERO_STABLE_SECONDS:
                        break
                else:
                    zero_since = None
            if msg_type in {"queue_error", "queue_evicted"}:
                raise RuntimeError(f"queue failed: {message}")
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return _connect_token(root, server, "presence", cookie)


def _decode_frames(raw: Any) -> list[dict[str, Any]]:
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


def _find_own_id(auth_payload: Any) -> int:
    preferred: list[Any] = []
    if isinstance(auth_payload, dict):
        player = auth_payload.get("player")
        if isinstance(player, dict):
            preferred.extend(player.get(key) for key in ("id", "playerId", "player_id", "userId"))
        preferred.extend(auth_payload.get(key) for key in ("playerId", "player_id", "id"))
    for value in preferred:
        number = _positive_int(value)
        if number:
            return number
    return 0


def _human_ids(players: Any) -> set[int]:
    rows = players if isinstance(players, list) else list(players.values()) if isinstance(players, dict) else []
    ids: set[int] = set()
    for player in rows:
        if not isinstance(player, dict):
            continue
        pid = _positive_int(player.get("id") or player.get("playerId") or player.get("player_id"))
        if not pid:
            continue
        if any(bool(player.get(key)) for key in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")):
            continue
        marker = " ".join(str(player.get(key) or "").lower() for key in (
            "type", "kind", "entityType", "entity_type", "npcType", "mobType", "species"
        ))
        if any(word in marker for word in ("npc", "mob", "boss", "enemy", "monster", "pet", "animal")):
            continue
        ids.add(pid)
    return ids


def _candidate_player_sets(
    node: Any,
    inherited_region: str = "",
) -> list[tuple[str, set[int]]]:
    found: list[tuple[str, set[int]]] = []
    if isinstance(node, dict):
        region = str(
            node.get("region")
            or node.get("pr")
            or node.get("presenceRegion")
            or inherited_region
            or ""
        ).strip().lower()
        for key in ("players", "onlinePlayers", "roster", "entities"):
            if key in node and isinstance(node[key], (list, dict)):
                ids = _human_ids(node[key])
                found.append((region, ids))
        for value in node.values():
            if isinstance(value, (dict, list)):
                found.extend(_candidate_player_sets(value, region))
    elif isinstance(node, list):
        for value in node:
            found.extend(_candidate_player_sets(value, inherited_region))
    return found


def _scan_one(root: Path, server: dict[str, Any], cookie: str, own_id: int) -> ServerResult:
    started_epoch = time.time()
    name = str(server.get("name") or "?")
    number = _server_number(server)
    ws = None
    try:
        token = _queue_presence_token(root, server, cookie)
        presence_url = _append_token(_ws_url(server, "presence"), token)
        ws = _open_ws(root, presence_url, cookie, timeout=10.0)
        ws.settimeout(0.65)

        # Exact F12 location; one stationary frame only.
        ws.send(json.dumps(EMBER_POSITION, separators=(",", ":"), ensure_ascii=False))

        deadline = time.monotonic() + PRESENCE_CAPTURE_SECONDS
        best_ids: set[int] | None = None
        snapshot_seen = False
        own_removed = False
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for frame in _decode_frames(raw):
                for region, ids in _candidate_player_sets(frame):
                    # Prefer an explicit Ember collection. If the protocol omits
                    # region, accept only a collection that contains our own ID,
                    # proving that it is the roster reached after the F12 frame.
                    explicit_ember = region == "ember"
                    contains_self = bool(own_id and own_id in ids)
                    if not explicit_ember and not contains_self:
                        continue
                    snapshot_seen = True
                    if own_id and own_id in ids:
                        ids = set(ids)
                        ids.discard(own_id)
                        own_removed = True
                    if best_ids is None or len(ids) > len(best_ids):
                        best_ids = set(ids)
        if best_ids is None:
            raise RuntimeError("No verified Ember player snapshot was received")
        return ServerResult(
            server=name,
            number=number,
            count=len(best_ids),
            ok=True,
            snapshot_seen=snapshot_seen,
            own_account_removed=own_removed,
            started_at=started_epoch,
            finished_at=time.time(),
        )
    except Exception as exc:
        return ServerResult(
            server=name,
            number=number,
            count=None,
            ok=False,
            snapshot_seen=False,
            own_account_removed=False,
            started_at=started_epoch,
            finished_at=time.time(),
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _write_compat_snapshots(root: Path, report: dict[str, Any]) -> None:
    paths = [
        root / "data" / "shared_services" / "ember" / "snapshot.json",
        root / "games" / "kintara" / "runtime" / "shared" / "ember" / "snapshot.json",
    ]
    for path in paths:
        try:
            _write_json(path, report)
        except Exception:
            pass


def scan_all_servers(progress: Callable[[int, int, ServerResult], None] | None = None) -> dict[str, Any]:
    root = _project_root()
    cookie = _cookie(root)
    auth_status, auth_payload, auth_raw = _http_get(root, "/api/auth/me", cookie, timeout=12.0)
    if auth_status != 200 or not isinstance(auth_payload, dict):
        raise RuntimeError(f"Kintara authentication failed: HTTP {auth_status} {auth_raw[:160]}")
    own_id = _find_own_id(auth_payload)

    server_status, server_payload, server_raw = _http_get(root, "/api/servers", cookie, timeout=15.0)
    if server_status != 200 or not isinstance(server_payload, dict):
        raise RuntimeError(f"Server list failed: HTTP {server_status} {server_raw[:160]}")
    servers = [
        dict(row) for row in (server_payload.get("servers") or [])
        if isinstance(row, dict) and _server_number(row) > 0
    ]
    servers.sort(key=_server_number)
    if len(servers) != 25:
        raise RuntimeError(f"Expected exactly 25 normal servers, received {len(servers)}")

    results: list[ServerResult] = []
    next_start = time.monotonic()
    for index, server in enumerate(servers, start=1):
        wait_seconds = next_start - time.monotonic()
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        actual_start = time.monotonic()
        result = _scan_one(root, server, cookie, own_id)
        results.append(result)
        if progress is not None:
            progress(index, len(servers), result)
        # Start-to-start interval is never less than five seconds.
        next_start = actual_start + SERVER_START_GAP_SECONDS

    successful = [row for row in results if row.ok and row.count is not None]
    top3 = sorted(successful, key=lambda row: (-int(row.count or 0), row.number))[:3]
    completed_at = time.time()
    report = {
        "mode": "manual_sequential_presence",
        "created_at": completed_at,
        "servers_expected": 25,
        "servers_checked": len(results),
        "servers_successful": len(successful),
        "servers_failed": len(results) - len(successful),
        "minimum_server_start_gap_seconds": SERVER_START_GAP_SECONDS,
        "position": dict(EMBER_POSITION),
        "scan_account_excluded_from_counts": bool(own_id),
        "top3": [
            {"server": row.server, "number": row.number, "count": int(row.count or 0)}
            for row in top3
        ],
        "results": [asdict(row) for row in results],
    }
    _write_json(root / "data" / "ember_manual_last_result.json", report)
    _write_compat_snapshots(root, report)
    return report
