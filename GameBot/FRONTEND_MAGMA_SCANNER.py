#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kintara frontend Magma definition scanner.

READ-ONLY:
- HTTP GET only
- No POST
- No WebSocket
- No gameplay action
- No movement, mining, attack or inventory operation

Scans:
- /play
- Same-origin JavaScript, CSS, JSON, manifest and source-map assets
- Static references discovered inside those files

Explicitly blocks:
- /terms
- terms.html
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


BASE = "https://kintara.gg"
ALLOWED_HOST = "kintara.gg"

WORK_DIR = Path(__file__).resolve().parent
ENV_FILE = WORK_DIR / ".env"

STAMP = time.strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = WORK_DIR / f"FRONTEND_MAGMA_SCAN_{STAMP}"
ASSETS_DIR = OUTPUT_DIR / "assets"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

MAX_ASSETS = 220
MAX_FILE_BYTES = 16 * 1024 * 1024
HTTP_TIMEOUT = 25
SNIPPET_RADIUS = 350
MAX_HITS_PER_FILE = 80

BLOCKED_PARTS = (
    "/terms",
    "terms.html",
)

STRONG_TERMS = (
    "molten_rock",
    "molten-rock",
    "molten rock",
    "magma",
    "lava",
    "volcano",
    "volcanic",
    "inferno",
    "hasmetal",
    "has_metal",
)

SUPPORTING_TERMS = (
    "molten",
    "igneous",
    "resourcegrid",
    "resource_grid",
    "mapbounds",
    "map_bounds",
    "biome",
    "worldbounds",
    "world_bounds",
)

TEXT_EXTENSIONS = {
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".json",
    ".map",
    ".txt",
    ".html",
    ".htm",
    ".webmanifest",
    ".manifest",
    ".svg",
}

STATIC_PATH_MARKERS = (
    "/_next/",
    "/static/",
    "/assets/",
    "/build/",
    "/dist/",
    "/chunks/",
    "/scripts/",
    "/js/",
    "/css/",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


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

    for raw_line in ENV_FILE.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines():

        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key.strip() != "KINTARA_COOKIE":
            continue

        cookie = unquote(value)

        if "=" not in cookie:
            raise RuntimeError(
                "KINTARA_COOKIE must contain the complete NAME=VALUE cookie."
            )

        return cookie

    raise RuntimeError("KINTARA_COOKIE was not found in .env")


COOKIE = load_cookie()


def blocked(value: str) -> bool:
    low = str(value or "").lower()
    return any(part in low for part in BLOCKED_PARTS)


def normalized_url(reference: str, parent_url: str = BASE + "/play") -> str | None:
    reference = html.unescape(str(reference or "").strip())

    if not reference:
        return None

    if reference.startswith((
        "data:",
        "blob:",
        "javascript:",
        "mailto:",
        "tel:",
        "#",
    )):
        return None

    url = urllib.parse.urljoin(parent_url, reference)
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https":
        return None

    if parsed.hostname != ALLOWED_HOST:
        return None

    if blocked(parsed.path):
        return None

    # Fragment does not affect the fetched resource.
    parsed = parsed._replace(fragment="")

    return urllib.parse.urlunparse(parsed)


def safe_get(url: str) -> tuple[int, bytes, str, str]:
    parsed = urllib.parse.urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or blocked(parsed.path)
    ):
        raise RuntimeError(f"Blocked URL: {url}")

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
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
        with opener.open(
            request,
            timeout=HTTP_TIMEOUT,
        ) as response:

            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    if int(content_length) > MAX_FILE_BYTES:
                        return (
                            int(response.status),
                            b"",
                            str(response.headers.get("Content-Type") or ""),
                            f"content_too_large:{content_length}",
                        )
                except Exception:
                    pass

            raw = response.read(MAX_FILE_BYTES + 1)

            if len(raw) > MAX_FILE_BYTES:
                return (
                    int(response.status),
                    b"",
                    str(response.headers.get("Content-Type") or ""),
                    "content_too_large",
                )

            return (
                int(response.status),
                raw,
                str(response.headers.get("Content-Type") or ""),
                "",
            )

    except urllib.error.HTTPError as exc:
        raw = exc.read(2000)

        return (
            int(exc.code),
            raw,
            str(exc.headers.get("Content-Type") or ""),
            f"http_error:{exc.code}",
        )

    except Exception as exc:
        return 0, b"", "", repr(exc)


def is_text_asset(url: str, content_type: str = "") -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    suffix = Path(path).suffix.lower()
    content_type = str(content_type or "").lower()

    if suffix in TEXT_EXTENSIONS:
        return True

    if any(marker in path for marker in STATIC_PATH_MARKERS):
        return True

    return any(marker in content_type for marker in (
        "javascript",
        "json",
        "text/",
        "xml",
        "svg",
    ))


def should_enqueue(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    suffix = Path(path).suffix.lower()

    if path.startswith("/api/"):
        # API strings are reported but never called by this scanner.
        return False

    if suffix in TEXT_EXTENSIONS:
        return True

    return any(marker in path for marker in STATIC_PATH_MARKERS)


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        values = {key.lower(): value for key, value in attrs}

        for attribute in ("src", "href"):
            value = values.get(attribute)

            if value:
                self.references.append(value)


QUOTED_PATH_RE = re.compile(
    r"""(?P<quote>["'])
    (?P<value>
        (?:https://kintara\.gg)?
        /
        [^"'\\\s]{1,500}
    )
    (?P=quote)""",
    re.IGNORECASE | re.VERBOSE,
)

IMPORT_RE = re.compile(
    r"""(?:import\s*\(\s*|from\s+|import\s+)
    ["']([^"']+)["']""",
    re.IGNORECASE,
)

SOURCE_MAP_RE = re.compile(
    r"""sourceMappingURL\s*=\s*([^\s*]+)""",
    re.IGNORECASE,
)

NEW_URL_RE = re.compile(
    r"""new\s+URL\(
        \s*["']([^"']+)["']
        \s*,\s*import\.meta\.url
    \s*\)""",
    re.IGNORECASE | re.VERBOSE,
)

API_PATH_RE = re.compile(
    r"""["'](
        /api/
        [^"'\\\s]{1,500}
    )["']""",
    re.IGNORECASE | re.VERBOSE,
)

WS_PATH_RE = re.compile(
    r"""["'](
        /ws/
        [^"'\\\s]{1,500}
    )["']""",
    re.IGNORECASE | re.VERBOSE,
)


def extract_references(text: str, parent_url: str) -> set[str]:
    references: set[str] = set()

    parser = ReferenceParser()

    try:
        parser.feed(text)
        references.update(parser.references)
    except Exception:
        pass

    for match in IMPORT_RE.finditer(text):
        references.add(match.group(1))

    for match in NEW_URL_RE.finditer(text):
        references.add(match.group(1))

    for match in SOURCE_MAP_RE.finditer(text):
        value = match.group(1).strip().strip('"').strip("'")

        if not value.startswith("data:"):
            references.add(value)

    for match in QUOTED_PATH_RE.finditer(text):
        references.add(match.group("value"))

    result: set[str] = set()

    for reference in references:
        url = normalized_url(reference, parent_url)

        if url and should_enqueue(url):
            result.add(url)

    return result


def asset_filename(url: str, content_type: str) -> str:
    parsed = urllib.parse.urlparse(url)
    original_name = Path(parsed.path).name or "index"

    original_name = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        original_name,
    )[:100]

    digest = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:14]

    suffix = Path(original_name).suffix

    if not suffix:
        if "json" in content_type.lower():
            suffix = ".json"
        elif "javascript" in content_type.lower():
            suffix = ".js"
        elif "css" in content_type.lower():
            suffix = ".css"
        else:
            suffix = ".txt"

        original_name += suffix

    return f"{digest}_{original_name}"


def find_term_hits(
    text: str,
    url: str,
    saved_file: str,
) -> list[dict[str, Any]]:

    low = text.lower()
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    terms = STRONG_TERMS + SUPPORTING_TERMS

    for term in terms:
        start = 0
        found_for_term = 0

        while found_for_term < MAX_HITS_PER_FILE:
            index = low.find(term, start)

            if index < 0:
                break

            signature = (term, index)

            if signature not in seen:
                seen.add(signature)

                left = max(0, index - SNIPPET_RADIUS)
                right = min(
                    len(text),
                    index + len(term) + SNIPPET_RADIUS,
                )

                snippet = text[left:right]
                snippet = snippet.replace("\r", " ").replace("\n", " ")

                hits.append({
                    "term": term,
                    "strong": term in STRONG_TERMS,
                    "url": url,
                    "saved_file": saved_file,
                    "offset": index,
                    "snippet": snippet,
                })

            found_for_term += 1
            start = index + max(1, len(term))

    return hits


def extract_reported_paths(text: str, source_url: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for category, pattern in (
        ("api", API_PATH_RE),
        ("websocket", WS_PATH_RE),
    ):
        for match in pattern.finditer(text):
            path = match.group(1)

            if blocked(path):
                continue

            rows.append({
                "category": category,
                "path": path,
                "source_url": source_url,
            })

    return rows


def main() -> None:
    print("=" * 74)
    print("KINTARA FRONTEND MAGMA SCANNER")
    print("=" * 74)
    print("Output:", OUTPUT_DIR)
    print("HTTP: GET only")
    print("WebSocket: NONE")
    print("Gameplay actions: NONE")
    print("/terms: BLOCKED")
    print("=" * 74)

    queue: deque[str] = deque()
    queue.append(BASE + "/play")

    queued: set[str] = {BASE + "/play"}
    fetched: set[str] = set()

    asset_index: list[dict[str, Any]] = []
    all_hits: list[dict[str, Any]] = []
    reported_paths: list[dict[str, str]] = []

    status_counts: Counter[int] = Counter()
    content_type_counts: Counter[str] = Counter()

    while queue and len(fetched) < MAX_ASSETS:
        url = queue.popleft()

        if url in fetched:
            continue

        fetched.add(url)

        status, raw, content_type, error = safe_get(url)

        status_counts[status] += 1
        content_type_counts[content_type] += 1

        print(
            f"[{len(fetched):03d}/{MAX_ASSETS}] "
            f"HTTP {status} | {len(raw):8d} bytes | {url}"
        )

        row: dict[str, Any] = {
            "url": url,
            "status": status,
            "bytes": len(raw),
            "content_type": content_type,
            "error": error,
            "saved_file": None,
            "new_references": 0,
            "strong_hits": 0,
            "supporting_hits": 0,
        }

        if status != 200 or not raw:
            asset_index.append(row)
            continue

        if not is_text_asset(url, content_type):
            row["error"] = "non_text_asset_skipped"
            asset_index.append(row)
            continue

        text = raw.decode(
            "utf-8",
            errors="replace",
        )

        filename = asset_filename(url, content_type)
        saved_path = ASSETS_DIR / filename

        saved_path.write_text(
            text,
            encoding="utf-8",
        )

        row["saved_file"] = str(saved_path.relative_to(OUTPUT_DIR))

        hits = find_term_hits(
            text,
            url,
            row["saved_file"],
        )

        all_hits.extend(hits)

        row["strong_hits"] = sum(
            1 for hit in hits if hit["strong"]
        )

        row["supporting_hits"] = sum(
            1 for hit in hits if not hit["strong"]
        )

        reported_paths.extend(
            extract_reported_paths(text, url)
        )

        references = extract_references(text, url)
        new_references = 0

        for reference_url in sorted(references):
            if reference_url in queued or reference_url in fetched:
                continue

            queued.add(reference_url)
            queue.append(reference_url)
            new_references += 1

        row["new_references"] = new_references
        asset_index.append(row)

    unique_paths: list[dict[str, str]] = []
    seen_paths: set[tuple[str, str]] = set()

    for row in reported_paths:
        signature = (
            row["category"],
            row["path"],
        )

        if signature in seen_paths:
            continue

        seen_paths.add(signature)
        unique_paths.append(row)

    strong_hits = [
        hit
        for hit in all_hits
        if hit["strong"]
    ]

    supporting_hits = [
        hit
        for hit in all_hits
        if not hit["strong"]
    ]

    (OUTPUT_DIR / "00_ASSET_INDEX.json").write_text(
        json.dumps(
            asset_index,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (OUTPUT_DIR / "01_STRONG_MAGMA_HITS.json").write_text(
        json.dumps(
            strong_hits,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (OUTPUT_DIR / "02_SUPPORTING_HITS.json").write_text(
        json.dumps(
            supporting_hits,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (OUTPUT_DIR / "03_REPORTED_API_WS_PATHS.json").write_text(
        json.dumps(
            unique_paths,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    term_counts = Counter(
        hit["term"]
        for hit in all_hits
    )

    files_with_strong_hits = Counter(
        hit["saved_file"]
        for hit in strong_hits
    )

    summary: list[str] = []

    summary.append("KINTARA FRONTEND MAGMA SCAN")
    summary.append("=" * 74)
    summary.append(f"Output directory: {OUTPUT_DIR}")
    summary.append(f"Fetched assets: {len(fetched)}")
    summary.append(f"Queued/discovered assets: {len(queued)}")
    summary.append(f"Strong Magma hits: {len(strong_hits)}")
    summary.append(f"Supporting hits: {len(supporting_hits)}")
    summary.append(f"Reported API/WS paths: {len(unique_paths)}")
    summary.append("")

    summary.append("HTTP STATUS COUNTS")
    summary.append("-" * 74)

    for status, count in status_counts.most_common():
        summary.append(f"{count:6d}  HTTP {status}")

    summary.append("")
    summary.append("TERM COUNTS")
    summary.append("-" * 74)

    if term_counts:
        for term, count in term_counts.most_common():
            summary.append(f"{count:6d}  {term}")
    else:
        summary.append("No target terms found.")

    summary.append("")
    summary.append("FILES WITH STRONG MAGMA HITS")
    summary.append("-" * 74)

    if files_with_strong_hits:
        for filename, count in files_with_strong_hits.most_common():
            summary.append(f"{count:6d}  {filename}")
    else:
        summary.append(
            "No molten_rock, magma, lava, volcano or hasMetal "
            "definition was found in downloaded frontend text assets."
        )

    summary.append("")
    summary.append("STRONG HIT PREVIEW")
    summary.append("-" * 74)

    if strong_hits:
        for hit in strong_hits[:80]:
            summary.append(
                f"[{hit['term']}] {hit['url']}"
            )
            summary.append(
                "  " + hit["snippet"][:700]
            )
            summary.append("")
    else:
        summary.append("No strong hit available.")

    summary.append("")
    summary.append("DISCOVERED API / WEBSOCKET PATHS")
    summary.append("-" * 74)

    for row in unique_paths[:150]:
        summary.append(
            f"{row['category']}: {row['path']}"
        )

    summary_path = OUTPUT_DIR / "04_SUMMARY.txt"

    summary_path.write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 74)
    print("SCAN COMPLETE")
    print("=" * 74)
    print("Fetched assets:", len(fetched))
    print("Strong Magma hits:", len(strong_hits))
    print("Supporting hits:", len(supporting_hits))
    print()
    print("Summary:")
    print(summary_path)
    print()
    print("Strong-hit JSON:")
    print(OUTPUT_DIR / "01_STRONG_MAGMA_HITS.json")
    print("=" * 74)


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

        print("FATAL:", exc)
        print("Saved:", fatal)
        raise
