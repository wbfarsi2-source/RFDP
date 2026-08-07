from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError as exc:
    raise SystemExit("Missing dependency: httpx. Run with the project virtual environment.") from exc

try:
    import websocket
except ImportError as exc:
    raise SystemExit("Missing dependency: websocket-client. Run with the project virtual environment.") from exc

BASE_DEFAULT = "https://kintara.gg"
ORIGIN_DEFAULT = "https://kintara.gg"
CAPTURE_SECONDS = 3.5
MAX_JS_FILES = 8
MAX_JS_BYTES_TOTAL = 14 * 1024 * 1024
MAX_JS_BYTES_EACH = 4 * 1024 * 1024

PAYLOAD_PROBES: list[tuple[str, dict[str, Any] | None]] = [
    ("no-registration", None),
    ("region-ember", {"t": "spec_reg", "region": "ember"}),
    ("region-emberstone", {"t": "spec_reg", "region": "emberstone"}),
    ("region-the-emberstone", {"t": "spec_reg", "region": "the_emberstone"}),
    ("region-molten", {"t": "spec_reg", "region": "molten"}),
    ("zone-ember", {"t": "spec_reg", "zone": "ember"}),
    ("area-ember", {"t": "spec_reg", "area": "ember"}),
    ("map-ember", {"t": "spec_reg", "map": "ember"}),
    ("short-r-ember", {"t": "spec_reg", "r": "ember"}),
    ("world-zone-ember", {"t": "spec_reg", "region": "world", "zone": "ember"}),
    ("world-subregion-ember", {"t": "spec_reg", "region": "world", "subregion": "ember"}),
]

URL_PROBES = [
    ("query-region", "?region=ember"),
    ("query-zone", "?zone=ember"),
    ("query-area", "?area=ember"),
]

SEARCH_PATTERNS = [
    "spec_reg",
    "ws/spectate",
    "emberstone",
    "the_emberstone",
    'region:"ember"',
    "region:'ember'",
    'region:"world"',
]


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


def project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".env").exists() or (candidate / "START_GAMEBOT.bat").exists():
            return candidate
    return start


def server_number(row: dict[str, Any]) -> int:
    match = re.fullmatch(r"Server\s+(\d+)", str(row.get("name") or "").strip())
    return int(match.group(1)) if match else -1


def shard_id(row: dict[str, Any]) -> int:
    for key in ("routeShardId", "localShardId", "id"):
        try:
            value = int(float(row.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def ws_url(row: dict[str, Any], suffix: str = "") -> str:
    shard = shard_id(row)
    if shard <= 0:
        raise RuntimeError("Invalid shard")
    base = str(row.get("wsBaseUrl") or "").strip()
    if not base:
        base = BASE_DEFAULT
    if not base.startswith(("ws://", "wss://")):
        base = re.sub(r"^http", "ws", base, flags=re.I)
    return base.rstrip("/") + f"/ws/spectate/s{shard}" + suffix


def decode(raw: Any) -> list[dict[str, Any]]:
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


def safe_top_level(message: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in message.items():
        low = key.lower()
        if any(token in low for token in ("token", "cookie", "secret", "authorization", "proof")):
            result[key] = "<redacted>"
        elif key == "players" and isinstance(value, list):
            result["players_count"] = len(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list):
            result[key] = f"<list:{len(value)}>"
        elif isinstance(value, dict):
            result[key] = f"<dict:{len(value)}>"
        else:
            result[key] = f"<{type(value).__name__}>"
    return result


def run_ws_probe(server: dict[str, Any], label: str, payload: dict[str, Any] | None, suffix: str = "") -> dict[str, Any]:
    endpoint = ws_url(server, suffix)
    started = time.monotonic()
    message_types: Counter[str] = Counter()
    regions: Counter[str] = Counter()
    player_counts: list[int] = []
    samples: list[dict[str, Any]] = []
    error = ""
    connected = False
    first_snapshot_ms: int | None = None
    ws = None
    try:
        ws = websocket.create_connection(
            endpoint,
            timeout=8,
            origin=ORIGIN_DEFAULT,
            enable_multithread=True,
            header=[
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ],
        )
        connected = True
        ws.settimeout(0.6)
        if payload is not None:
            ws.send(json.dumps(payload, separators=(",", ":")))
        deadline = time.monotonic() + CAPTURE_SECONDS
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            for message in decode(raw):
                msg_type = str(message.get("t") or "<none>")
                message_types[msg_type] += 1
                region = str(message.get("region") or "").strip().lower()
                if region:
                    regions[region] += 1
                if msg_type == "snap":
                    if first_snapshot_ms is None:
                        first_snapshot_ms = int((time.monotonic() - started) * 1000)
                    players = message.get("players")
                    if isinstance(players, list):
                        player_counts.append(len(players))
                if len(samples) < 8 and (msg_type != "snap" or not samples):
                    samples.append(safe_top_level(message))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass
    return {
        "label": label,
        "server": str(server.get("name") or "?"),
        "endpoint": endpoint,
        "payload": payload,
        "connected": connected,
        "first_snapshot_ms": first_snapshot_ms,
        "message_types": dict(message_types),
        "regions": dict(regions),
        "player_counts": player_counts[:20],
        "samples": samples,
        "error": error,
    }


def same_origin_js_urls(html: str, page_url: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(page_url, match.group(1))
        parsed = urlparse(url)
        base = urlparse(base_url)
        if parsed.netloc != base.netloc:
            continue
        if "terms" in parsed.path.lower():
            continue
        if url not in urls:
            urls.append(url)
    return urls


def snippets(text: str, pattern: str, radius: int = 260, limit: int = 12) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    needle = pattern.lower()
    start = 0
    while len(found) < limit:
        index = lower.find(needle, start)
        if index < 0:
            break
        left = max(0, index - radius)
        right = min(len(text), index + len(pattern) + radius)
        found.append(text[left:right].replace("\r", " ").replace("\n", " "))
        start = index + len(pattern)
    return found


def scan_frontend(client: httpx.Client, base_url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"pages": [], "scripts": [], "matches": []}
    script_urls: list[str] = []
    for path in ("/", "/play"):
        if "terms" in path.lower():
            continue
        url = base_url.rstrip("/") + path
        try:
            response = client.get(url, timeout=15)
            result["pages"].append({"url": url, "status": response.status_code, "length": len(response.content)})
            if response.status_code == 200:
                for item in same_origin_js_urls(response.text, url, base_url):
                    if item not in script_urls:
                        script_urls.append(item)
        except Exception as exc:
            result["pages"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    total = 0
    for url in script_urls[:MAX_JS_FILES]:
        if total >= MAX_JS_BYTES_TOTAL:
            break
        try:
            response = client.get(url, timeout=20)
            content = response.content[:MAX_JS_BYTES_EACH]
            total += len(content)
            text = content.decode("utf-8", errors="replace")
            item = {"url": url, "status": response.status_code, "bytes_read": len(content)}
            result["scripts"].append(item)
            if response.status_code != 200:
                continue
            for pattern in SEARCH_PATTERNS:
                for sample in snippets(text, pattern):
                    result["matches"].append({"url": url, "pattern": pattern, "snippet": sample})
        except Exception as exc:
            result["scripts"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return result


def choose_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_number = {server_number(row): row for row in servers}
    chosen: list[dict[str, Any]] = []
    for number in (24, 4):
        row = by_number.get(number)
        if row is not None:
            chosen.append(row)
    if not chosen and servers:
        chosen.append(servers[0])
    return chosen


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = project_root(script_dir)
    load_env(root / ".env")
    base_url = os.environ.get("KINTARA_BASE_URL", BASE_DEFAULT).strip().rstrip("/") or BASE_DEFAULT
    cookie = os.environ.get("KINTARA_COOKIE", "").strip()
    if not cookie:
        raise SystemExit("KINTARA_COOKIE is missing from .env")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = root / "diagnostics" / f"ctm_protocol_probe_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Origin": base_url,
        "Referer": base_url + "/play",
        "Cookie": cookie,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    print("=" * 78)
    print("KINTARA COME TO MOLTEN PROTOCOL PROBE")
    print("=" * 78)
    print("This is a controlled read-only test.")
    print("It never opens terms.html and never sends gameplay actions.")
    print("Each candidate uses one fresh spectator connection and one registration message.")
    print(f"Output: {out_dir}")
    print("-" * 78)

    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "base_url": base_url,
        "cookie_present": True,
        "capture_seconds": CAPTURE_SECONDS,
        "server_list": {},
        "selected_servers": [],
        "payload_probes": [],
        "url_probes": [],
        "frontend_scan": {},
    }

    with httpx.Client(headers=headers, trust_env=True, follow_redirects=True) as client:
        response = client.get(base_url + "/api/servers", params={"_": str(int(time.time() * 1000))}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        rows = [dict(row) for row in (payload.get("servers") or []) if isinstance(row, dict) and server_number(row) >= 1]
        rows.sort(key=server_number)
        report["server_list"] = {
            "status": response.status_code,
            "count": len(rows),
            "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            "server_field_sets": sorted({tuple(sorted(row.keys())) for row in rows}),
            "servers": rows,
        }
        selected = choose_servers(rows)
        report["selected_servers"] = [str(row.get("name") or "?") for row in selected]

        if not selected:
            raise RuntimeError("No numbered servers returned")

        primary = selected[0]
        print(f"Primary probe server: {primary.get('name')}")
        for index, (label, probe_payload) in enumerate(PAYLOAD_PROBES, 1):
            print(f"[{index:02d}/{len(PAYLOAD_PROBES)}] {label}")
            result = run_ws_probe(primary, label, probe_payload)
            report["payload_probes"].append(result)
            print(f"    regions={result['regions']} snapshots={result['message_types'].get('snap', 0)} error={result['error'] or '-'}")
            time.sleep(0.35)

        old_payload = {"t": "spec_reg", "region": "ember"}
        for label, suffix in URL_PROBES:
            print(f"[URL] {label}")
            result = run_ws_probe(primary, label, old_payload, suffix=suffix)
            report["url_probes"].append(result)
            print(f"    regions={result['regions']} snapshots={result['message_types'].get('snap', 0)} error={result['error'] or '-'}")
            time.sleep(0.35)

        if len(selected) > 1:
            confirmation = run_ws_probe(selected[1], "confirmation-region-ember", old_payload)
            report["payload_probes"].append(confirmation)
            print(f"Confirmation server: {confirmation['server']} regions={confirmation['regions']}")

        print("Scanning current same-origin frontend scripts for protocol strings...")
        report["frontend_scan"] = scan_frontend(client, base_url)

    report_path = out_dir / "protocol_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary_lines = [
        "KINTARA COME TO MOLTEN PROTOCOL PROBE",
        "=" * 78,
        f"Created: {report['created_at']}",
        f"Servers: {report['server_list'].get('count', 0)}",
        f"Selected: {', '.join(report['selected_servers'])}",
        "",
        "PAYLOAD RESULTS",
        "-" * 78,
    ]
    for row in report["payload_probes"]:
        summary_lines.append(
            f"{row['server']} | {row['label']:<28} | regions={row['regions']} | "
            f"snaps={row['message_types'].get('snap', 0)} | error={row['error'] or '-'}"
        )
    summary_lines.extend(["", "URL RESULTS", "-" * 78])
    for row in report["url_probes"]:
        summary_lines.append(
            f"{row['server']} | {row['label']:<28} | regions={row['regions']} | "
            f"snaps={row['message_types'].get('snap', 0)} | error={row['error'] or '-'}"
        )
    summary_lines.extend([
        "",
        "FRONTEND SCAN",
        "-" * 78,
        f"Pages checked: {len(report['frontend_scan'].get('pages', []))}",
        f"Scripts checked: {len(report['frontend_scan'].get('scripts', []))}",
        f"Protocol matches: {len(report['frontend_scan'].get('matches', []))}",
        "",
        f"Full report: {report_path}",
    ])
    summary_path = out_dir / "summary.txt"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print("-" * 78)
    print("Probe completed.")
    print(f"Send these files:")
    print(f"  {summary_path}")
    print(f"  {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
