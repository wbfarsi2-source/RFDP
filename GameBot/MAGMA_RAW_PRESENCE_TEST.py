#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kintara Magma raw presence diagnostic.

READ-ONLY:
- HTTP GET only
- WebSocket receive only
- No POST
- No ws.send()
- No position, movement, mining, attack or inventory action
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import websocket


BASE = "https://kintara.gg"
WS_DEFAULT = "wss://kintara.gg"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

WORK_DIR = Path(__file__).resolve().parent
ENV_FILE = WORK_DIR / ".env"

CAPTURE_SECONDS = 90
MAX_FRAMES_PER_SERVER = 1000
MAX_PARALLEL_SERVERS = 24
MIN_SERVER_NUMBER = 9

BLOCKED_TEXT = (
    "/terms",
    "terms.html",
)

SEARCH_WORDS = (
    "magma",
    "molten",
    "molten_rock",
    "lava",
    "volcano",
    "volcanic",
    "inferno",
    "mine",
    "mining",
    "mob",
    "monster",
    "boss",
    "region",
    "zone",
    "map",
    "biome",
    "scene",
    "area",
    "room",
    "player",
    "players",
    "presence",
    "snapshot",
)

SECRET_KEYS = {
    "cookie",
    "authorization",
    "token",
    "connecttoken",
    "connect_token",
    "session",
    "jwt",
    "secret",
    "email",
}

STAMP = time.strftime("%Y%m%d_%H%M%S")

OUTPUT_DIR = WORK_DIR / f"MAGMA_RAW_TEST_{STAMP}"
FRAMES_DIR = OUTPUT_DIR / "frames"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

PRINT_LOCK = threading.Lock()
DATA_LOCK = threading.Lock()

FRAME_TYPES: Counter[str] = Counter()
SCHEMA_PATHS: Counter[str] = Counter()
KEYWORD_HITS: list[dict[str, Any]] = []
SERVER_RESULTS: dict[str, dict[str, Any]] = {}
ERRORS: list[dict[str, Any]] = []


def log(message: str) -> None:
    with PRINT_LOCK:
        print(message, flush=True)


def is_blocked(value: str) -> bool:
    low = str(value or "").lower()
    return any(word in low for word in BLOCKED_TEXT)


def unquote(value: str) -> str:
    value = str(value or "").strip()

    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in ("'", '"')
    ):
        return value[1:-1]

    return value


def load_cookie() -> str:
    if not ENV_FILE.exists():
        raise RuntimeError(f".env not found: {ENV_FILE}")

    for raw in ENV_FILE.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines():

        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key.strip() == "KINTARA_COOKIE":
            cookie = unquote(value)

            if "=" not in cookie:
                raise RuntimeError(
                    "KINTARA_COOKIE is incomplete. "
                    "Expected NAME=VALUE."
                )

            return cookie

    raise RuntimeError("KINTARA_COOKIE was not found in .env")


COOKIE = load_cookie()


def safe_http_url(path: str) -> str:
    if is_blocked(path):
        raise RuntimeError("Blocked URL")

    url = urllib.parse.urljoin(BASE + "/", str(path or ""))

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https" or parsed.hostname != "kintara.gg":
        raise RuntimeError(f"External HTTP host blocked: {url}")

    return url


def http_get(path: str, timeout: float = 20) -> tuple[int, Any, str]:
    url = safe_http_url(path)

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Origin": BASE,
            "Referer": BASE + "/play",
            "Cookie": COOKIE,
            "Cache-Control": "no-cache",
        },
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode(
                "utf-8",
                errors="replace",
            )

            try:
                payload = json.loads(raw or "{}")
            except Exception:
                payload = None

            return int(response.status), payload, raw

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = None

        return int(exc.code), payload, raw

    except Exception as exc:
        return 0, None, repr(exc)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}

        for key, child in value.items():
            if str(key).lower() in SECRET_KEYS:
                result[key] = "<redacted>"
            else:
                result[key] = redact(child)

        return result

    if isinstance(value, list):
        return [redact(item) for item in value]

    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            redact(value),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def as_positive_int(value: Any) -> int:
    try:
        number = int(float(value or 0))
        return number if number > 0 else 0
    except Exception:
        return 0


def route_shard(server: dict[str, Any]) -> int:
    for key in (
        "routeShardId",
        "localShardId",
        "id",
    ):
        number = as_positive_int(server.get(key))

        if number > 0:
            return number

    return 0


def display_id(server: dict[str, Any]) -> int:
    for key in (
        "displayId",
        "id",
    ):
        number = as_positive_int(server.get(key))

        if number > 0:
            return number

    return 0


def connection_zone(server: dict[str, Any]) -> str:
    return str(
        server.get("zone")
        or server.get("region")
        or ""
    ).strip().lower()


def server_is_free(server: dict[str, Any]) -> bool:
    name = str(server.get("name") or "")

    match = re.fullmatch(r"Server (\d+)", name)

    return bool(
        match
        and int(match.group(1)) >= MIN_SERVER_NUMBER
    )


def ws_base_is_cross_origin(ws_base: str) -> bool:
    ws_base = str(ws_base or "").strip()

    if not ws_base:
        return False

    try:
        http_url = re.sub(
            r"^wss:",
            "https:",
            ws_base,
            flags=re.I,
        )

        http_url = re.sub(
            r"^ws:",
            "http:",
            http_url,
            flags=re.I,
        )

        target = urllib.parse.urlparse(http_url)
        origin = urllib.parse.urlparse(BASE)

        target_port = target.port or (
            443 if target.scheme == "https" else 80
        )

        origin_port = origin.port or 443

        return (
            target.hostname,
            target_port,
        ) != (
            origin.hostname,
            origin_port,
        )

    except Exception:
        return True


def websocket_url(path: str, ws_base: str = "") -> str:
    if is_blocked(path) or is_blocked(ws_base):
        raise RuntimeError("Blocked WebSocket path")

    ws_base = str(ws_base or "").strip()

    if ws_base:
        if ws_base.startswith(("ws://", "wss://")):
            return ws_base.rstrip("/") + path

        return re.sub(
            r"^http",
            "ws",
            ws_base,
            flags=re.I,
        ).rstrip("/") + path

    return WS_DEFAULT + path


def append_token(url: str, token: str) -> str:
    token = str(token or "").strip()

    if not token:
        return url

    separator = "&" if "?" in url else "?"

    return (
        url
        + separator
        + "kt="
        + urllib.parse.quote(token, safe="")
    )


def fetch_presence_token(server: dict[str, Any]) -> str:
    ws_base = str(server.get("wsBaseUrl") or "")

    if not ws_base_is_cross_origin(ws_base):
        return ""

    shard = route_shard(server)

    params = {
        "shard": str(shard),
        "purpose": "presence",
    }

    zone = connection_zone(server)

    if zone:
        params["zone"] = zone

    path = (
        "/api/lobby/connect-token?"
        + urllib.parse.urlencode(params)
    )

    status, payload, raw = http_get(path, timeout=12)

    if status == 404:
        return ""

    if (
        status == 200
        and isinstance(payload, dict)
        and payload.get("ok") is not False
    ):
        return str(payload.get("token") or "").strip()

    error = (
        payload.get("error")
        if isinstance(payload, dict)
        else raw[:250]
    )

    raise RuntimeError(
        f"connect-token failed status={status} error={error}"
    )


def open_presence(server: dict[str, Any]):
    shard = route_shard(server)

    if shard <= 0:
        raise RuntimeError("Missing route shard")

    ws_base = str(server.get("wsBaseUrl") or "")
    token = fetch_presence_token(server)

    url = append_token(
        websocket_url(
            f"/ws/presence/s{shard}",
            ws_base,
        ),
        token,
    )

    ws = websocket.create_connection(
        url,
        timeout=20,
        cookie=COOKIE,
        origin=BASE,
        enable_multithread=True,
        header=[
            f"User-Agent: {USER_AGENT}",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
        ],
        http_no_proxy=["*"],
    )

    ws.settimeout(1.0)

    return ws


def safe_filename(value: str) -> str:
    clean = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        str(value or "server"),
    ).strip("_")

    return clean[:100] or "server"


def detect_frame_type(frame: Any) -> str:
    if isinstance(frame, dict):
        for key in (
            "t",
            "type",
            "event",
            "op",
            "action",
            "kind",
        ):
            if key in frame:
                return f"{key}={str(frame.get(key))[:120]}"

        return "dict_without_type"

    if isinstance(frame, list):
        return "list"

    return type(frame).__name__


def walk_schema(
    value: Any,
    path: str = "$",
    depth: int = 0,
) -> None:
    if depth > 20:
        return

    with DATA_LOCK:
        SCHEMA_PATHS[path] += 1

    if isinstance(value, dict):
        for key, child in value.items():
            walk_schema(
                child,
                path + "." + str(key),
                depth + 1,
            )

    elif isinstance(value, list):
        for child in value[:200]:
            walk_schema(
                child,
                path + "[]",
                depth + 1,
            )


def save_keyword_hit(
    server_name: str,
    frame_index: int,
    frame: Any,
) -> None:
    encoded = json.dumps(
        frame,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )

    low = encoded.lower()

    matched = sorted(
        {
            word
            for word in SEARCH_WORDS
            if word in low
        }
    )

    if not matched:
        return

    hit = {
        "server": server_name,
        "frame_index": frame_index,
        "keywords": matched,
        "frame": redact(frame),
    }

    with DATA_LOCK:
        KEYWORD_HITS.append(hit)


def probe_server(server: dict[str, Any]) -> dict[str, Any]:
    name = str(server.get("name") or "?")
    started = time.time()

    frames = 0
    received_bytes = 0
    status = "ok"
    error = ""

    local_types: Counter[str] = Counter()

    raw_path = FRAMES_DIR / (
        safe_filename(name) + ".jsonl"
    )

    ws = None

    try:
        ws = open_presence(server)

        log(
            f"[CONNECTED] {name} | "
            f"shard={route_shard(server)} | "
            f"zone={connection_zone(server) or '-'}"
        )

        with raw_path.open(
            "a",
            encoding="utf-8",
        ) as output_file:

            while (
                time.time() - started < CAPTURE_SECONDS
                and frames < MAX_FRAMES_PER_SERVER
            ):
                try:
                    raw = ws.recv()

                except websocket.WebSocketTimeoutException:
                    continue

                if raw in (None, ""):
                    status = "closed"
                    break

                if isinstance(raw, bytes):
                    received_bytes += len(raw)

                    frame: Any = {
                        "binary": True,
                        "length": len(raw),
                        "hex_prefix": raw[:200].hex(),
                    }

                else:
                    received_bytes += len(str(raw))

                    try:
                        frame = json.loads(raw)

                    except Exception:
                        frame = {
                            "raw": str(raw)[:50000]
                        }

                frames += 1

                frame_type = detect_frame_type(frame)

                local_types[frame_type] += 1

                with DATA_LOCK:
                    FRAME_TYPES[frame_type] += 1

                walk_schema(frame)

                save_keyword_hit(
                    name,
                    frames,
                    frame,
                )

                row = {
                    "time": time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "server": name,
                    "frame_index": frames,
                    "frame": redact(frame),
                }

                output_file.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    )
                    + "\n"
                )

                output_file.flush()

    except Exception as exc:
        status = "error"
        error = str(exc)

        log(f"[ERROR] {name} | {error}")

        with DATA_LOCK:
            ERRORS.append(
                {
                    "server": name,
                    "error": error,
                }
            )

    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass

    result = {
        "name": name,
        "display_id": display_id(server),
        "route_shard": route_shard(server),
        "zone": connection_zone(server),
        "queue_length": server.get("queueLength"),
        "ws_base_url": server.get("wsBaseUrl"),
        "status": status,
        "frames": frames,
        "bytes_received": received_bytes,
        "frame_types": dict(local_types),
        "error": error,
    }

    with DATA_LOCK:
        SERVER_RESULTS[name] = result

    log(
        f"[DONE] {name} | "
        f"frames={frames} | "
        f"bytes={received_bytes} | "
        f"status={status}"
    )

    return result


def main() -> None:
    print("=" * 72)
    print("KINTARA MAGMA RAW PRESENCE TEST")
    print("=" * 72)
    print("Directory :", WORK_DIR)
    print("Output    :", OUTPUT_DIR)
    print("HTTP      : GET only")
    print("WebSocket : RECEIVE only")
    print("ws.send   : NEVER")
    print("Gameplay  : NONE")
    print("=" * 72)

    status, me, raw = http_get(
        "/api/auth/me",
        timeout=20,
    )

    if status != 200:
        raise RuntimeError(
            f"/api/auth/me failed: HTTP {status} - {raw[:300]}"
        )

    if not isinstance(me, dict) or not me.get("player"):
        raise RuntimeError(
            "/api/auth/me returned no player data"
        )

    write_json(
        OUTPUT_DIR / "00_AUTH_ME_REDACTED.json",
        me,
    )

    print("[OK] Cookie and account verified")

    status, payload, raw = http_get(
        "/api/servers",
        timeout=20,
    )

    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(
            f"/api/servers failed: HTTP {status} - {raw[:300]}"
        )

    write_json(
        OUTPUT_DIR / "01_ALL_SERVERS.json",
        payload,
    )

    all_servers = [
        server
        for server in (payload.get("servers") or [])
        if isinstance(server, dict)
    ]

    servers = [
        server
        for server in all_servers
        if server_is_free(server)
    ]

    servers.sort(
        key=lambda server: display_id(server) or 999999
    )

    write_json(
        OUTPUT_DIR / "02_SELECTED_SERVERS.json",
        servers,
    )

    print(
        f"[OK] Servers loaded: "
        f"all={len(all_servers)} selected={len(servers)}"
    )

    for server in servers:
        print(
            f" - {str(server.get('name') or '?'):<16} "
            f"display={display_id(server):<3} "
            f"shard={route_shard(server):<3} "
            f"zone={connection_zone(server) or '-':<10} "
            f"queue={server.get('queueLength')}"
        )

    if not servers:
        raise RuntimeError("No free servers were returned")

    workers = min(
        MAX_PARALLEL_SERVERS,
        len(servers),
    )

    print()
    print(
        f"Opening {len(servers)} receive-only Presence connections..."
    )
    print(
        f"Capture duration: {CAPTURE_SECONDS} seconds"
    )
    print()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = []

        for server in servers:
            futures.append(
                executor.submit(
                    probe_server,
                    server,
                )
            )

            time.sleep(0.10)

        for future in concurrent.futures.as_completed(
            futures
        ):
            try:
                future.result()
            except Exception as exc:
                with DATA_LOCK:
                    ERRORS.append(
                        {
                            "server": "worker",
                            "error": repr(exc),
                        }
                    )

    write_json(
        OUTPUT_DIR / "03_SERVER_RESULTS.json",
        SERVER_RESULTS,
    )

    write_json(
        OUTPUT_DIR / "04_FRAME_TYPES.json",
        dict(FRAME_TYPES.most_common()),
    )

    write_json(
        OUTPUT_DIR / "05_SCHEMA_PATHS.json",
        dict(SCHEMA_PATHS.most_common()),
    )

    write_json(
        OUTPUT_DIR / "06_KEYWORD_HITS.json",
        KEYWORD_HITS,
    )

    write_json(
        OUTPUT_DIR / "07_ERRORS.json",
        ERRORS,
    )

    total_frames = sum(
        result.get("frames", 0)
        for result in SERVER_RESULTS.values()
    )

    hit_servers = Counter(
        hit.get("server")
        for hit in KEYWORD_HITS
    )

    summary_lines = [
        "KINTARA MAGMA RAW PRESENCE TEST",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Selected servers: {len(servers)}",
        f"Server results: {len(SERVER_RESULTS)}",
        f"Total frames: {total_frames}",
        f"Keyword hits: {len(KEYWORD_HITS)}",
        f"Errors: {len(ERRORS)}",
        "",
        "PER SERVER",
    ]

    for name in sorted(SERVER_RESULTS):
        result = SERVER_RESULTS[name]

        summary_lines.append(
            f"{name} | "
            f"status={result.get('status')} | "
            f"frames={result.get('frames')} | "
            f"bytes={result.get('bytes_received')} | "
            f"shard={result.get('route_shard')} | "
            f"zone={result.get('zone') or '-'} | "
            f"error={result.get('error') or '-'}"
        )

    summary_lines.extend(
        [
            "",
            "TOP FRAME TYPES",
        ]
    )

    for frame_type, count in FRAME_TYPES.most_common(30):
        summary_lines.append(
            f"{count:7d}  {frame_type}"
        )

    summary_lines.extend(
        [
            "",
            "KEYWORD HIT SERVERS",
        ]
    )

    if hit_servers:
        for name, count in hit_servers.most_common():
            summary_lines.append(
                f"{count:7d}  {name}"
            )
    else:
        summary_lines.append(
            "No magma/map/player keywords were found."
        )

    summary = "\n".join(summary_lines) + "\n"

    summary_path = OUTPUT_DIR / "08_SUMMARY.txt"

    summary_path.write_text(
        summary,
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(summary)
    print("=" * 72)
    print("RESULT DIRECTORY:")
    print(OUTPUT_DIR)
    print()
    print("IMPORTANT FILE:")
    print(summary_path)
    print()
    print("RAW FRAMES:")
    print(FRAMES_DIR)


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nStopped by user.")

    except Exception as exc:
        fatal_path = OUTPUT_DIR / "FATAL.txt"

        fatal_path.write_text(
            repr(exc) + "\n",
            encoding="utf-8",
        )

        print()
        print("FATAL:", exc)
        print("Saved:", fatal_path)
        raise
