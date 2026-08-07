from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:
    raise SystemExit("Missing dependency: httpx. Run this file with the project's .venv Python.") from exc

try:
    import websocket
except ImportError as exc:
    raise SystemExit("Missing dependency: websocket-client. Run this file with the project's .venv Python.") from exc


DEFAULT_BASE_URL = "https://kintara.gg"
DEFAULT_REGION = "ember"
DEFAULT_CAPTURE_SECONDS = 12.0
DEFAULT_REGISTER_SECONDS = 2.0
SENSITIVE_KEYS = ("cookie", "token", "password", "secret", "session", "authorization")
IDENTITY_KEYS = (
    "username",
    "displayName",
    "display_name",
    "characterName",
    "character_name",
    "accountId",
    "account_id",
    "userId",
    "user_id",
    "walletAddress",
    "wallet_address",
)
MARKER_KEYS = (
    "type",
    "kind",
    "entityType",
    "entity_type",
    "npcType",
    "npc_type",
    "mobType",
    "mob_type",
    "species",
    "category",
    "role",
)
NPC_FLAG_KEYS = (
    "isNpc",
    "isNPC",
    "npc",
    "isMob",
    "isBoss",
    "isPet",
    "isMonster",
    "isEnemy",
)
BLOCKED_MARKERS = (
    "npc",
    "mob",
    "boss",
    "enemy",
    "monster",
    "creature",
    "spider",
    "pet",
    "companion",
    "minion",
    "summon",
    "animal",
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
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
    candidates = [start, *start.parents]
    for candidate in candidates:
        if (candidate / ".env").exists() or (candidate / "START_GAMEBOT.bat").exists():
            return candidate
    return start


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


def websocket_url(server: dict[str, Any], base_url: str) -> str:
    shard = route_shard_id(server)
    if shard <= 0:
        raise ValueError("No valid route shard was found")
    ws_base = str(server.get("wsBaseUrl") or "").strip()
    if ws_base:
        if ws_base.startswith(("ws://", "wss://")):
            return ws_base.rstrip("/") + f"/ws/spectate/s{shard}"
        return re.sub(r"^http", "ws", ws_base, flags=re.I).rstrip("/") + f"/ws/spectate/s{shard}"
    return re.sub(r"^http", "ws", base_url, flags=re.I).rstrip("/") + f"/ws/spectate/s{shard}"


def decode_messages(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    try:
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if data and data[0] == 1:
                data = gzip.decompress(data[1:])
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        payload = json.loads(text)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if isinstance(payload, dict):
        return [payload], None
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], None
    return [], f"Unsupported JSON payload type: {type(payload).__name__}"


def positive_numeric_id(player: dict[str, Any]) -> bool:
    for key in ("id", "playerId", "player_id", "characterId", "character_id", "userId", "user_id"):
        try:
            if int(float(player.get(key))) > 0:
                return True
        except Exception:
            continue
    return False


def marker_text(player: dict[str, Any]) -> str:
    return " ".join(str(player.get(key) or "").strip().lower() for key in MARKER_KEYS)


def has_npc_signal(player: dict[str, Any]) -> bool:
    if any(bool(player.get(key)) for key in NPC_FLAG_KEYS):
        return True
    markers = marker_text(player)
    return any(word in markers for word in BLOCKED_MARKERS)


def old_human_heuristic(player: Any) -> bool:
    if not isinstance(player, dict):
        return False
    try:
        if int(float(player.get("id"))) <= 0:
            return False
    except Exception:
        return False
    return not has_npc_signal(player)


def identity_human_candidate(player: Any) -> bool:
    if not isinstance(player, dict) or has_npc_signal(player):
        return False
    if not positive_numeric_id(player):
        return False
    if any(player.get(key) not in (None, "", 0, False) for key in IDENTITY_KEYS):
        return True
    markers = marker_text(player)
    return any(word in markers for word in ("player", "human", "character", "account"))


def stable_redaction(value: Any) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"<redacted:{digest}>"


def sanitize_player(player: Any) -> dict[str, Any]:
    if not isinstance(player, dict):
        return {"value_type": type(player).__name__}
    selected: dict[str, Any] = {}
    for key, value in player.items():
        lower = key.lower()
        if any(token in lower for token in SENSITIVE_KEYS):
            selected[key] = "<redacted>"
        elif lower in {"id", "playerid", "player_id", "userid", "user_id", "accountid", "account_id"}:
            selected[key] = stable_redaction(value)
        elif lower in {"name", "username", "displayname", "display_name", "charactername", "character_name"}:
            selected[key] = "<redacted>" if value not in (None, "") else value
        elif key in MARKER_KEYS or key in NPC_FLAG_KEYS:
            selected[key] = value
        elif isinstance(value, (bool, int, float)) or value is None:
            selected[key] = value
        elif isinstance(value, str):
            selected[key] = f"<string:{len(value)}>"
        elif isinstance(value, list):
            selected[key] = f"<list:{len(value)}>"
        elif isinstance(value, dict):
            selected[key] = f"<dict:{len(value)}>"
        else:
            selected[key] = f"<{type(value).__name__}>"
    return {
        "keys": sorted(player.keys()),
        "selected": selected,
        "old_human_heuristic": old_human_heuristic(player),
        "identity_human_candidate": identity_human_candidate(player),
    }


def sanitize_message(message: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in message.items():
        lower = key.lower()
        if any(token in lower for token in SENSITIVE_KEYS):
            result[key] = "<redacted>"
        elif key == "players" and isinstance(value, list):
            result[key] = [sanitize_player(player) for player in value[:12]]
            result["players_truncated"] = max(0, len(value) - 12)
        elif isinstance(value, dict):
            result[key] = {k: ("<redacted>" if any(token in k.lower() for token in SENSITIVE_KEYS) else v) for k, v in value.items()}
        else:
            result[key] = value
    return result


@dataclass
class ServerProbeResult:
    server: str
    number: int
    shard: int
    websocket_url: str
    connection_mode: str = ""
    connected: bool = False
    first_snapshot_ms: int | None = None
    snapshots: int = 0
    registration_messages: int = 0
    message_types: dict[str, int] = field(default_factory=dict)
    regions: list[str] = field(default_factory=list)
    latest_raw_player_count: int | None = None
    latest_old_heuristic_count: int | None = None
    latest_identity_candidate_count: int | None = None
    latest_snapshot_age_ms: int | None = None
    player_key_sets: list[list[str]] = field(default_factory=list)
    protocol_samples: list[dict[str, Any]] = field(default_factory=list)
    decode_errors: list[str] = field(default_factory=list)
    error: str = ""


def connect_websocket(url: str, user_agent: str, origin: str) -> tuple[Any, str]:
    base_kwargs = {
        "timeout": 12,
        "origin": origin,
        "enable_multithread": True,
        "header": [
            f"User-Agent: {user_agent}",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
        ],
    }
    try:
        return websocket.create_connection(url, **base_kwargs), "environment"
    except Exception as first_exc:
        try:
            return websocket.create_connection(url, http_no_proxy=["*"], **base_kwargs), "direct-fallback"
        except Exception as second_exc:
            raise RuntimeError(f"environment={first_exc}; direct={second_exc}") from second_exc


def probe_server(
    server: dict[str, Any],
    *,
    base_url: str,
    region: str,
    user_agent: str,
    capture_seconds: float,
    register_seconds: float,
) -> ServerProbeResult:
    name = str(server.get("name") or "?")
    number = server_number(server)
    shard = route_shard_id(server)
    try:
        url = websocket_url(server, base_url)
    except Exception as exc:
        return ServerProbeResult(name, number, shard, "", error=str(exc))

    result = ServerProbeResult(name, number, shard, url)
    ws = None
    started = time.monotonic()
    last_registration = -999.0
    latest_snapshot_at: float | None = None
    type_counter: Counter[str] = Counter()
    region_values: set[str] = set()
    player_key_sets: set[tuple[str, ...]] = set()

    try:
        ws, mode = connect_websocket(url, user_agent, base_url)
        result.connection_mode = mode
        result.connected = True
        ws.settimeout(0.5)

        while time.monotonic() - started < capture_seconds:
            elapsed = time.monotonic() - started
            if elapsed - last_registration >= register_seconds:
                ws.send(json.dumps({"t": "spec_reg", "region": region}, separators=(",", ":")))
                result.registration_messages += 1
                last_registration = elapsed

            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue

            if raw in (None, ""):
                raise RuntimeError("Socket closed before the capture window completed")

            messages, decode_error = decode_messages(raw)
            if decode_error:
                if len(result.decode_errors) < 8:
                    result.decode_errors.append(decode_error)
                continue

            for message in messages:
                message_type = str(message.get("t") or "<missing>")
                type_counter[message_type] += 1
                if len(result.protocol_samples) < 4:
                    result.protocol_samples.append(sanitize_message(message))

                if message_type != "snap":
                    continue

                result.snapshots += 1
                latest_snapshot_at = time.monotonic()
                if result.first_snapshot_ms is None:
                    result.first_snapshot_ms = int((latest_snapshot_at - started) * 1000)

                region_value = str(message.get("region") or "")
                region_values.add(region_value)
                players = message.get("players")
                if not isinstance(players, list):
                    result.latest_raw_player_count = None
                    result.latest_old_heuristic_count = None
                    result.latest_identity_candidate_count = None
                    continue

                result.latest_raw_player_count = len(players)
                result.latest_old_heuristic_count = sum(1 for player in players if old_human_heuristic(player))
                result.latest_identity_candidate_count = sum(1 for player in players if identity_human_candidate(player))
                for player in players:
                    if isinstance(player, dict):
                        player_key_sets.add(tuple(sorted(player.keys())))

        if latest_snapshot_at is not None:
            result.latest_snapshot_age_ms = int((time.monotonic() - latest_snapshot_at) * 1000)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    result.message_types = dict(type_counter)
    result.regions = sorted(region_values)
    result.player_key_sets = [list(keys) for keys in sorted(player_key_sets)[:12]]
    return result


def fetch_servers(base_url: str, cookie: str, user_agent: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = base_url.rstrip("/") + "/api/servers"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json,text/plain,*/*",
        "Origin": base_url.rstrip("/"),
        "Referer": base_url.rstrip("/") + "/play",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie

    errors: list[str] = []
    for trust_env, mode in ((True, "environment"), (False, "direct-fallback")):
        try:
            with httpx.Client(timeout=httpx.Timeout(25.0, connect=15.0), trust_env=trust_env, follow_redirects=True) as client:
                response = client.get(url, headers=headers, params={"_": str(int(time.time() * 1000))})
            raw_text = response.text
            try:
                payload = response.json()
            except Exception:
                payload = None
            metadata = {
                "url": str(response.url),
                "status_code": response.status_code,
                "connection_mode": mode,
                "content_type": response.headers.get("content-type", ""),
                "response_length": len(response.content),
                "payload": payload,
                "raw_text": raw_text[:100000],
            }
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {raw_text[:300]}")
            if not isinstance(payload, dict):
                raise RuntimeError("The server-list response is not a JSON object")
            rows = [dict(row) for row in (payload.get("servers") or []) if isinstance(row, dict) and server_number(row) >= 1]
            rows.sort(key=server_number)
            if not rows:
                raise RuntimeError("No numbered servers were found in /api/servers")
            return rows, metadata
        except Exception as exc:
            errors.append(f"{mode}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def build_summary(results: list[ServerProbeResult], http_meta: dict[str, Any], elapsed: float) -> str:
    connected = [row for row in results if row.connected]
    snapshots = [row for row in results if row.snapshots > 0]
    lines = [
        "KINTARA COME TO MOLTEN DIAGNOSTIC",
        "=" * 86,
        f"HTTP status: {http_meta.get('status_code')}",
        f"HTTP route: {http_meta.get('connection_mode')}",
        f"Numbered servers: {len(results)}",
        f"WebSocket connected: {len(connected)}",
        f"Servers with snapshots: {len(snapshots)}",
        f"Total test time: {elapsed:.1f}s",
        "",
        f"{'SERVER':<12} {'SHARD':>7} {'SNAPS':>6} {'FIRST':>8} {'RAW':>5} {'OLD':>5} {'IDENT':>6} STATUS",
        "-" * 86,
    ]
    for row in sorted(results, key=lambda item: item.number):
        first = "-" if row.first_snapshot_ms is None else f"{row.first_snapshot_ms}ms"
        raw = "-" if row.latest_raw_player_count is None else str(row.latest_raw_player_count)
        old = "-" if row.latest_old_heuristic_count is None else str(row.latest_old_heuristic_count)
        ident = "-" if row.latest_identity_candidate_count is None else str(row.latest_identity_candidate_count)
        status = "OK" if row.snapshots else (row.error[:70] if row.error else "NO SNAPSHOT")
        lines.append(
            f"{row.server:<12} {row.shard:>7} {row.snapshots:>6} {first:>8} {raw:>5} {old:>5} {ident:>6} {status}"
        )

    verified = [row for row in results if row.snapshots > 0 and row.latest_old_heuristic_count is not None]
    leaders = sorted(verified, key=lambda row: (-(row.latest_old_heuristic_count or 0), row.number))[:3]
    lines.extend(["", "TOP 3 USING CURRENT BOT HEURISTIC", "-" * 86])
    positive = [row for row in leaders if (row.latest_old_heuristic_count or 0) > 0]
    if not positive:
        lines.append("No human player is currently detected in The Emberstone.")
    else:
        for index, row in enumerate(positive, start=1):
            lines.append(f"{index}. {row.server} - {row.latest_old_heuristic_count} player(s)")

    mismatches = [
        row for row in verified
        if row.latest_old_heuristic_count != row.latest_identity_candidate_count
    ]
    lines.extend(["", "CLASSIFICATION DIFFERENCES", "-" * 86])
    if not mismatches:
        lines.append("No difference was detected between the current and identity-based diagnostic heuristics.")
    else:
        for row in mismatches:
            lines.append(
                f"{row.server}: current={row.latest_old_heuristic_count}, identity-candidate={row.latest_identity_candidate_count}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Kintara Come To Molten server-list and spectator protocol.")
    parser.add_argument("--capture-seconds", type=float, default=DEFAULT_CAPTURE_SECONDS)
    parser.add_argument("--register-seconds", type=float, default=DEFAULT_REGISTER_SECONDS)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = find_project_root(Path.cwd().resolve())
    if not (project_root / ".env").exists() and (script_dir / ".env").exists():
        project_root = script_dir
    load_env_file(project_root / ".env")

    base_url = str(os.environ.get("KINTARA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    cookie = str(os.environ.get("KINTARA_EMBER_COOKIE") or os.environ.get("KINTARA_COOKIE") or "").strip()
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output).resolve() if args.output else project_root / "diagnostics" / f"come_to_molten_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 86)
    print("KINTARA COME TO MOLTEN SERVER DIAGNOSTIC")
    print("=" * 86)
    print(f"Project root: {project_root}")
    print(f"Base URL: {base_url}")
    print(f"Cookie for /api/servers: {'loaded' if cookie else 'not found'}")
    print("WebSocket spectator connections: anonymous")
    print(f"Capture: {args.capture_seconds:.1f}s | spec_reg interval: {args.register_seconds:.1f}s")
    print(f"Output: {output_dir}")
    print("This test only calls /api/servers and /ws/spectate. It does not open any other page.")
    print("-" * 86)

    started = time.monotonic()
    try:
        servers, http_meta = fetch_servers(base_url, cookie, user_agent)
    except Exception as exc:
        error_text = f"Server-list test failed: {type(exc).__name__}: {exc}\n"
        (output_dir / "fatal_error.txt").write_text(error_text, encoding="utf-8")
        print(error_text)
        print(f"Send this folder for review: {output_dir}")
        return 2

    raw_payload = http_meta.pop("payload", None)
    raw_text = http_meta.pop("raw_text", "")
    write_json(output_dir / "servers_response.json", raw_payload)
    (output_dir / "servers_response_raw.txt").write_text(raw_text, encoding="utf-8", errors="replace")
    write_json(
        output_dir / "server_fields.json",
        [
            {
                "server": str(row.get("name") or "?"),
                "number": server_number(row),
                "keys": sorted(row.keys()),
                "routeShardId": row.get("routeShardId"),
                "localShardId": row.get("localShardId"),
                "id": row.get("id"),
                "wsBaseUrl": row.get("wsBaseUrl"),
                "region": row.get("region"),
                "zone": row.get("zone"),
                "full": row.get("full"),
                "requiresMembership": row.get("requiresMembership"),
            }
            for row in servers
        ],
    )

    print(f"Found {len(servers)} numbered servers. Starting controlled spectator checks...")
    results: list[ServerProbeResult] = []
    result_lock = threading.Lock()

    def worker(server: dict[str, Any]) -> None:
        result = probe_server(
            server,
            base_url=base_url,
            region=str(args.region),
            user_agent=user_agent,
            capture_seconds=max(4.0, float(args.capture_seconds)),
            register_seconds=max(1.0, float(args.register_seconds)),
        )
        with result_lock:
            results.append(result)
        status = f"{result.snapshots} snap(s)" if result.snapshots else (result.error or "no snapshot")
        print(f"[{result.server}] {status}")

    threads: list[threading.Thread] = []
    for server in servers:
        thread = threading.Thread(target=worker, args=(server,), daemon=True, name=f"probe-{server_number(server)}")
        thread.start()
        threads.append(thread)
        time.sleep(0.06)

    for thread in threads:
        thread.join(timeout=max(20.0, float(args.capture_seconds) + 20.0))

    existing_numbers = {row.number for row in results}
    for server in servers:
        number = server_number(server)
        if number not in existing_numbers:
            results.append(
                ServerProbeResult(
                    server=str(server.get("name") or "?"),
                    number=number,
                    shard=route_shard_id(server),
                    websocket_url=websocket_url(server, base_url),
                    error="Probe thread did not complete before the safety timeout",
                )
            )

    results.sort(key=lambda row: row.number)
    elapsed = time.monotonic() - started
    report = {
        "created_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "base_url": base_url,
        "cookie_present": bool(cookie),
        "region_requested": str(args.region),
        "capture_seconds": float(args.capture_seconds),
        "register_seconds": float(args.register_seconds),
        "http": http_meta,
        "server_count": len(servers),
        "elapsed_seconds": elapsed,
        "results": [asdict(row) for row in results],
    }
    write_json(output_dir / "report.json", report)
    summary = build_summary(results, http_meta, elapsed)
    (output_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print("Diagnostic completed.")
    print(f"Send these two files for review:\n  {output_dir / 'summary.txt'}\n  {output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
