#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Offline resource/coordinate analyzer.

Network activity: NONE
HTTP requests: NONE
WebSocket: NONE
Gameplay actions: NONE

It reads the newest MAGMA_RAW_TEST_* capture and correlates:
- res_evt.kind / keys / loot
- actor player ID in res_evt.by
- latest player x/y/z coordinates from snap frames
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WORK_DIR = Path(__file__).resolve().parent


def newest_capture() -> Path:
    candidates = [
        path
        for path in WORK_DIR.glob("MAGMA_RAW_TEST_*")
        if path.is_dir() and (path / "frames").is_dir()
    ]

    if not candidates:
        raise RuntimeError(
            f"No MAGMA_RAW_TEST_* directory found in {WORK_DIR}"
        )

    return max(candidates, key=lambda path: path.stat().st_mtime)


CAPTURE_DIR = newest_capture()
FRAMES_DIR = CAPTURE_DIR / "frames"

JSON_OUTPUT = CAPTURE_DIR / "13_RESOURCE_COORD_REPORT.json"
CSV_OUTPUT = CAPTURE_DIR / "14_RESOURCE_EVENT_COORDS.csv"
TEXT_OUTPUT = CAPTURE_DIR / "15_RESOURCE_COORD_SUMMARY.txt"
SNAP_RES_OUTPUT = CAPTURE_DIR / "16_SNAP_RES_SAMPLES.json"


def canonical(value: Any, limit: int = 1000) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        text = repr(value)

    if len(text) > limit:
        return text[:limit] + "..."

    return text


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)

        if math.isfinite(number):
            return number

    except Exception:
        pass

    return None


def player_id(value: Any) -> str:
    if value is None:
        return ""

    return str(value)


def rounded_cell(value: float | None) -> str:
    if value is None:
        return "?"

    return str(round(value))


def describe_values(counter: Counter[str], limit: int = 30) -> list[dict]:
    return [
        {
            "value": value,
            "count": count,
        }
        for value, count in counter.most_common(limit)
    ]


event_type_counts: Counter[str] = Counter()
kind_counts: Counter[str] = Counter()
keys_counts: Counter[str] = Counter()
loot_counts: Counter[str] = Counter()
coal_counts: Counter[str] = Counter()
metal_counts: Counter[str] = Counter()
h_counts: Counter[str] = Counter()
hm_counts: Counter[str] = Counter()
l2kind_counts: Counter[str] = Counter()
l2tool_counts: Counter[str] = Counter()

kind_event_counts: Counter[tuple[str, str]] = Counter()
server_event_counts: Counter[str] = Counter()

coordinate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
event_records: list[dict[str, Any]] = []

snap_res_shapes: Counter[str] = Counter()
snap_res_examples: list[dict[str, Any]] = []

total_frames = 0
total_snapshots = 0
total_resource_events = 0
mapped_resource_events = 0


for frame_file in sorted(FRAMES_DIR.glob("*.jsonl")):
    server = frame_file.stem

    latest_players: dict[str, dict[str, Any]] = {}

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

            total_frames += 1

            message_type = str(
                frame.get("t")
                or frame.get("type")
                or ""
            )

            event_type_counts[message_type] += 1

            if message_type == "snap":
                total_snapshots += 1

                players = frame.get("players")

                if isinstance(players, list):
                    current_players: dict[str, dict[str, Any]] = {}

                    for player in players:
                        if not isinstance(player, dict):
                            continue

                        pid = player_id(player.get("id"))

                        if not pid:
                            continue

                        current_players[pid] = {
                            "id": pid,
                            "x": safe_float(player.get("x")),
                            "y": safe_float(player.get("y")),
                            "z": safe_float(player.get("z")),
                            "act": player.get("act"),
                            "eq": player.get("eq"),
                            "pr": player.get("pr"),
                            "mov": player.get("mov"),
                        }

                    latest_players = current_players

                if "res" in frame:
                    resource_snapshot = frame.get("res")

                    if isinstance(resource_snapshot, dict):
                        shape = "dict:" + ",".join(
                            sorted(str(key) for key in resource_snapshot)
                        )

                    elif isinstance(resource_snapshot, list):
                        shape = f"list:length={len(resource_snapshot)}"

                    else:
                        shape = type(resource_snapshot).__name__

                    snap_res_shapes[shape] += 1

                    rendered = canonical(resource_snapshot, limit=10000)

                    if not any(
                        sample["value"] == rendered
                        for sample in snap_res_examples
                    ):
                        if len(snap_res_examples) < 30:
                            snap_res_examples.append({
                                "server": server,
                                "line": line_number,
                                "shape": shape,
                                "value": rendered,
                            })

                continue

            if message_type != "res_evt":
                continue

            total_resource_events += 1
            server_event_counts[server] += 1

            evt = str(frame.get("evt"))
            kind = canonical(frame.get("kind"))
            keys = canonical(frame.get("keys"))
            loot = canonical(frame.get("loot"))

            has_coal = canonical(frame.get("hasCoal"))
            has_metal = canonical(frame.get("hasMetal"))
            h = canonical(frame.get("h"))
            hm = canonical(frame.get("hm"))
            l2kind = canonical(frame.get("l2kind"))
            l2tool = canonical(frame.get("l2t"))

            kind_counts[kind] += 1
            keys_counts[keys] += 1
            loot_counts[loot] += 1
            coal_counts[has_coal] += 1
            metal_counts[has_metal] += 1
            h_counts[h] += 1
            hm_counts[hm] += 1
            l2kind_counts[l2kind] += 1
            l2tool_counts[l2tool] += 1

            kind_event_counts[(kind, evt)] += 1

            actor_id = player_id(frame.get("by"))
            actor = latest_players.get(actor_id)

            x = actor.get("x") if actor else None
            y = actor.get("y") if actor else None
            z = actor.get("z") if actor else None

            if actor is not None:
                mapped_resource_events += 1

            record = {
                "server": server,
                "line": line_number,
                "event": evt,
                "kind": kind,
                "keys": keys,
                "loot": loot,
                "hasCoal": has_coal,
                "hasMetal": has_metal,
                "h": h,
                "hm": hm,
                "l2kind": l2kind,
                "l2tool": l2tool,
                "actor_id": actor_id,
                "x": x,
                "y": y,
                "z": z,
                "grid_x": rounded_cell(x),
                "grid_z": rounded_cell(z),
                "actor_action": actor.get("act") if actor else None,
                "actor_equipment": actor.get("eq") if actor else None,
                "actor_region": actor.get("pr") if actor else None,
                "actor_moving": actor.get("mov") if actor else None,
            }

            event_records.append(record)

            if actor is not None:
                coordinate_groups[kind].append(record)


coordinate_summary: dict[str, dict[str, Any]] = {}

for kind, records in coordinate_groups.items():
    xs = [
        record["x"]
        for record in records
        if record["x"] is not None
    ]

    ys = [
        record["y"]
        for record in records
        if record["y"] is not None
    ]

    zs = [
        record["z"]
        for record in records
        if record["z"] is not None
    ]

    grid_counter = Counter(
        f"{record['grid_x']},{record['grid_z']}"
        for record in records
    )

    server_counter = Counter(
        record["server"]
        for record in records
    )

    equipment_counter = Counter(
        str(record["actor_equipment"])
        for record in records
    )

    action_counter = Counter(
        str(record["actor_action"])
        for record in records
    )

    event_counter = Counter(
        str(record["event"])
        for record in records
    )

    coordinate_summary[kind] = {
        "mapped_events": len(records),
        "x_min": min(xs) if xs else None,
        "x_max": max(xs) if xs else None,
        "x_median": statistics.median(xs) if xs else None,
        "y_min": min(ys) if ys else None,
        "y_max": max(ys) if ys else None,
        "z_min": min(zs) if zs else None,
        "z_max": max(zs) if zs else None,
        "z_median": statistics.median(zs) if zs else None,
        "top_coordinate_cells": describe_values(grid_counter, 30),
        "servers": describe_values(server_counter, 30),
        "events": describe_values(event_counter, 20),
        "equipment": describe_values(equipment_counter, 20),
        "actions": describe_values(action_counter, 20),
    }


report = {
    "capture_directory": str(CAPTURE_DIR),
    "total_frames": total_frames,
    "total_snapshots": total_snapshots,
    "total_resource_events": total_resource_events,
    "mapped_resource_events": mapped_resource_events,
    "message_types": describe_values(event_type_counts, 50),
    "resource_event_kinds": describe_values(kind_counts, 100),
    "resource_event_kind_and_event": [
        {
            "kind": kind,
            "event": event,
            "count": count,
        }
        for (kind, event), count in kind_event_counts.most_common()
    ],
    "resource_keys": describe_values(keys_counts, 100),
    "resource_loot": describe_values(loot_counts, 100),
    "has_coal": describe_values(coal_counts, 30),
    "has_metal": describe_values(metal_counts, 30),
    "h_values": describe_values(h_counts, 30),
    "hm_values": describe_values(hm_counts, 30),
    "l2kind_values": describe_values(l2kind_counts, 50),
    "l2tool_values": describe_values(l2tool_counts, 50),
    "events_by_server": describe_values(server_event_counts, 100),
    "coordinates_by_kind": coordinate_summary,
    "snap_res_shapes": describe_values(snap_res_shapes, 50),
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

SNAP_RES_OUTPUT.write_text(
    json.dumps(
        snap_res_examples,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)


csv_fields = [
    "server",
    "line",
    "event",
    "kind",
    "keys",
    "loot",
    "hasCoal",
    "hasMetal",
    "h",
    "hm",
    "l2kind",
    "l2tool",
    "actor_id",
    "x",
    "y",
    "z",
    "grid_x",
    "grid_z",
    "actor_action",
    "actor_equipment",
    "actor_region",
    "actor_moving",
]

with CSV_OUTPUT.open(
    "w",
    encoding="utf-8",
    newline="",
) as csv_file:

    writer = csv.DictWriter(
        csv_file,
        fieldnames=csv_fields,
    )

    writer.writeheader()
    writer.writerows(event_records)


summary: list[str] = []

summary.append("KINTARA RESOURCE / COORDINATE ANALYSIS")
summary.append("=" * 72)
summary.append(f"Capture: {CAPTURE_DIR}")
summary.append(f"Total frames: {total_frames}")
summary.append(f"Snapshots: {total_snapshots}")
summary.append(f"Resource events: {total_resource_events}")
summary.append(
    f"Resource events mapped to player coordinates: "
    f"{mapped_resource_events}"
)
summary.append("")

summary.append("RESOURCE EVENT KINDS")
summary.append("-" * 72)

for value, count in kind_counts.most_common():
    summary.append(f"{count:7d}  {value}")

summary.append("")
summary.append("KIND + EVENT")
summary.append("-" * 72)

for (kind, event), count in kind_event_counts.most_common():
    summary.append(
        f"{count:7d}  kind={kind} | event={event}"
    )

summary.append("")
summary.append("RESOURCE KEYS")
summary.append("-" * 72)

for value, count in keys_counts.most_common(50):
    summary.append(f"{count:7d}  {value}")

summary.append("")
summary.append("RESOURCE LOOT")
summary.append("-" * 72)

for value, count in loot_counts.most_common(50):
    summary.append(f"{count:7d}  {value}")

summary.append("")
summary.append("COORDINATE RANGES BY KIND")
summary.append("-" * 72)

if not coordinate_summary:
    summary.append(
        "No resource event could be connected to a player coordinate."
    )

for kind, data in sorted(
    coordinate_summary.items(),
    key=lambda pair: pair[1]["mapped_events"],
    reverse=True,
):
    summary.append("")
    summary.append(
        f"KIND: {kind} | mapped_events={data['mapped_events']}"
    )

    summary.append(
        f"X: {data['x_min']} .. {data['x_max']} "
        f"| median={data['x_median']}"
    )

    summary.append(
        f"Z: {data['z_min']} .. {data['z_max']} "
        f"| median={data['z_median']}"
    )

    summary.append("Top X,Z cells:")

    for row in data["top_coordinate_cells"][:15]:
        summary.append(
            f"  {row['count']:6d}  {row['value']}"
        )

    summary.append("Equipment:")

    for row in data["equipment"][:10]:
        summary.append(
            f"  {row['count']:6d}  {row['value']}"
        )

summary.append("")
summary.append("SNAP.RES SHAPES")
summary.append("-" * 72)

for value, count in snap_res_shapes.most_common():
    summary.append(f"{count:7d}  {value}")

TEXT_OUTPUT.write_text(
    "\n".join(summary) + "\n",
    encoding="utf-8",
)


print()
print("=" * 72)
print("OFFLINE RESOURCE ANALYSIS COMPLETE")
print("=" * 72)
print("Capture:", CAPTURE_DIR)
print("Resource events:", total_resource_events)
print("Mapped to coordinates:", mapped_resource_events)
print()
print("Created:")
print(TEXT_OUTPUT)
print(JSON_OUTPUT)
print(CSV_OUTPUT)
print(SNAP_RES_OUTPUT)
print()
print("SUMMARY")
print("=" * 72)
print("\n".join(summary))
