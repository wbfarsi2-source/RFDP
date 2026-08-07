from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError as exc:
    raise SystemExit("Missing dependency: httpx. Run with the project virtual environment.") from exc

BASE_DEFAULT = "https://kintara.gg"
MAX_SCRIPT_BYTES = 8 * 1024 * 1024
REQUEST_DELAY_MIN_SECONDS = 0.18
REQUEST_DELAY_MAX_SECONDS = 0.38
TARGET_PATTERNS = (
    "worldChatRegionKey",
    "sendSpectatorRegionUpdate",
    "spec_reg",
    "enterEmber",
    "leaveEmber",
    "gameState===\"ember\"",
    "gameState==\"ember\"",
    "case\"ember\"",
    "emberstone",
)


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


def same_origin_scripts(html: str, page_url: str, base_url: str) -> list[str]:
    scripts: list[str] = []
    base_host = urlparse(base_url).netloc
    for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        url = urljoin(page_url, match.group(1))
        parsed = urlparse(url)
        if parsed.netloc != base_host:
            continue
        if "terms" in parsed.path.lower():
            continue
        if url not in scripts:
            scripts.append(url)
    return scripts


def compact(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")


def context_snippets(text: str, pattern: str, radius: int = 2400, limit: int = 20) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    lower = text.lower()
    needle = pattern.lower()
    cursor = 0
    while len(output) < limit:
        index = lower.find(needle, cursor)
        if index < 0:
            break
        left = max(0, index - radius)
        right = min(len(text), index + len(pattern) + radius)
        output.append({
            "pattern": pattern,
            "index": index,
            "snippet": compact(text[left:right]),
        })
        cursor = index + max(1, len(pattern))
    return output


def extract_balanced_method(text: str, name: str) -> list[str]:
    blocks: list[str] = []
    cursor = 0
    while True:
        index = text.find(name, cursor)
        if index < 0:
            break
        brace = text.find("{", index, min(len(text), index + 500))
        if brace < 0:
            cursor = index + len(name)
            continue

        depth = 0
        quote = ""
        escaped = False
        line_comment = False
        block_comment = False
        end = None
        i = brace
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""

            if line_comment:
                if ch in "\r\n":
                    line_comment = False
                i += 1
                continue
            if block_comment:
                if ch == "*" and nxt == "/":
                    block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = ""
                i += 1
                continue

            if ch == "/" and nxt == "/":
                line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                block_comment = True
                i += 2
                continue
            if ch in ("'", '"', "`"):
                quote = ch
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1

        if end is not None:
            start = max(0, index - 250)
            block = compact(text[start:end])
            if block not in blocks:
                blocks.append(block)
        cursor = index + len(name)
    return blocks[:10]


def string_candidates(blocks: list[str]) -> list[str]:
    values: set[str] = set()
    for block in blocks:
        for match in re.finditer(r"[\"']([a-zA-Z0-9_\-]{2,40})[\"']", block):
            value = match.group(1)
            low = value.lower()
            if any(token in low for token in ("ember", "world", "wild", "arena", "mine", "pond", "shore")):
                values.add(value)
    return sorted(values)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_project_root(script_dir)
    load_env(root / ".env")
    base_url = os.environ.get("KINTARA_BASE_URL", BASE_DEFAULT).strip().rstrip("/") or BASE_DEFAULT
    cookie = os.environ.get("KINTARA_COOKIE", "").strip()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = root / "diagnostics" / f"ctm_region_key_probe_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
        "Accept": "text/html,application/javascript,text/javascript,*/*",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie

    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "base_url": base_url,
        "cookie_present": bool(cookie),
        "pages": [],
        "scripts": [],
        "world_chat_region_key_blocks": [],
        "spectator_update_blocks": [],
        "matches": [],
        "candidate_region_strings": [],
    }

    print("=" * 78)
    print("KINTARA COME TO MOLTEN REGION KEY PROBE")
    print("=" * 78)
    print("Read-only frontend inspection. No WebSocket or gameplay action is sent.")
    print("The terms page is never requested.")
    print(f"Output: {out_dir}")
    print("-" * 78)

    script_urls: list[str] = []
    with httpx.Client(headers=headers, trust_env=True, follow_redirects=True, timeout=25) as client:
        for path in ("/", "/play"):
            url = base_url + path
            response = client.get(url)
            report["pages"].append({"url": url, "status": response.status_code, "bytes": len(response.content)})
            if response.status_code == 200:
                for item in same_origin_scripts(response.text, url, base_url):
                    if item not in script_urls:
                        script_urls.append(item)
            time.sleep(random.uniform(REQUEST_DELAY_MIN_SECONDS, REQUEST_DELAY_MAX_SECONDS))

        for index, url in enumerate(script_urls, 1):
            print(f"[{index}/{len(script_urls)}] {url}")
            try:
                response = client.get(url)
                content = response.content[:MAX_SCRIPT_BYTES]
                text = content.decode("utf-8", errors="replace")
                script_row = {
                    "url": url,
                    "status": response.status_code,
                    "bytes": len(content),
                    "contains_worldChatRegionKey": "worldChatRegionKey" in text,
                    "contains_spec_reg": "spec_reg" in text,
                }
                report["scripts"].append(script_row)
                if response.status_code != 200:
                    continue

                if "worldChatRegionKey" in text:
                    report["world_chat_region_key_blocks"].extend(
                        {"url": url, "block": block}
                        for block in extract_balanced_method(text, "worldChatRegionKey")
                    )
                if "sendSpectatorRegionUpdate" in text:
                    report["spectator_update_blocks"].extend(
                        {"url": url, "block": block}
                        for block in extract_balanced_method(text, "sendSpectatorRegionUpdate")
                    )

                for pattern in TARGET_PATTERNS:
                    for row in context_snippets(text, pattern):
                        row["url"] = url
                        report["matches"].append(row)
            except Exception as exc:
                report["scripts"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            time.sleep(random.uniform(REQUEST_DELAY_MIN_SECONDS, REQUEST_DELAY_MAX_SECONDS))

    candidate_blocks = [row["block"] for row in report["world_chat_region_key_blocks"]]
    candidate_blocks += [row["snippet"] for row in report["matches"] if row["pattern"] == "worldChatRegionKey"]
    report["candidate_region_strings"] = string_candidates(candidate_blocks)

    report_path = out_dir / "region_key_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary: list[str] = [
        "KINTARA COME TO MOLTEN REGION KEY PROBE",
        "=" * 78,
        f"Created: {report['created_at']}",
        f"Scripts checked: {len(report['scripts'])}",
        f"worldChatRegionKey blocks: {len(report['world_chat_region_key_blocks'])}",
        f"Spectator update blocks: {len(report['spectator_update_blocks'])}",
        f"Candidate region strings: {', '.join(report['candidate_region_strings']) or '-'}",
        "",
        "WORLD CHAT REGION KEY BLOCKS",
        "-" * 78,
    ]
    if report["world_chat_region_key_blocks"]:
        for index, row in enumerate(report["world_chat_region_key_blocks"], 1):
            summary.append(f"[{index}] {row['url']}")
            summary.append(row["block"])
            summary.append("")
    else:
        summary.append("No balanced method block was extracted. Use the JSON context matches.")

    summary_path = out_dir / "summary.txt"
    summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")

    print("Completed.")
    print(f"Send: {summary_path}")
    print(f"Send: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
