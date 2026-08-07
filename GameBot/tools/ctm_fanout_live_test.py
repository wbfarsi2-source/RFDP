from __future__ import annotations

import gzip
import json
import os
import re
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import websocket

try:
    from core.system_proxy import websocket_proxy_options
except Exception:
    def websocket_proxy_options(_url: str) -> dict[str, Any]:
        return {}

BASE_URL = "https://kintara.gg"
REGION = "ember"
CAPTURE_SECONDS = 6.0
CONNECT_TIMEOUT_SECONDS = 12.0
SOCKET_TIMEOUT_SECONDS = 0.75
MAX_WORKERS = 8


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def cookie_header(env: dict[str, str]) -> str:
    raw = (env.get("KINTARA_EMBER_COOKIE") or env.get("KINTARA_COOKIE") or "").strip()
    if not raw:
        return ""
    if "=" not in raw:
        return f"__Host-kintara_session={raw}"
    return raw


def server_number(server: dict[str, Any]) -> int:
    for key in ("displayId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    match = re.fullmatch(r"Server\s+(\d+)", str(server.get("name") or ""))
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


def clean_controller(server: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(server.get("controllerId") or "").strip().lower())[:24]


def official_endpoint(server: dict[str, Any]) -> str:
    origin = str(server.get("fanoutOrigin") or "").strip()
    controller = clean_controller(server)
    shard = route_shard(server)
    if not origin:
        raise RuntimeError("fanoutOrigin is missing")
    if not controller:
        raise RuntimeError("controllerId is missing")
    if shard <= 0:
        raise RuntimeError("routeShardId is invalid")
    ws_origin = re.sub(r"^https:", "wss:", origin, flags=re.I)
    ws_origin = re.sub(r"^http:", "ws:", ws_origin, flags=re.I)
    return f"{ws_origin.rstrip('/')}/ws/spectate/{controller}/s{shard}"


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
        return [row for row in payload if isinstance(row, dict)]
    return []


def human_count(players: Any) -> int:
    if not isinstance(players, list):
        return 0
    ids: set[int] = set()
    for player in players:
        if not isinstance(player, dict):
            continue
        if any(bool(player.get(k)) for k in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")):
            continue
        try:
            player_id = int(float(player.get("id") or 0))
        except Exception:
            player_id = 0
        if player_id > 0:
            ids.add(player_id)
    return len(ids)


def probe_server(server: dict[str, Any]) -> dict[str, Any]:
    number = server_number(server)
    name = str(server.get("name") or f"Server {number}")
    result: dict[str, Any] = {
        "server": name,
        "number": number,
        "zone": str(server.get("zone") or ""),
        "controllerId": clean_controller(server),
        "routeShardId": route_shard(server),
        "fanoutOrigin": str(server.get("fanoutOrigin") or ""),
        "endpoint": "",
        "connected": False,
        "ember_snapshots": 0,
        "world_snapshots": 0,
        "counts": [],
        "stable_count": None,
        "latest_count": None,
        "first_ember_ms": None,
        "regions": {},
        "error": "",
    }
    started = time.monotonic()
    ws = None
    try:
        endpoint = official_endpoint(server)
        result["endpoint"] = endpoint
        ws = websocket.create_connection(
            endpoint,
            timeout=CONNECT_TIMEOUT_SECONDS,
            origin=BASE_URL,
            enable_multithread=True,
            header=[
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ],
            **websocket_proxy_options(endpoint),
        )
        result["connected"] = True
        ws.settimeout(SOCKET_TIMEOUT_SECONDS)
        ws.send(json.dumps({"t": "spec_reg", "region": REGION}, separators=(",", ":")))
        deadline = time.monotonic() + CAPTURE_SECONDS
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            for message in decode_frames(raw):
                if str(message.get("t") or "") != "snap":
                    continue
                region = str(message.get("region") or "").strip().lower() or "<none>"
                result["regions"][region] = int(result["regions"].get(region, 0)) + 1
                if region == "world":
                    result["world_snapshots"] += 1
                if region != REGION:
                    continue
                result["ember_snapshots"] += 1
                if result["first_ember_ms"] is None:
                    result["first_ember_ms"] = int((time.monotonic() - started) * 1000)
                count = human_count(message.get("players"))
                result["counts"].append(count)
        if result["counts"]:
            recent = result["counts"][-20:]
            result["latest_count"] = recent[-1]
            frequencies = Counter(recent)
            result["stable_count"] = max(frequencies, key=lambda value: (frequencies[value], value))
        elif not result["error"]:
            result["error"] = "No Ember snapshot received"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    return result


def fetch_servers(cookie: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/play",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie
    attempts: list[dict[str, Any]] = []
    for trust_env, label in ((True, "system-route"), (False, "direct-fallback")):
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, connect=15.0), headers=headers, trust_env=trust_env) as client:
                response = client.get(BASE_URL + "/api/servers", params={"_": str(time.time_ns())})
                attempts.append({"route": label, "status": response.status_code})
                payload = response.json()
                if response.status_code == 200 and isinstance(payload, dict):
                    rows = [dict(row) for row in payload.get("servers") or [] if isinstance(row, dict)]
                    rows = [row for row in rows if server_number(row) > 0]
                    rows.sort(key=server_number)
                    if rows:
                        return rows, {"status": response.status_code, "route": label, "attempts": attempts}
        except Exception as exc:
            attempts.append({"route": label, "error": f"{type(exc).__name__}: {exc}"})
    raise RuntimeError(f"Could not load /api/servers: {attempts}")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    env = load_env(project_root / ".env")
    cookie = cookie_header(env)
    output_root = project_root / "diagnostics"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / f"ctm_fanout_live_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 82)
    print("KINTARA COME TO MOLTEN FANOUT LIVE TEST")
    print("=" * 82)
    print(f"Project root: {project_root}")
    print(f"Cookie for /api/servers: {'loaded' if cookie else 'missing'}")
    print("WebSocket route: fanoutOrigin + controllerId + routeShardId")
    print("Region: ember")
    print("-" * 82)

    servers, server_meta = fetch_servers(cookie)
    print(f"Found {len(servers)} numbered servers. Checking live Ember snapshots...")

    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(probe_server, server): server for server in servers}
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            status = f"Ember={row['stable_count']}" if row.get("stable_count") is not None else "NO EMBER"
            print(f"[{row['server']}] {status} | snaps={row['ember_snapshots']} | {row['error'] or 'OK'}")

    results.sort(key=lambda row: int(row.get("number") or 0))
    valid = [row for row in results if row.get("stable_count") is not None and int(row.get("ember_snapshots") or 0) > 0]
    top3 = sorted(valid, key=lambda row: (-int(row["stable_count"]), int(row["number"])))[:3]

    report = {
        "created_at": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "server_list": server_meta,
        "server_count": len(servers),
        "successful_ember_servers": len(valid),
        "results": results,
        "top3": [
            {"server": row["server"], "number": row["number"], "players": row["stable_count"]}
            for row in top3
        ],
    }
    (output_dir / "fanout_live_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "KINTARA COME TO MOLTEN FANOUT LIVE TEST",
        "=" * 78,
        f"Created: {report['created_at']}",
        f"Numbered servers: {len(servers)}",
        f"Servers with verified Ember snapshots: {len(valid)}/{len(servers)}",
        "",
        "SERVER RESULTS",
        "-" * 78,
    ]
    for row in results:
        count = "-" if row.get("stable_count") is None else str(row["stable_count"])
        lines.append(
            f"{row['server']:<12} players={count:>3} ember_snaps={row['ember_snapshots']:>3} "
            f"first_ms={str(row.get('first_ember_ms') or '-'):>6} error={row['error'] or '-'}"
        )
    lines += ["", "TOP 3 VERIFIED EMBER SERVERS", "-" * 78]
    if top3:
        for index, row in enumerate(top3, 1):
            lines.append(f"{index}. {row['server']} — {row['stable_count']} player(s)")
    elif len(valid) == len(servers):
        lines.append("No human player is currently detected in The Emberstone.")
    else:
        lines.append("No verified Top 3 could be produced because Ember snapshots were incomplete.")
    summary = "\n".join(lines) + "\n"
    (output_dir / "summary.txt").write_text(summary, encoding="utf-8")

    print("\n" + summary)
    print(f"Report: {output_dir / 'fanout_live_report.json'}")
    print(f"Summary: {output_dir / 'summary.txt'}")
    return 0 if len(valid) == len(servers) else 2


if __name__ == "__main__":
    raise SystemExit(main())
