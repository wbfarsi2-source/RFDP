#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Offline analyzer for previously captured Kintara Presence frames.

This script:
- Makes NO HTTP request
- Opens NO WebSocket
- Sends NOTHING to the game
- Only reads the newest MAGMA_RAW_TEST_* directory
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WORK_DIR = Path(__file__).resolve().parent

MAGMA_WORDS = (
    "magma",
    "molten",
    "molten_rock",
    "lava",
    "volcano",
    "volcanic",
    "inferno",
    "igneous",
)

FRAME_TYPES_OF_INTEREST = {
    "snap",
    "res_evt",
    "online_total",
    "wild_bg",
    "wild_bg_rm",
    "mp_rsv",
}

LOCATION_KEYS = {
    "region",
    "regionname",
    "regionid",
    "zone",
    "zonename",
    "zoneid",
    "map",
    "mapname",
    "mapid",
    "area",
    "areaname",
    "areaid",
    "biome",
    "world",
    "worldid",
    "location",
    "locationid",
    "scene",
    "sceneid",
    "room",
    "roomid",
    "realm",
    "dimension",
    "instance",
    "instanceid",
    "place",
    "placeid",
    "loc",
    "reg",
    "rg",
    "zn",
}

PLAYER_ID_KEYS = {
    "playerid",
    "userid",
    "accountid",
    "characterid",
    "sessionid",
    "uid",
    "pid",
}

PLAYER_NAME_KEYS = {
    "username",
    "playername",
    "displayname",
    "nickname",
}

MAX_SAMPLES_PER_TYPE_PER_SERVER = 3
MAX_EXACT_HITS = 1000
MAX_EXAMPLES_PER_PATH = 12
MAX_LIST_ITEMS_TO_WALK = 100


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def short_value(value: Any, limit: int = 220) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        except Exception:
            text = repr(value)

    text = text.replace("\r", " ").replace("\n", " ")

    if len(text) > limit:
        return text[:limit] + "..."

    return text


def contains_magma(value: Any) -> list[str]:
    text = str(value or "").lower()

    return sorted({
        word
        for word in MAGMA_WORDS
        if word in text
    })


def frame_type(frame: Any) -> str:
    if not isinstance(frame, dict):
        return type(frame).__name__

    for key in ("t", "type", "event", "op", "action", "kind"):
        if key in frame:
            return str(frame.get(key) or "").lower()

    return "dict_without_type"


def newest_capture_directory() -> Path:
    directories = [
        path
        for path in WORK_DIR.glob("MAGMA_RAW_TEST_*")
        if path.is_dir() and (path / "frames").is_dir()
    ]

    if not directories:
        raise RuntimeError(
            f"No MAGMA_RAW_TEST_* directory found in {WORK_DIR}"
        )

    return max(
        directories,
        key=lambda path: path.stat().st_mtime,
    )


CAPTURE_DIR = newest_capture_directory()
FRAMES_DIR = CAPTURE_DIR / "frames"

TYPE_COUNTS: Counter[str] = Counter()
SERVER_TYPE_COUNTS: dict[str, Counter[str]] = defaultdict(Counter)

TOP_LEVEL_KEYS: dict[str, Counter[str]] = defaultdict(Counter)
PATH_TYPES: dict[str, Counter[str]] = defaultdict(Counter)
PATH_EXAMPLES: dict[str, list[str]] = defaultdict(list)
LIST_LENGTHS: dict[str, Counter[int]] = defaultdict(Counter)

LOCATION_VALUES: dict[str, Counter[str]] = defaultdict(Counter)
SHORT_KEY_VALUES: dict[str, Counter[str]] = defaultdict(Counter)

DICT_SHAPES: Counter[str] = Counter()

EXACT_MAGMA_HITS: list[dict[str, Any]] = []

SAMPLES: dict[str, dict[str, list[Any]]] = defaultdict(
    lambda: defaultdict(list)
)

FRAME_COUNT = 0


def add_example(path: str, value: Any) -> None:
    rendered = short_value(value)

    examples = PATH_EXAMPLES[path]

    if rendered in examples:
        return

    if len(examples) < MAX_EXAMPLES_PER_PATH:
        examples.append(rendered)


def is_location_key(key: Any) -> bool:
    normalized = normalize_key(key)

    if normalized in LOCATION_KEYS:
        return True

    endings = (
        "region",
        "regionid",
        "zone",
        "zoneid",
        "map",
        "mapid",
        "biome",
        "location",
        "locationid",
        "scene",
        "sceneid",
        "area",
        "areaid",
        "world",
        "worldid",
        "room",
        "roomid",
    )

    return normalized.endswith(endings)


def record_exact_hit(
    server: str,
    current_type: str,
    path: str,
    key: Any,
    value: Any,
    matched: list[str],
) -> None:
    if not matched:
        return

    if len(EXACT_MAGMA_HITS) >= MAX_EXACT_HITS:
        return

    EXACT_MAGMA_HITS.append({
        "server": server,
        "frame_type": current_type,
        "path": path,
        "key": str(key),
        "matched": matched,
        "value": short_value(value, 500),
    })


def walk(
    node: Any,
    server: str,
    current_type: str,
    path: str = "$",
    depth: int = 0,
) -> None:
    if depth > 20:
        return

    type_name = type(node).__name__
    PATH_TYPES[path][type_name] += 1

    if isinstance(node, dict):
        keys = sorted(str(key) for key in node.keys())

        shape_key = (
            f"type={current_type} | "
            f"path={path} | "
            f"keys={','.join(keys[:40])}"
        )

        DICT_SHAPES[shape_key] += 1

        for key, value in node.items():
            key_text = str(key)
            normalized = normalize_key(key)
            child_path = f"{path}.{key_text}"

            key_matches = contains_magma(key_text)

            if key_matches:
                record_exact_hit(
                    server,
                    current_type,
                    child_path,
                    key,
                    value,
                    key_matches,
                )

            if isinstance(value, (str, int, float, bool)) or value is None:
                add_example(child_path, value)

                value_matches = contains_magma(value)

                if value_matches:
                    record_exact_hit(
                        server,
                        current_type,
                        child_path,
                        key,
                        value,
                        value_matches,
                    )

                if is_location_key(key):
                    LOCATION_VALUES[
                        f"{current_type} | {child_path}"
                    ][short_value(value)] += 1

                # Short/abbreviated protocol keys are important because
                # Presence payloads may use keys such as r, rg, z, m, loc.
                if len(normalized) <= 3:
                    SHORT_KEY_VALUES[
                        f"{current_type} | {child_path}"
                    ][short_value(value)] += 1

            walk(
                value,
                server,
                current_type,
                child_path,
                depth + 1,
            )

    elif isinstance(node, list):
        LIST_LENGTHS[
            f"{current_type} | {path}"
        ][len(node)] += 1

        for index, child in enumerate(
            node[:MAX_LIST_ITEMS_TO_WALK]
        ):
            walk(
                child,
                server,
                current_type,
                f"{path}[]",
                depth + 1,
            )


for frame_file in sorted(FRAMES_DIR.glob("*.jsonl")):
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

            current_type = frame_type(frame)

            FRAME_COUNT += 1
            TYPE_COUNTS[current_type] += 1
            SERVER_TYPE_COUNTS[server][current_type] += 1

            if isinstance(frame, dict):
                for key in frame:
                    TOP_LEVEL_KEYS[current_type][str(key)] += 1

            if (
                current_type in FRAME_TYPES_OF_INTEREST
                and len(SAMPLES[server][current_type])
                < MAX_SAMPLES_PER_TYPE_PER_SERVER
            ):
                SAMPLES[server][current_type].append({
                    "source_file": frame_file.name,
                    "line_number": line_number,
                    "frame": frame,
                })

            walk(
                frame,
                server,
                current_type,
            )


focused_paths = []

for path, type_counter in PATH_TYPES.items():
    low = path.lower()

    if any(word in low for word in (
        "player",
        "user",
        "region",
        "zone",
        "map",
        "location",
        "scene",
        "area",
        "world",
        "room",
        "coord",
        ".x",
        ".y",
        ".z",
        ".r",
        ".rg",
        ".pid",
        ".uid",
    )):
        focused_paths.append({
            "path": path,
            "types": dict(type_counter.most_common()),
            "examples": PATH_EXAMPLES.get(path, []),
        })


json_report = {
    "capture_directory": str(CAPTURE_DIR),
    "total_frames": FRAME_COUNT,
    "frame_types": dict(TYPE_COUNTS.most_common()),
    "server_frame_types": {
        server: dict(counts.most_common())
        for server, counts in sorted(SERVER_TYPE_COUNTS.items())
    },
    "top_level_keys_by_frame_type": {
        current_type: dict(counter.most_common())
        for current_type, counter in TOP_LEVEL_KEYS.items()
    },
    "location_values": {
        path: dict(counter.most_common(50))
        for path, counter in LOCATION_VALUES.items()
    },
    "short_protocol_key_values": {
        path: dict(counter.most_common(30))
        for path, counter in SHORT_KEY_VALUES.items()
    },
    "list_lengths": {
        path: dict(counter.most_common(20))
        for path, counter in LIST_LENGTHS.items()
    },
    "focused_paths": focused_paths,
    "common_dictionary_shapes": [
        {
            "count": count,
            "shape": shape,
        }
        for shape, count in DICT_SHAPES.most_common(200)
    ],
    "exact_magma_hits": EXACT_MAGMA_HITS,
}

REPORT_JSON = CAPTURE_DIR / "09_FOCUSED_SCHEMA_REPORT.json"
SAMPLES_JSON = CAPTURE_DIR / "10_SNAP_RES_EVT_SAMPLES.json"
HITS_JSON = CAPTURE_DIR / "11_EXACT_MAGMA_HITS.json"
REPORT_TXT = CAPTURE_DIR / "12_FOCUSED_SUMMARY.txt"

REPORT_JSON.write_text(
    json.dumps(
        json_report,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)

SAMPLES_JSON.write_text(
    json.dumps(
        SAMPLES,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)

HITS_JSON.write_text(
    json.dumps(
        EXACT_MAGMA_HITS,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)


summary = []

summary.append("KINTARA FOCUSED MAGMA CAPTURE ANALYSIS")
summary.append("=" * 70)
summary.append(f"Capture directory: {CAPTURE_DIR}")
summary.append(f"Total frames: {FRAME_COUNT}")
summary.append(f"Exact magma/molten/lava hits: {len(EXACT_MAGMA_HITS)}")
summary.append("")

summary.append("FRAME TYPES")
for name, count in TYPE_COUNTS.most_common(30):
    summary.append(f"{count:8d}  {name}")

summary.append("")
summary.append("TOP-LEVEL KEYS")

for current_type in (
    "snap",
    "res_evt",
    "online_total",
    "wild_bg",
    "wild_bg_rm",
    "mp_rsv",
):
    counter = TOP_LEVEL_KEYS.get(current_type)

    if not counter:
        continue

    summary.append("")
    summary.append(f"[{current_type}]")

    for key, count in counter.most_common(50):
        summary.append(f"{count:8d}  {key}")

summary.append("")
summary.append("LOCATION / MAP FIELD VALUES")

if LOCATION_VALUES:
    for path, counter in sorted(LOCATION_VALUES.items()):
        summary.append("")
        summary.append(path)

        for value, count in counter.most_common(20):
            summary.append(f"{count:8d}  {value}")
else:
    summary.append("No obvious long-form location field was detected.")

summary.append("")
summary.append("SHORT PROTOCOL KEYS")

for path, counter in sorted(SHORT_KEY_VALUES.items()):
    if sum(counter.values()) < 2:
        continue

    summary.append("")
    summary.append(path)

    for value, count in counter.most_common(12):
        summary.append(f"{count:8d}  {value}")

summary.append("")
summary.append("EXACT MAGMA HITS")

if EXACT_MAGMA_HITS:
    for hit in EXACT_MAGMA_HITS[:100]:
        summary.append(
            f"{hit['server']} | "
            f"{hit['frame_type']} | "
            f"{hit['path']} | "
            f"{','.join(hit['matched'])} | "
            f"{hit['value']}"
        )
else:
    summary.append(
        "No exact magma/molten/lava text exists in the captured Presence frames."
    )
    summary.append(
        "This likely means the map is represented by coordinates, numeric IDs,"
    )
    summary.append(
        "or an abbreviated protocol field rather than the literal word 'magma'."
    )

REPORT_TXT.write_text(
    "\n".join(summary) + "\n",
    encoding="utf-8",
)

print()
print("=" * 70)
print("OFFLINE ANALYSIS COMPLETE")
print("=" * 70)
print("Capture:", CAPTURE_DIR)
print("Frames :", FRAME_COUNT)
print("Exact magma-related hits:", len(EXACT_MAGMA_HITS))
print()
print("Created:")
print(REPORT_TXT)
print(REPORT_JSON)
print(SAMPLES_JSON)
print(HITS_JSON)
print()
print("Display focused summary with:")
print(f'cat "{REPORT_TXT}"')
print("=" * 70)
