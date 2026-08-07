from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

import ctm_common_capture as common

BASE_URL = common.BASE_URL
CANDIDATE_RE = re.compile(
    r"ember|molten|cave|boss|active|online|player|count|population|occup|capacity|region|realm|presence",
    re.I,
)
SECRET_RE = re.compile(r"cookie|token|authorization|secret|session", re.I)


def safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if SECRET_RE.search(str(key)):
                out[str(key)] = "<redacted>"
            else:
                out[str(key)] = safe_value(child)
        return out
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "...<truncated>"
    return value


def fetch_json_url(url: str, cookie: str = "", *, send_cookie: bool = False) -> dict[str, Any]:
    headers = common.request_headers(cookie if send_cookie else "")
    headers["Origin"] = BASE_URL
    headers["Referer"] = BASE_URL + "/play"
    attempts = []
    for trust_env, route in ((True, "system-route"), (False, "direct-fallback")):
        try:
            with httpx.Client(
                timeout=common.HTTP_TIMEOUT,
                headers=headers,
                trust_env=trust_env,
                follow_redirects=True,
            ) as client:
                response = client.get(url)
            try:
                payload = response.json() if response.content else {}
            except Exception:
                payload = {"raw_preview": response.text[:1000]}
            return {
                "url": url,
                "route": route,
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "payload": safe_value(payload),
            }
        except Exception as exc:
            attempts.append(f"{route}: {type(exc).__name__}: {exc}")
    return {"url": url, "status": 0, "error": " | ".join(attempts), "payload": {}}


def flatten_keys(value: Any, prefix: str = "") -> Counter[str]:
    found: Counter[str] = Counter()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found[path] += 1
            found.update(flatten_keys(child, path))
    elif isinstance(value, list):
        for child in value:
            found.update(flatten_keys(child, prefix + "[]"))
    return found


def summarize_servers(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Payload is not an object"}
    servers = [row for row in payload.get("servers") or [] if isinstance(row, dict)]
    normal = sorted(
        [row for row in servers if common.server_number(row) >= 1],
        key=common.server_number,
    )
    all_keys = sorted({str(key) for row in servers for key in row.keys()})
    candidate_keys = [key for key in all_keys if CANDIDATE_RE.search(key)]

    field_matrix: dict[str, list[dict[str, Any]]] = {}
    for key in candidate_keys:
        rows = []
        for server in normal:
            if key in server:
                rows.append({
                    "server": str(server.get("name") or "?"),
                    "number": common.server_number(server),
                    "value": safe_value(server.get(key)),
                })
        field_matrix[key] = rows

    numeric_top3: dict[str, list[dict[str, Any]]] = {}
    for key, rows in field_matrix.items():
        numeric_rows = []
        for row in rows:
            value = row.get("value")
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except Exception:
                continue
            numeric_rows.append({**row, "numeric": number})
        if numeric_rows:
            numeric_top3[key] = sorted(
                numeric_rows,
                key=lambda row: (-row["numeric"], row["number"]),
            )[:3]

    return {
        "valid": True,
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "all_entries": len(servers),
        "normal_servers": len(normal),
        "club_entries": len(servers) - len(normal),
        "all_server_keys": all_keys,
        "candidate_server_keys": candidate_keys,
        "candidate_field_matrix": field_matrix,
        "candidate_numeric_top3": numeric_top3,
        "normal_server_objects": safe_value(normal),
    }


def fetch_frontend(cookie: str) -> dict[str, Any]:
    play_response, play_route = common.get_with_fallback(
        BASE_URL + "/play", cookie, "text/html,application/xhtml+xml,*/*"
    )
    html = play_response.text
    scripts = common.extract_scripts(html, BASE_URL)
    script_rows = []
    source_texts: list[tuple[str, str]] = []
    for url in scripts:
        if "terms" in url.lower():
            continue
        try:
            response, route = common.get_with_fallback(url, "", "application/javascript,text/javascript,*/*")
            text = response.text
            if len(text.encode("utf-8", errors="replace")) > common.MAX_SCRIPT_BYTES:
                text = text[: common.MAX_SCRIPT_BYTES]
            source_texts.append((url, text))
            script_rows.append({
                "url": url,
                "status": response.status_code,
                "route": route,
                "bytes": len(text.encode("utf-8", errors="replace")),
            })
        except Exception as exc:
            script_rows.append({"url": url, "status": 0, "error": f"{type(exc).__name__}: {exc}"})

    combined = "\n".join(text for _, text in source_texts)
    quoted_keys = sorted(set(re.findall(r"[.\[](?:[\"']?)([A-Za-z_][A-Za-z0-9_]{2,60})", combined)))
    candidate_source_keys = [key for key in quoted_keys if CANDIDATE_RE.search(key)]
    api_paths = sorted(set(re.findall(r"[\"'`](/api/[A-Za-z0-9_?&=/${}.%:+\-]+)", combined)))
    relevant_api_paths = [
        path for path in api_paths
        if CANDIDATE_RE.search(path) or any(token in path for token in ("/api/servers", "/api/spectate/", "/api/world/chat"))
    ]
    contexts = {}
    for term in (
        "bossCaveActive", "bossCaveCapacity", "ember", "molten", "populationLabel",
        "onlineTotal", "spec_reg", "presencePlayerRegionKey", "presenceKeyFromGameState",
    ):
        contexts[term] = common.context_block(combined, re.escape(term), radius=900, max_items=20)

    return {
        "play_status": play_response.status_code,
        "play_route": play_route,
        "script_count": len(script_rows),
        "scripts": script_rows,
        "candidate_source_keys": candidate_source_keys,
        "relevant_api_paths": relevant_api_paths,
        "contexts": contexts,
    }


def write_summary(report: dict[str, Any]) -> str:
    main = report.get("main_authenticated") or {}
    analysis = report.get("main_analysis") or {}
    lines = [
        "KINTARA COME TO MOLTEN SERVER SURFACE PROBE",
        "=" * 92,
        f"Created: {report.get('created_at')}",
        f"Project root: {report.get('project_root')}",
        f"Cookie loaded: {report.get('cookie_present')}",
        "",
        "FULL /api/servers READ",
        "-" * 92,
        f"Authenticated status: {main.get('status', 0)} route={main.get('route', '-')}",
        f"All entries: {analysis.get('all_entries', 0)}",
        f"Normal servers: {analysis.get('normal_servers', 0)}",
        f"Club entries: {analysis.get('club_entries', 0)}",
        f"Top-level keys: {analysis.get('top_level_keys') or []}",
        f"All server keys: {analysis.get('all_server_keys') or []}",
        "",
        "COUNT / POPULATION CANDIDATE FIELDS",
        "-" * 92,
    ]
    candidates = analysis.get("candidate_server_keys") or []
    if not candidates:
        lines.append("No candidate server field was found.")
    else:
        for key in candidates:
            rows = (analysis.get("candidate_field_matrix") or {}).get(key) or []
            preview = ", ".join(f"{row['server']}={row['value']}" for row in rows[:8])
            lines.append(f"{key}: {preview}")

    lines.extend([
        "",
        "FANOUT ORIGIN READS",
        "-" * 92,
    ])
    for row in report.get("fanout_reads") or []:
        lines.append(f"{row.get('url')} status={row.get('status',0)} route={row.get('route','-')}")

    frontend = report.get("frontend") or {}
    lines.extend([
        "",
        "CURRENT CLIENT SOURCE",
        "-" * 92,
        f"Frontend scripts checked: {frontend.get('script_count', 0)}",
        f"Relevant official API paths: {frontend.get('relevant_api_paths') or []}",
        f"Candidate source keys: {frontend.get('candidate_source_keys') or []}",
        "",
        "RESULT",
        "-" * 92,
        "This report contains the complete current /api/servers objects, all candidate count fields,",
        "fanout /api/servers responses, and current official client references.",
        "No WebSocket, Presence session, movement, gameplay action, or browser automation was used.",
        "",
        f"Full report: {report.get('report_path')}",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    print("=" * 92)
    print("KINTARA COME TO MOLTEN SERVER SURFACE PROBE")
    print("=" * 92)
    print("This test reads the complete current server-list payload and official read-only fanout surfaces.")
    print("It opens no WebSocket, creates no Presence session, performs no game entry, and sends no action.")
    print("terms.html is never requested.")
    print("-" * 92)

    project_root = common.find_project_root()
    env_path = project_root / ".env"
    env = common.load_env(env_path)
    cookie = common.normalize_cookie(env)
    print(f"Project root: {project_root}")
    print(f"Cookie: {'loaded' if cookie else 'missing'}")
    if not cookie:
        print("KINTARA_EMBER_COOKIE or KINTARA_COOKIE was not found in .env")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "diagnostics" / f"ctm_server_surface_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    main_authenticated = fetch_json_url(BASE_URL + "/api/servers", cookie, send_cookie=True)
    main_anonymous = fetch_json_url(BASE_URL + "/api/servers", "", send_cookie=False)
    main_payload = main_authenticated.get("payload") or {}
    main_analysis = summarize_servers(main_payload)

    fanout_origins = sorted({
        str(row.get("fanoutOrigin") or "").rstrip("/")
        for row in (main_payload.get("servers") or [])
        if isinstance(row, dict) and str(row.get("fanoutOrigin") or "").strip()
    })
    fanout_reads = []
    for index, origin in enumerate(fanout_origins):
        if index:
            time.sleep(0.2)
        fanout_reads.append(fetch_json_url(origin + "/api/servers", "", send_cookie=False))

    frontend = fetch_frontend(cookie)

    report_path = output_dir / "server_surface_report.json"
    report = {
        "created_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "cookie_present": bool(cookie),
        "main_authenticated": main_authenticated,
        "main_anonymous": main_anonymous,
        "main_analysis": main_analysis,
        "fanout_reads": fanout_reads,
        "fanout_analyses": [summarize_servers(row.get("payload") or {}) for row in fanout_reads],
        "frontend": frontend,
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = write_summary(report)
    summary_path = output_dir / "summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Output folder: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
