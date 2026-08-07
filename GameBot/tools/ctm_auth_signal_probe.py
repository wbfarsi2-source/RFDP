from __future__ import annotations

import gzip
import json
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
import websocket

BASE_URL = "https://kintara.gg"
REGION = "ember"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
CONNECT_TIMEOUT = 12.0
READ_TIMEOUT = 0.5
CAPTURE_SECONDS = 4.5
MAX_SCRIPT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_SCRIPT_BYTES = 16 * 1024 * 1024
MAX_SCAN_WORKERS = 6

try:
    from core.system_proxy import websocket_proxy_options
except Exception:
    def websocket_proxy_options(_url: str) -> dict[str, Any]:
        return {}




def _candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []

    def add(path: Path | str | None) -> None:
        if not path:
            return
        try:
            value = Path(path).expanduser().resolve()
        except Exception:
            return
        if value not in candidates:
            candidates.append(value)

    explicit = os.environ.get("GAMEBOT_PROJECT_ROOT")
    add(explicit)

    args = list(sys.argv[1:])
    if "--project-root" in args:
        index = args.index("--project-root")
        if index + 1 < len(args):
            add(args[index + 1])

    cwd = Path.cwd()
    script_path = Path(__file__).resolve()
    add(cwd)
    for parent in cwd.parents:
        add(parent)
    add(script_path.parent)
    for parent in script_path.parents:
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


def _project_root_score(path: Path) -> int:
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


def find_project_root() -> tuple[Path, list[tuple[Path, int]]]:
    ranked = sorted(
        ((path, _project_root_score(path)) for path in _candidate_project_roots()),
        key=lambda item: (-item[1], len(str(item[0]))),
    )
    if ranked and ranked[0][1] >= 18:
        return ranked[0][0], ranked

    checked = "\n".join(f"  - {path} (score={score})" for path, score in ranked[:15])
    raise RuntimeError(
        "Could not locate the GameBot project root. "
        "The correct folder must contain .env and games\\kintara.\n"
        f"Checked locations:\n{checked}"
    )


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


def http_headers(cookie: str, accept: str = "application/json,text/plain,*/*") -> dict[str, str]:
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


def http_client(cookie: str, trust_env: bool = True) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(25.0, connect=15.0),
        headers=http_headers(cookie),
        trust_env=trust_env,
        follow_redirects=True,
    )


def request_json(path: str, cookie: str) -> tuple[int, dict[str, Any], str]:
    errors: list[str] = []
    for trust_env, route in ((True, "system-route"), (False, "direct-fallback")):
        try:
            with http_client(cookie, trust_env=trust_env) as client:
                response = client.get(BASE_URL + path)
                payload = response.json() if response.content else {}
                if not isinstance(payload, dict):
                    payload = {"value_type": type(payload).__name__}
                return response.status_code, payload, route
        except Exception as exc:
            errors.append(f"{route}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


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


def endpoint_for(server: dict[str, Any], family: str) -> str:
    shard = route_shard(server)
    controller = controller_id(server)
    if shard <= 0:
        raise RuntimeError("Invalid route shard")
    if family == "fanout_controller":
        base = ws_origin(str(server.get("fanoutOrigin") or ""))
        if not base or not controller:
            raise RuntimeError("Missing fanoutOrigin/controllerId")
        return f"{base}/ws/spectate/{controller}/s{shard}"
    if family == "wsbase_controller":
        base = ws_origin(str(server.get("wsBaseUrl") or ""))
        if not base or not controller:
            raise RuntimeError("Missing wsBaseUrl/controllerId")
        return f"{base}/ws/spectate/{controller}/s{shard}"
    if family == "wsbase_legacy":
        base = ws_origin(str(server.get("wsBaseUrl") or ""))
        if not base:
            raise RuntimeError("Missing wsBaseUrl")
        return f"{base}/ws/spectate/s{shard}"
    raise RuntimeError(f"Unknown endpoint family: {family}")


def append_token(url: str, token: str) -> str:
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}kt={quote(token, safe='')}"


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
        if any(bool(player.get(key)) for key in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")):
            continue
        try:
            player_id = int(float(player.get("id") or 0))
        except Exception:
            player_id = 0
        if player_id > 0:
            ids.add(player_id)
    return len(ids)


def fetch_token(server: dict[str, Any], purpose: str, cookie: str) -> dict[str, Any]:
    shard = route_shard(server)
    zone = str(server.get("zone") or "").strip().lower()
    path = f"/api/lobby/connect-token?shard={shard}&purpose={quote(purpose)}"
    if zone:
        path += f"&zone={quote(zone)}"
    status, payload, route = request_json(path, cookie)
    token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
    return {
        "purpose": purpose,
        "status": status,
        "route": route,
        "ok": bool(status == 200 and payload.get("ok") is not False and token),
        "token_present": bool(token),
        "error": str(payload.get("error") or "")[:200],
        "_token": token,
    }


def open_websocket(url: str, cookie: str, send_cookie: bool):
    common: dict[str, Any] = {
        "timeout": CONNECT_TIMEOUT,
        "origin": BASE_URL,
        "enable_multithread": True,
        "header": [
            f"User-Agent: {USER_AGENT}",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
        ],
    }
    if send_cookie and cookie:
        common["cookie"] = cookie
    proxy_options = websocket_proxy_options(url)
    try:
        return websocket.create_connection(url, **common, **proxy_options), "system-route"
    except Exception as first_error:
        try:
            direct = dict(common)
            direct.update({"http_proxy_host": None, "http_proxy_port": None, "proxy_type": None, "http_no_proxy": ["*"]})
            return websocket.create_connection(url, **direct), "direct-fallback"
        except Exception as second_error:
            raise RuntimeError(
                f"{type(first_error).__name__}: {first_error} | "
                f"{type(second_error).__name__}: {second_error}"
            ) from second_error


def probe_method(
    server: dict[str, Any],
    *,
    label: str,
    family: str,
    cookie: str,
    send_cookie: bool,
    token: str,
) -> dict[str, Any]:
    endpoint = append_token(endpoint_for(server, family), token)
    result: dict[str, Any] = {
        "label": label,
        "server": str(server.get("name") or "?"),
        "family": family,
        "cookie_sent": bool(send_cookie and cookie),
        "token_sent": bool(token),
        "endpoint": endpoint.split("?", 1)[0] + ("?kt=<redacted>" if token else ""),
        "connected": False,
        "route": "",
        "regions": {},
        "snapshots": {},
        "ember_counts": [],
        "first_ember_ms": None,
        "error": "",
    }
    ws = None
    started = time.monotonic()
    region_counts: Counter[str] = Counter()
    snapshot_counts: Counter[str] = Counter()
    try:
        ws, route = open_websocket(endpoint, cookie, send_cookie)
        result["connected"] = True
        result["route"] = route
        ws.settimeout(READ_TIMEOUT)

        # Allow the initial world snapshot to establish the socket state.
        initial_deadline = time.monotonic() + 2.0
        while time.monotonic() < initial_deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            for message in decode_frames(raw):
                region = str(message.get("region") or "").strip().lower() or "<none>"
                region_counts[region] += 1
                if str(message.get("t") or "") == "snap":
                    snapshot_counts[region] += 1
            if snapshot_counts.get("world", 0) >= 1:
                break

        ws.send(json.dumps({"t": "spec_reg", "region": REGION}, separators=(",", ":")))
        retry_sent = False
        deadline = time.monotonic() + CAPTURE_SECONDS
        while time.monotonic() < deadline:
            if not retry_sent and time.monotonic() + 1.0 >= deadline:
                ws.send(json.dumps({"t": "spec_reg", "region": REGION}, separators=(",", ":")))
                retry_sent = True
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw in (None, ""):
                break
            for message in decode_frames(raw):
                region = str(message.get("region") or "").strip().lower() or "<none>"
                region_counts[region] += 1
                if str(message.get("t") or "") != "snap":
                    continue
                snapshot_counts[region] += 1
                if region == REGION:
                    if result["first_ember_ms"] is None:
                        result["first_ember_ms"] = int((time.monotonic() - started) * 1000)
                    result["ember_counts"].append(human_count(message.get("players")))
                    if snapshot_counts[REGION] >= 2:
                        break
            if snapshot_counts.get(REGION, 0) >= 2:
                break
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:600]
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    result["regions"] = dict(region_counts)
    result["snapshots"] = dict(snapshot_counts)
    return result


def collect_level_candidates(player: Any, prefix: str = "player", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4 or not isinstance(player, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, value in player.items():
        path = f"{prefix}.{key}"
        low = str(key).lower()
        if isinstance(value, (int, float)) and any(token in low for token in ("avg", "level", "lvl", "xp")):
            rows.append({"path": path, "value": value})
        elif isinstance(value, dict):
            rows.extend(collect_level_candidates(value, path, depth + 1))
    return rows[:120]


def sanitize_auth(payload: dict[str, Any], status: int, route: str) -> dict[str, Any]:
    player = payload.get("player") if isinstance(payload, dict) else None
    result: dict[str, Any] = {
        "status": status,
        "route": route,
        "ok": bool(status == 200 and isinstance(player, dict)),
        "error": str(payload.get("error") or "")[:200] if isinstance(payload, dict) else "",
        "player_keys": sorted(str(key) for key in player.keys()) if isinstance(player, dict) else [],
        "level_candidates": collect_level_candidates(player) if isinstance(player, dict) else [],
    }
    return result


def same_origin_scripts(html: str, page_url: str) -> list[str]:
    host = urlparse(BASE_URL).netloc
    found: list[str] = []
    for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(page_url, match.group(1))
        parsed = urlparse(url)
        if parsed.netloc != host or "terms" in parsed.path.lower():
            continue
        if url not in found:
            found.append(url)
    return found


def snippets(text: str, needle: str, radius: int = 900, limit: int = 8) -> list[str]:
    rows: list[str] = []
    start = 0
    while len(rows) < limit:
        index = text.find(needle, start)
        if index < 0:
            break
        rows.append(text[max(0, index - radius): min(len(text), index + len(needle) + radius)])
        start = index + len(needle)
    return rows


def scan_frontend(cookie: str) -> dict[str, Any]:
    result: dict[str, Any] = {"pages": [], "scripts": [], "matches": {}}
    script_urls: list[str] = []
    total = 0
    with http_client(cookie, trust_env=True) as client:
        for path in ("/", "/play"):
            url = BASE_URL + path
            response = client.get(url)
            text = response.text if response.status_code < 400 else ""
            result["pages"].append({"url": url, "status": response.status_code, "bytes": len(response.content)})
            script_urls.extend(same_origin_scripts(text, url))
        for url in script_urls[:8]:
            if total >= MAX_TOTAL_SCRIPT_BYTES:
                break
            response = client.get(url)
            body = response.content[: min(MAX_SCRIPT_BYTES, MAX_TOTAL_SCRIPT_BYTES - total)]
            total += len(body)
            text = body.decode("utf-8", errors="replace")
            result["scripts"].append({"url": url, "status": response.status_code, "bytes": len(body)})
            if not text:
                continue
            for needle in (
                "bossCaveActive",
                "bossCaveCapacity",
                "/api/lobby/connect-token",
                "buildSpectateWsUrl",
                "canEnterEmberOrToast",
                '"spec_reg"',
                "worldChatRegionKey",
            ):
                found = snippets(text, needle)
                if found:
                    result["matches"].setdefault(needle, []).extend({"url": url, "context": row} for row in found)
    return result


def stable_count(values: list[int]) -> int | None:
    if not values:
        return None
    recent = values[-20:]
    counts = Counter(recent)
    return max(counts, key=lambda value: (counts[value], value))


def winning_probe(probes: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [row for row in probes if int(row.get("snapshots", {}).get(REGION, 0)) >= 2]
    if not valid:
        return None
    return sorted(valid, key=lambda row: (not row.get("token_sent"), not row.get("cookie_sent"), row.get("label", "")))[0]


def main() -> int:
    project_root, ranked_roots = find_project_root()
    env_path = project_root / ".env"
    env = load_env(env_path)
    cookie = normalize_cookie(env)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_auth_signal_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("KINTARA COME TO MOLTEN AUTHENTICATED SPECTATOR AND SERVER SIGNAL PROBE")
    print("=" * 84)
    print(f"Project root: {project_root}")
    print(f"Environment file: {env_path}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    print("This test does not send movement, combat, farming, or account-changing messages.")
    print("-" * 84)

    if not cookie:
        expected = "KINTARA_EMBER_COOKIE or KINTARA_COOKIE"
        print("ERROR: The GameBot project was found, but the Kintara connection value is missing.")
        print(f"Add {expected} to: {env_path}")
        print("The authenticated test was not started, because running it without the cookie would produce invalid 401 results.")
        return 2

    auth_status, auth_payload, auth_route = request_json("/api/auth/me", cookie)
    auth = sanitize_auth(auth_payload, auth_status, auth_route)
    print(f"/api/auth/me: status={auth_status} valid={auth['ok']}")

    server_status, server_payload, server_route = request_json(f"/api/servers?_={time.time_ns()}", cookie)
    all_servers = [dict(row) for row in server_payload.get("servers") or [] if isinstance(row, dict)]
    numbered_servers = [row for row in all_servers if server_number(row) > 0]
    numbered_servers.sort(key=server_number)
    club_servers = [row for row in all_servers if str(row.get("name") or "").startswith("Kintara Club")]
    print(f"/api/servers: status={server_status} normal_servers={len(numbered_servers)} clubs={len(club_servers)}")

    boss_signal = [
        {
            "server": str(row.get("name") or "?"),
            "number": server_number(row),
            "bossCaveActive": int(row.get("bossCaveActive") or 0),
            "bossCaveCapacity": int(row.get("bossCaveCapacity") or 0),
        }
        for row in numbered_servers
    ]
    boss_top3 = sorted(boss_signal, key=lambda row: (-row["bossCaveActive"], row["number"]))[:3]

    frontend = scan_frontend(cookie)
    print(f"Frontend scripts checked: {len(frontend['scripts'])}")
    print(f"bossCaveActive source matches: {len(frontend['matches'].get('bossCaveActive', []))}")

    if not numbered_servers:
        raise RuntimeError("No normal Server N entries were returned")
    primary = next((row for row in numbered_servers if server_number(row) == 4), numbered_servers[0])
    secondary = next((row for row in numbered_servers if server_number(row) == 24), numbered_servers[-1])

    token_rows: dict[str, dict[str, Any]] = {}
    for purpose in ("spectate", "presence"):
        token_rows[purpose] = fetch_token(primary, purpose, cookie)
        print(
            f"connect-token purpose={purpose}: status={token_rows[purpose]['status']} "
            f"token={token_rows[purpose]['token_present']} error={token_rows[purpose]['error'] or '-'}"
        )

    methods = [
        ("fanout-controller anonymous", "fanout_controller", False, ""),
        ("fanout-controller cookie", "fanout_controller", True, ""),
        ("fanout-controller spectate-token", "fanout_controller", True, token_rows["spectate"].get("_token", "")),
        ("fanout-controller presence-token", "fanout_controller", True, token_rows["presence"].get("_token", "")),
        ("wsbase-controller cookie", "wsbase_controller", True, ""),
        ("wsbase-controller presence-token", "wsbase_controller", True, token_rows["presence"].get("_token", "")),
        ("wsbase-legacy cookie", "wsbase_legacy", True, ""),
        ("wsbase-legacy presence-token", "wsbase_legacy", True, token_rows["presence"].get("_token", "")),
    ]

    probes: list[dict[str, Any]] = []
    for label, family, send_cookie, token in methods:
        if "token" in label and not token:
            probes.append({
                "label": label,
                "server": str(primary.get("name") or "?"),
                "family": family,
                "cookie_sent": bool(send_cookie and cookie),
                "token_sent": False,
                "endpoint": "",
                "connected": False,
                "route": "",
                "regions": {},
                "snapshots": {},
                "ember_counts": [],
                "first_ember_ms": None,
                "error": "Token was not issued",
            })
            continue
        row = probe_method(
            primary,
            label=label,
            family=family,
            cookie=cookie,
            send_cookie=send_cookie,
            token=str(token or ""),
        )
        probes.append(row)
        print(
            f"[{label}] connected={row['connected']} world={row['snapshots'].get('world', 0)} "
            f"ember={row['snapshots'].get('ember', 0)} error={row['error'] or '-'}"
        )
        time.sleep(0.15)

    winner = winning_probe(probes)
    verification: dict[str, Any] | None = None
    full_scan: list[dict[str, Any]] = []
    top3: list[dict[str, Any]] = []

    if winner is not None:
        winning_token = ""
        if winner.get("token_sent"):
            winning_token = token_rows["spectate"].get("_token", "") if "spectate-token" in winner["label"] else token_rows["presence"].get("_token", "")
        verification = probe_method(
            secondary,
            label=winner["label"],
            family=winner["family"],
            cookie=cookie,
            send_cookie=bool(winner.get("cookie_sent")),
            token=str(winning_token or ""),
        )
        print(
            f"Winner verification on {verification['server']}: "
            f"ember={verification['snapshots'].get('ember', 0)} error={verification['error'] or '-'}"
        )

        if int(verification.get("snapshots", {}).get(REGION, 0)) >= 2:
            def scan_one(server: dict[str, Any]) -> dict[str, Any]:
                method_token = ""
                if winner.get("token_sent"):
                    purpose = "spectate" if "spectate-token" in winner["label"] else "presence"
                    token_meta = fetch_token(server, purpose, cookie)
                    method_token = str(token_meta.get("_token") or "")
                row = probe_method(
                    server,
                    label=winner["label"],
                    family=winner["family"],
                    cookie=cookie,
                    send_cookie=bool(winner.get("cookie_sent")),
                    token=method_token,
                )
                row["number"] = server_number(server)
                row["stable_count"] = stable_count(row.get("ember_counts") or [])
                return row

            with ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS) as pool:
                future_map = {pool.submit(scan_one, server): server for server in numbered_servers}
                for future in as_completed(future_map):
                    row = future.result()
                    full_scan.append(row)
                    print(
                        f"[{row['server']}] Ember={row.get('stable_count')} "
                        f"snaps={row.get('snapshots', {}).get('ember', 0)} error={row.get('error') or '-'}"
                    )
            full_scan.sort(key=lambda row: int(row.get("number") or 0))
            valid = [row for row in full_scan if row.get("stable_count") is not None]
            top3 = sorted(valid, key=lambda row: (-int(row["stable_count"]), int(row["number"])))[:3]

    for row in token_rows.values():
        row.pop("_token", None)

    report = {
        "created_at": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "cookie_present": bool(cookie),
        "auth": auth,
        "server_list": {
            "status": server_status,
            "route": server_route,
            "all_entries": len(all_servers),
            "normal_servers": len(numbered_servers),
            "club_entries": len(club_servers),
        },
        "boss_cave_signal": {
            "note": "Current /api/servers field. This probe does not assume it equals all human players in The Emberstone.",
            "servers": boss_signal,
            "top3": boss_top3,
        },
        "frontend_scan": frontend,
        "tokens": token_rows,
        "primary_server": str(primary.get("name") or "?"),
        "probes": probes,
        "winner": winner,
        "verification": verification,
        "full_scan": full_scan,
        "top3": [
            {"server": row["server"], "number": row["number"], "players": row["stable_count"]}
            for row in top3
        ],
    }

    report_path = output_dir / "auth_signal_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "KINTARA COME TO MOLTEN AUTHENTICATED SPECTATOR AND SERVER SIGNAL PROBE",
        "=" * 84,
        f"Created: {report['created_at']}",
        f"Auth valid: {auth['ok']} (status={auth_status})",
        f"Server entries: all={len(all_servers)} normal={len(numbered_servers)} clubs={len(club_servers)}",
        "",
        "CURRENT /api/servers bossCaveActive TOP 3 (NOT YET ASSUMED TO EQUAL EMBER MAP POPULATION)",
        "-" * 84,
    ]
    for index, row in enumerate(boss_top3, 1):
        lines.append(
            f"{index}. {row['server']} - active={row['bossCaveActive']} capacity={row['bossCaveCapacity']}"
        )
    lines += ["", "AUTHENTICATED SPECTATOR METHOD RESULTS", "-" * 84]
    for row in probes:
        lines.append(
            f"{row['label']:<42} connected={str(row.get('connected')):<5} "
            f"world={int(row.get('snapshots', {}).get('world', 0)):>3} "
            f"ember={int(row.get('snapshots', {}).get('ember', 0)):>3} "
            f"error={row.get('error') or '-'}"
        )
    lines += ["", "RESULT", "-" * 84]
    if winner is None:
        lines.append("No spectator-only method produced an Ember snapshot.")
        lines.append("The next protocol step would require an authenticated presence-session test.")
        lines.append("That step is intentionally not performed here because it can put the account online.")
    else:
        lines.append(f"Working method: {winner['label']}")
        if top3:
            lines.append("")
            lines.append("TOP 3 VERIFIED EMBER SERVERS")
            for index, row in enumerate(top3, 1):
                lines.append(f"{index}. {row['server']} - {row['stable_count']} player(s)")
        elif full_scan:
            lines.append("No human player is currently detected in The Emberstone.")
        else:
            lines.append("The method worked on the primary server but did not pass cross-server verification.")
    lines += ["", f"Full report: {report_path}"]

    summary_path = output_dir / "summary.txt"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("-" * 84)
    print("\n".join(lines[-12:]))
    print(f"\nOutput folder: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        raise
