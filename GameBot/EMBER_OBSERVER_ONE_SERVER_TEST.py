#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kintara Ember observer — controlled one-server test.

Outbound operations:
- HTTP GET only
- Exactly ONE WebSocket message:
    t=pos, region=ember

Never sends:
- movement
- mining
- chopping
- attack
- fishing
- inventory
- action
- equipment
- repeated position updates
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import websocket


BASE = "https://kintara.gg"
DEFAULT_WS_BASE = "wss://kintara.gg"

WORK_DIR = Path(__file__).resolve().parent
ENV_FILE = WORK_DIR / ".env"

TEST_SERVER_NUMBER = int(
    os.environ.get("OBSERVER_TEST_SERVER", "9")
)

CAPTURE_SECONDS = 20

# Emberstone is 40x40 with an offset of -19.5.
# Safe-camp tile selected:
# col=10, row=37 -> x=-9.5, z=17.5
OBSERVER_X = -9.5
OBSERVER_Y = 0.25
OBSERVER_Z = 17.5
OBSERVER_RY = 0.0

STAMP = time.strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = WORK_DIR / f"EMBER_OBSERVER_TEST_{STAMP}"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FRAMES_FILE = OUTPUT_DIR / "frames.jsonl"
SUMMARY_JSON = OUTPUT_DIR / "summary.json"
SUMMARY_TXT = OUTPUT_DIR / "summary.txt"

BLOCKED_PARTS = (
    "/terms",
    "terms.html",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}

    if not ENV_FILE.exists():
        raise RuntimeError(f".env not found: {ENV_FILE}")

    for raw_line in ENV_FILE.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines():

        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        values[key] = value

    return values


ENV = load_env()

OBSERVER_COOKIE = ENV.get(
    "KINTARA_OBSERVER_COOKIE",
    "",
).strip()

MAIN_COOKIE = ENV.get(
    "KINTARA_COOKIE",
    "",
).strip()

ALLOW_MAIN_ACCOUNT = (
    ENV.get(
        "ALLOW_MAIN_ACCOUNT_OBSERVER",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

if not OBSERVER_COOKIE:
    raise RuntimeError(
        "KINTARA_OBSERVER_COOKIE is missing from .env. "
        "Use a separate observer account."
    )

if "=" not in OBSERVER_COOKIE:
    raise RuntimeError(
        "KINTARA_OBSERVER_COOKIE must contain NAME=VALUE."
    )

if (
    MAIN_COOKIE
    and OBSERVER_COOKIE == MAIN_COOKIE
    and not ALLOW_MAIN_ACCOUNT
):
    raise RuntimeError(
        "Observer cookie is identical to the main account cookie. "
        "The script refuses to place the main account in Emberstone. "
        "Use a separate observer account."
    )


def blocked(value: str) -> bool:
    low = str(value or "").lower()

    return any(
        marker in low
        for marker in BLOCKED_PARTS
    )


def safe_http_url(path: str) -> str:
    if blocked(path):
        raise RuntimeError("Blocked path")

    url = urllib.parse.urljoin(
        BASE + "/",
        str(path or ""),
    )

    parsed = urllib.parse.urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != "kintara.gg"
        or blocked(parsed.path)
    ):
        raise RuntimeError(f"Blocked URL: {url}")

    return url


def http_get(
    path: str,
    timeout: float = 20,
) -> tuple[int, Any, str]:

    url = safe_http_url(path)

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Origin": BASE,
            "Referer": BASE + "/play",
            "Cookie": OBSERVER_COOKIE,
            "Cache-Control": "no-cache",
        },
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    try:
        with opener.open(
            request,
            timeout=timeout,
        ) as response:

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


def positive_int(value: Any) -> int:
    try:
        number = int(float(value or 0))
        return number if number > 0 else 0
    except Exception:
        return 0


def display_id(server: dict[str, Any]) -> int:
    return (
        positive_int(server.get("displayId"))
        or positive_int(server.get("id"))
    )


def route_shard(server: dict[str, Any]) -> int:
    return (
        positive_int(server.get("routeShardId"))
        or positive_int(server.get("localShardId"))
        or positive_int(server.get("id"))
    )


def zone(server: dict[str, Any]) -> str:
    return str(
        server.get("zone")
        or server.get("region")
        or ""
    ).strip().lower()


def websocket_base_is_cross_origin(
    ws_base: str,
) -> bool:

    ws_base = str(ws_base or "").strip()

    if not ws_base:
        return False

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


def fetch_connect_token(
    server: dict[str, Any],
) -> str:

    ws_base = str(
        server.get("wsBaseUrl")
        or ""
    ).strip()

    if not websocket_base_is_cross_origin(ws_base):
        return ""

    params = {
        "shard": str(route_shard(server)),
        "purpose": "presence",
    }

    server_zone = zone(server)

    if server_zone:
        params["zone"] = server_zone

    path = (
        "/api/lobby/connect-token?"
        + urllib.parse.urlencode(params)
    )

    status, payload, raw = http_get(
        path,
        timeout=15,
    )

    if status == 404:
        return ""

    if (
        status == 200
        and isinstance(payload, dict)
        and payload.get("ok") is not False
    ):
        return str(
            payload.get("token")
            or ""
        ).strip()

    error = (
        payload.get("error")
        if isinstance(payload, dict)
        else raw[:300]
    )

    raise RuntimeError(
        f"connect-token failed: "
        f"HTTP {status} error={error}"
    )


def presence_url(
    server: dict[str, Any],
) -> str:

    shard = route_shard(server)

    if shard <= 0:
        raise RuntimeError("Invalid route shard")

    ws_base = str(
        server.get("wsBaseUrl")
        or ""
    ).strip()

    if ws_base:
        if ws_base.startswith(
            ("ws://", "wss://")
        ):
            url = (
                ws_base.rstrip("/")
                + f"/ws/presence/s{shard}"
            )
        else:
            url = (
                re.sub(
                    r"^http",
                    "ws",
                    ws_base,
                    flags=re.I,
                ).rstrip("/")
                + f"/ws/presence/s{shard}"
            )
    else:
        url = (
            DEFAULT_WS_BASE
            + f"/ws/presence/s{shard}"
        )

    if blocked(url):
        raise RuntimeError("Blocked WebSocket URL")

    token = fetch_connect_token(server)

    if token:
        separator = "&" if "?" in url else "?"

        url += (
            separator
            + "kt="
            + urllib.parse.quote(
                token,
                safe="",
            )
        )

    return url


def open_presence(
    server: dict[str, Any],
):
    ws = websocket.create_connection(
        presence_url(server),
        timeout=20,
        cookie=OBSERVER_COOKIE,
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


def find_server(
    servers: list[dict[str, Any]],
) -> dict[str, Any]:

    for server in servers:
        if display_id(server) == TEST_SERVER_NUMBER:
            return server

    available = sorted({
        display_id(server)
        for server in servers
        if display_id(server) > 0
    })

    raise RuntimeError(
        f"Server {TEST_SERVER_NUMBER} was not found. "
        f"Available: {available}"
    )


def possible_observer_player(
    player: dict[str, Any],
) -> bool:

    try:
        x = float(player.get("x"))
        z = float(player.get("z"))
    except Exception:
        return False

    return (
        abs(x - OBSERVER_X) <= 0.15
        and abs(z - OBSERVER_Z) <= 0.15
        and not bool(player.get("mov"))
        and not player.get("act")
    )


def main() -> None:
    print("=" * 74)
    print("KINTARA EMBER OBSERVER — ONE SERVER TEST")
    print("=" * 74)
    print("Server:", TEST_SERVER_NUMBER)
    print("Region: ember")
    print(
        "Position:",
        OBSERVER_X,
        OBSERVER_Y,
        OBSERVER_Z,
    )
    print("Position message count: EXACTLY ONE")
    print("Fishing fields: NONE")
    print("Movement: false")
    print("Actions: NONE")
    print("Output:", OUTPUT_DIR)
    print("=" * 74)

    status, auth_payload, auth_raw = http_get(
        "/api/auth/me",
        timeout=20,
    )

    if status != 200:
        raise RuntimeError(
            f"Observer authentication failed: "
            f"HTTP {status} {auth_raw[:300]}"
        )

    status, servers_payload, servers_raw = http_get(
        "/api/servers",
        timeout=20,
    )

    if (
        status != 200
        or not isinstance(servers_payload, dict)
    ):
        raise RuntimeError(
            f"/api/servers failed: "
            f"HTTP {status} {servers_raw[:300]}"
        )

    servers = [
        server
        for server
        in (servers_payload.get("servers") or [])
        if isinstance(server, dict)
    ]

    server = find_server(servers)

    print(
        f"[OK] Connecting to "
        f"{server.get('name')} "
        f"shard={route_shard(server)} "
        f"zone={zone(server) or '-'}"
    )

    ws = open_presence(server)

    send_count = 0

    observer_message = {
        "t": "pos",
        "region": "ember",
        "x": OBSERVER_X,
        "y": OBSERVER_Y,
        "z": OBSERVER_Z,
        "ry": OBSERVER_RY,
        "mov": False,
        "outfit": {},
        "le": 0,
    }

    # The only outbound WebSocket message in this program.
    ws.send(
        json.dumps(
            observer_message,
            separators=(",", ":"),
        )
    )

    send_count += 1

    if send_count != 1:
        raise RuntimeError(
            "Unexpected WebSocket send count."
        )

    print("[SENT] One observer pos message")
    print("[WAIT] Receiving Ember snapshots...")

    started = time.time()

    frame_count = 0
    snapshot_count = 0
    ember_snapshot_count = 0

    latest_raw_count = None
    latest_adjusted_count = None
    latest_possible_self_count = None

    max_raw_count = 0
    max_adjusted_count = 0

    regions: dict[str, int] = {}

    with FRAMES_FILE.open(
        "w",
        encoding="utf-8",
    ) as output_file:

        while time.time() - started < CAPTURE_SECONDS:
            try:
                raw = ws.recv()

            except websocket.WebSocketTimeoutException:
                continue

            if raw in (None, ""):
                break

            frame_count += 1

            if isinstance(raw, bytes):
                frame: Any = {
                    "binary": True,
                    "length": len(raw),
                }
            else:
                try:
                    frame = json.loads(raw)
                except Exception:
                    frame = {
                        "raw": str(raw)[:50000]
                    }

            output_file.write(
                json.dumps(
                    {
                        "received_at": time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "frame": frame,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            )

            output_file.flush()

            if not isinstance(frame, dict):
                continue

            if str(frame.get("t") or "") != "snap":
                continue

            snapshot_count += 1

            region = str(
                frame.get("region")
                or ""
            ).strip().lower()

            regions[region] = (
                regions.get(region, 0) + 1
            )

            if region != "ember":
                continue

            ember_snapshot_count += 1

            players = frame.get("players")

            if not isinstance(players, list):
                players = []

            valid_players = [
                player
                for player in players
                if isinstance(player, dict)
            ]

            possible_self = [
                player
                for player in valid_players
                if possible_observer_player(player)
            ]

            raw_count = len(valid_players)

            # At most one exact observer-coordinate row is excluded.
            adjusted_count = max(
                0,
                raw_count - min(1, len(possible_self)),
            )

            latest_raw_count = raw_count
            latest_adjusted_count = adjusted_count
            latest_possible_self_count = len(
                possible_self
            )

            max_raw_count = max(
                max_raw_count,
                raw_count,
            )

            max_adjusted_count = max(
                max_adjusted_count,
                adjusted_count,
            )

            print(
                f"[EMBER SNAP] "
                f"raw={raw_count} "
                f"adjusted={adjusted_count} "
                f"observer_match={len(possible_self)}"
            )

    try:
        ws.close()
    except Exception:
        pass

    summary = {
        "server": server.get("name"),
        "display_id": display_id(server),
        "route_shard": route_shard(server),
        "zone": zone(server),
        "outbound_websocket_messages": send_count,
        "observer_message": observer_message,
        "capture_seconds": CAPTURE_SECONDS,
        "frames_received": frame_count,
        "snapshots_received": snapshot_count,
        "ember_snapshots_received": ember_snapshot_count,
        "snapshot_regions": regions,
        "latest_raw_player_count": latest_raw_count,
        "latest_adjusted_player_count": latest_adjusted_count,
        "latest_possible_observer_matches": latest_possible_self_count,
        "maximum_raw_player_count": max_raw_count,
        "maximum_adjusted_player_count": max_adjusted_count,
        "observer_visibility_warning": (
            "The observer account may be visible in Emberstone."
        ),
    }

    SUMMARY_JSON.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "KINTARA EMBER OBSERVER TEST",
        "=" * 70,
        f"Server: {summary['server']}",
        f"Shard: {summary['route_shard']}",
        f"Zone: {summary['zone']}",
        f"Outbound WebSocket messages: {send_count}",
        f"Frames received: {frame_count}",
        f"Snapshots received: {snapshot_count}",
        f"Ember snapshots: {ember_snapshot_count}",
        f"Snapshot regions: {regions}",
        f"Latest raw count: {latest_raw_count}",
        f"Latest adjusted count: {latest_adjusted_count}",
        (
            "Possible observer rows in latest snapshot: "
            f"{latest_possible_self_count}"
        ),
        f"Maximum raw count: {max_raw_count}",
        f"Maximum adjusted count: {max_adjusted_count}",
        "",
        "WARNING:",
        (
            "The observer account may appear as a player at "
            f"x={OBSERVER_X}, z={OBSERVER_Z}."
        ),
    ]

    SUMMARY_TXT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print()
    print("\n".join(lines))
    print()
    print("Saved:")
    print(SUMMARY_TXT)
    print(SUMMARY_JSON)
    print(FRAMES_FILE)


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nStopped by user.")

    except Exception as exc:
        fatal = OUTPUT_DIR / "FATAL.txt"

        fatal.write_text(
            repr(exc) + "\n",
            encoding="utf-8",
        )

        print()
        print("FATAL:", exc)
        print("Saved:", fatal)
        raise
