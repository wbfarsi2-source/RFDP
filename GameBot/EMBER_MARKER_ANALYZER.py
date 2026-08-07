#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Offline Ember/Magma marker analyzer.

Network: NONE
HTTP: NONE
WebSocket: NONE
Gameplay action: NONE

Reads:
- Latest FRONTEND_MAGMA_SCAN_* downloaded game JavaScript
- Latest MAGMA_RAW_TEST_* captured Presence frames

Finds:
- Every meaningful occurrence of the internal identifier "ember"
- Nearby coordinate/fishing fields: x, y, z, ry, fc, fr, fph, region
- Presence players carrying fishing-related fields
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WORK_DIR = Path(__file__).resolve().parent

STAMP = time.strftime("%Y%m%d_%H%M%S")

TEXT_OUTPUT = WORK_DIR / f"EMBER_MARKER_ANALYSIS_{STAMP}.txt"
JSON_OUTPUT = WORK_DIR / f"EMBER_MARKER_ANALYSIS_{STAMP}.json"

SNIPPET_RADIUS = 2600
MAX_SNIPPETS = 100

FISH_FIELDS = (
    "fc",
    "fr",
    "fph",
)

POSITION_FIELDS = (
    "x",
    "y",
    "z",
    "ry",
)

REGION_FIELDS = (
    "region",
    "pr",
    "zone",
    "map",
    "biome",
)

INTERESTING_PLAYER_FIELDS = set(
    FISH_FIELDS
    + POSITION_FIELDS
    + REGION_FIELDS
    + (
        "id",
        "act",
        "eq",
        "mov",
    )
)

FIELD_PATTERN = re.compile(
    r"""
    (?P<key>
        region|zone|map|biome|
        x|y|z|ry|
        fc|fr|fph
    )
    \s*:\s*
    (?P<value>
        "(?:\\.|[^"])*"
        |
        '(?:\\.|[^'])*'
        |
        -?\d+(?:\.\d+)?
        |
        true|false|null
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def newest_directory(pattern: str, required_child: str | None = None) -> Path:
    candidates = []

    for path in WORK_DIR.glob(pattern):
        if not path.is_dir():
            continue

        if required_child and not (path / required_child).exists():
            continue

        candidates.append(path)

    if not candidates:
        raise RuntimeError(
            f"No directory matching {pattern} found in {WORK_DIR}"
        )

    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def newest_game_js(frontend_dir: Path) -> Path:
    assets_dir = frontend_dir / "assets"

    candidates = [
        path
        for path in assets_dir.glob("*game*.js")
        if path.is_file()
    ]

    if not candidates:
        candidates = [
            path
            for path in assets_dir.glob("*.js")
            if path.is_file()
        ]

    if not candidates:
        raise RuntimeError(
            f"No JavaScript file found in {assets_dir}"
        )

    return max(
        candidates,
        key=lambda path: path.stat().st_size,
    )


def clean_snippet(value: str) -> str:
    return (
        value
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )


def extract_fields(snippet: str) -> list[dict[str, str]]:
    results = []
    seen = set()

    for match in FIELD_PATTERN.finditer(snippet):
        key = match.group("key")
        value = match.group("value")

        signature = (key.lower(), value)

        if signature in seen:
            continue

        seen.add(signature)

        results.append({
            "key": key,
            "value": value,
        })

    return results


def analyze_javascript(game_js: Path) -> dict[str, Any]:
    text = game_js.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    low = text.lower()

    occurrences = []

    start = 0

    while len(occurrences) < MAX_SNIPPETS:
        index = low.find("ember", start)

        if index < 0:
            break

        left = max(0, index - SNIPPET_RADIUS)
        right = min(
            len(text),
            index + len("ember") + SNIPPET_RADIUS,
        )

        snippet = clean_snippet(text[left:right])

        markers = sorted({
            marker
            for marker in (
                "molten_rock",
                "molten rock",
                "lava",
                "tickpondfishing",
                "region",
                "fc",
                "fr",
                "fph",
                "fish",
                "pond",
            )
            if marker in snippet.lower()
        })

        occurrences.append({
            "offset": index,
            "markers": markers,
            "fields": extract_fields(snippet),
            "snippet": snippet,
        })

        start = index + len("ember")

    important = [
        row
        for row in occurrences
        if any(
            marker in row["markers"]
            for marker in (
                "molten_rock",
                "molten rock",
                "lava",
                "tickpondfishing",
                "fc",
                "fr",
                "fph",
                "region",
            )
        )
    ]

    exact_patterns = {
        '"ember"': text.count('"ember"'),
        "'ember'": text.count("'ember'"),
        '==="ember"': text.count('==="ember"'),
        'region:"ember"': text.count('region:"ember"'),
        "region:'ember'": text.count("region:'ember'"),
        'region: "ember"': text.count('region: "ember"'),
    }

    return {
        "game_js": str(game_js),
        "game_js_bytes": game_js.stat().st_size,
        "total_ember_occurrences": len(occurrences),
        "important_occurrences": len(important),
        "exact_patterns": exact_patterns,
        "occurrences": occurrences,
        "important": important,
    }


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def player_is_fishing_related(player: dict[str, Any]) -> bool:
    if any(field in player for field in FISH_FIELDS):
        return True

    action = str(player.get("act") or "").lower()
    equipment = str(player.get("eq") or "").lower()
    region = str(
        player.get("region")
        or player.get("pr")
        or ""
    ).lower()

    if "fish" in action:
        return True

    if "fishing" in equipment:
        return True

    if region == "ember":
        return True

    return False


def player_signature(player: dict[str, Any]) -> str:
    selected = {}

    for key in sorted(INTERESTING_PLAYER_FIELDS):
        if key in player:
            selected[key] = normalize_scalar(player.get(key))

    return json.dumps(
        selected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def analyze_presence(capture_dir: Path) -> dict[str, Any]:
    frames_dir = capture_dir / "frames"

    player_key_counts: Counter[str] = Counter()
    fishing_signatures: Counter[str] = Counter()
    fishing_by_server: Counter[str] = Counter()
    max_fishing_by_server: Counter[str] = Counter()

    field_values: dict[str, Counter[str]] = defaultdict(Counter)
    samples = []

    total_snapshots = 0
    total_player_rows = 0
    fishing_player_rows = 0

    for frame_file in sorted(frames_dir.glob("*.jsonl")):
        server = frame_file.stem

        with frame_file.open(
            "r",
            encoding="utf-8",
            errors="ignore",
        ) as handle:

            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    row = json.loads(line)
                except Exception:
                    continue

                frame = (
                    row.get("frame")
                    if isinstance(row, dict) and "frame" in row
                    else row
                )

                if not isinstance(frame, dict):
                    continue

                if str(frame.get("t") or "") != "snap":
                    continue

                players = frame.get("players")

                if not isinstance(players, list):
                    continue

                total_snapshots += 1
                snapshot_fishing_count = 0

                for player in players:
                    if not isinstance(player, dict):
                        continue

                    total_player_rows += 1

                    for key in player:
                        player_key_counts[str(key)] += 1

                    for field in (
                        "fc",
                        "fr",
                        "fph",
                        "region",
                        "pr",
                        "act",
                        "eq",
                        "x",
                        "y",
                        "z",
                    ):
                        if field in player:
                            field_values[field][
                                str(normalize_scalar(player.get(field)))
                            ] += 1

                    if not player_is_fishing_related(player):
                        continue

                    fishing_player_rows += 1
                    snapshot_fishing_count += 1
                    fishing_by_server[server] += 1

                    signature = player_signature(player)
                    fishing_signatures[signature] += 1

                    if len(samples) < 300:
                        samples.append({
                            "server": server,
                            "line": line_number,
                            "player": {
                                key: normalize_scalar(player.get(key))
                                for key in sorted(INTERESTING_PLAYER_FIELDS)
                                if key in player
                            },
                        })

                max_fishing_by_server[server] = max(
                    max_fishing_by_server[server],
                    snapshot_fishing_count,
                )

    return {
        "capture_directory": str(capture_dir),
        "total_snapshots": total_snapshots,
        "total_player_rows": total_player_rows,
        "fishing_player_rows": fishing_player_rows,
        "player_key_counts": dict(
            player_key_counts.most_common()
        ),
        "field_values": {
            field: dict(counter.most_common(100))
            for field, counter in field_values.items()
        },
        "fishing_signatures": [
            {
                "count": count,
                "signature": json.loads(signature),
            }
            for signature, count
            in fishing_signatures.most_common(200)
        ],
        "fishing_rows_by_server": dict(
            fishing_by_server.most_common()
        ),
        "maximum_fishing_players_per_snapshot": dict(
            max_fishing_by_server.most_common()
        ),
        "samples": samples,
    }


def build_text_report(
    frontend_dir: Path,
    capture_dir: Path,
    js_report: dict[str, Any],
    presence_report: dict[str, Any],
) -> str:

    lines = []

    lines.append("KINTARA EMBER / MAGMA MARKER ANALYSIS")
    lines.append("=" * 78)
    lines.append(f"Frontend scan: {frontend_dir}")
    lines.append(f"Presence capture: {capture_dir}")
    lines.append(f"Game JS: {js_report['game_js']}")
    lines.append("")
    lines.append("NETWORK ACTIVITY: NONE")
    lines.append("")

    lines.append("EMBER JAVASCRIPT RESULTS")
    lines.append("-" * 78)
    lines.append(
        f"Total ember occurrences: "
        f"{js_report['total_ember_occurrences']}"
    )
    lines.append(
        f"Important ember occurrences: "
        f"{js_report['important_occurrences']}"
    )

    for pattern, count in js_report["exact_patterns"].items():
        lines.append(f"{count:6d}  {pattern}")

    lines.append("")
    lines.append("IMPORTANT EMBER SNIPPETS")
    lines.append("-" * 78)

    important = js_report["important"]

    if not important:
        lines.append("No important Ember snippet found.")

    for index, row in enumerate(important, start=1):
        lines.append("")
        lines.append(
            f"[EMBER {index}] offset={row['offset']} "
            f"markers={','.join(row['markers'])}"
        )

        if row["fields"]:
            lines.append(
                "Fields: "
                + json.dumps(
                    row["fields"],
                    ensure_ascii=False,
                )
            )

        lines.append(row["snippet"])

    lines.append("")
    lines.append("PRESENCE PLAYER FIELDS")
    lines.append("-" * 78)

    player_keys = presence_report["player_key_counts"]

    for key in (
        "fc",
        "fr",
        "fph",
        "region",
        "pr",
        "act",
        "eq",
        "x",
        "y",
        "z",
    ):
        lines.append(
            f"{key}: {player_keys.get(key, 0)} occurrences"
        )

    lines.append("")
    lines.append("MAXIMUM FISHING-RELATED PLAYERS PER SERVER")
    lines.append("-" * 78)

    maximums = presence_report[
        "maximum_fishing_players_per_snapshot"
    ]

    if not maximums:
        lines.append(
            "No player with fc/fr/fph, fishing action, "
            "fishing rod or region=ember was found."
        )

    for server, count in maximums.items():
        lines.append(f"{server}: {count}")

    lines.append("")
    lines.append("FISHING / EMBER PLAYER SIGNATURES")
    lines.append("-" * 78)

    signatures = presence_report["fishing_signatures"]

    if not signatures:
        lines.append("No fishing-related signature found.")

    for row in signatures[:100]:
        lines.append(
            f"{row['count']:7d}  "
            + json.dumps(
                row["signature"],
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    lines.append("")
    lines.append("FIELD VALUES")
    lines.append("-" * 78)

    for field in (
        "fc",
        "fr",
        "fph",
        "region",
        "pr",
        "act",
        "eq",
    ):
        values = presence_report["field_values"].get(field, {})

        lines.append("")
        lines.append(f"[{field}]")

        if not values:
            lines.append("No values.")

        for value, count in list(values.items())[:50]:
            lines.append(f"{count:7d}  {value}")

    return "\n".join(lines) + "\n"


def main() -> None:
    frontend_dir = newest_directory(
        "FRONTEND_MAGMA_SCAN_*",
        required_child="assets",
    )

    capture_dir = newest_directory(
        "MAGMA_RAW_TEST_*",
        required_child="frames",
    )

    game_js = newest_game_js(frontend_dir)

    print("=" * 78)
    print("KINTARA EMBER MARKER ANALYZER")
    print("=" * 78)
    print("Frontend:", frontend_dir)
    print("Capture :", capture_dir)
    print("Game JS :", game_js)
    print("Network : NONE")
    print("=" * 78)

    js_report = analyze_javascript(game_js)
    presence_report = analyze_presence(capture_dir)

    report = {
        "frontend_directory": str(frontend_dir),
        "capture_directory": str(capture_dir),
        "javascript": js_report,
        "presence": presence_report,
    }

    JSON_OUTPUT.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    text_report = build_text_report(
        frontend_dir,
        capture_dir,
        js_report,
        presence_report,
    )

    TEXT_OUTPUT.write_text(
        text_report,
        encoding="utf-8",
    )

    print()
    print("ANALYSIS COMPLETE")
    print()
    print("Text report:")
    print(TEXT_OUTPUT)
    print()
    print("JSON report:")
    print(JSON_OUTPUT)
    print()
    print("=" * 78)
    print(text_report)


if __name__ == "__main__":
    main()
