#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Offline Kintara resource-grid analyzer.

Network: NONE
HTTP: NONE
WebSocket: NONE
Gameplay actions: NONE

Reads the newest MAGMA_RAW_TEST_* capture and:
- Normalizes resource grid keys such as "15,60"
- Converts grid coordinates to world coordinates
- Collects hasCoal, hasMetal, loot, kind, h and hm
- Finds connected candidate resource zones
- Counts players seen inside each candidate zone
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


WORK_DIR = Path(__file__).resolve().parent
GRID_OFFSET = 31.5
PLAYER_ZONE_MARGIN = 1.5

NORMAL_LOOT = {
    "",
    "null",
    "none",
    "stone",
    "wood",
    "coal",
}

KEY_PATTERN = re.compile(r"(?<!\d)(\d{1,3}),(\d{1,3})(?!\d)")


def newest_capture() -> Path:
    captures = [
        path
        for path in WORK_DIR.glob("MAGMA_RAW_TEST_*")
        if path.is_dir() and (path / "frames").is_dir()
    ]

    if not captures:
        raise RuntimeError(
            f"No MAGMA_RAW_TEST_* directory found in {WORK_DIR}"
        )

    return max(captures, key=lambda path: path.stat().st_mtime)


CAPTURE_DIR = newest_capture()
FRAMES_DIR = CAPTURE_DIR / "frames"

CSV_OUTPUT = CAPTURE_DIR / "17_RESOURCE_GRID_CELLS.csv"
TEXT_OUTPUT = CAPTURE_DIR / "18_RESOURCE_GRID_CANDIDATES.txt"
JSON_OUTPUT = CAPTURE_DIR / "19_RESOURCE_GRID_REPORT.json"
SAMPLES_OUTPUT = CAPTURE_DIR / "20_SNAP_RESOURCE_SAMPLES.json"


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)

        if math.isfinite(number):
            return number
    except Exception:
        pass

    return None


def normalize_scalar(value: Any) -> str:
    if value is None:
        return "null"

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    return str(value)


def truthy(value: Any) -> bool:
    if value is True:
        return True

    if isinstance(value, (int, float)):
        return value != 0

    text = str(value or "").strip().lower()

    return text in {
        "1",
        "true",
        "yes",
        "on",
        "metal",
        "coal",
    }


def find_grid_keys(value: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 12:
            return

        if isinstance(node, str):
            for match in KEY_PATTERN.finditer(node):
                gx = int(match.group(1))
                gz = int(match.group(2))

                if 0 <= gx <= 255 and 0 <= gz <= 255:
                    found.add(f"{gx},{gz}")

            return

        if isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
            return

        if isinstance(node, dict):
            for child in node.values():
                walk(child, depth + 1)

    walk(value)

    return found


def direct_value(
    mapping: dict[str, Any],
    names: tuple[str, ...],
) -> Any:
    lowered = {
        str(key).lower(): value
        for key, value in mapping.items()
    }

    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]

    return None


def normalize_resource_entry(
    entry: Any,
    source: str,
    server: str,
    line_number: int,
) -> list[dict[str, Any]]:

    if not isinstance(entry, dict):
        return []

    keys_value = direct_value(
        entry,
        (
            "keys",
            "key",
            "k",
            "cell",
            "cells",
            "grid",
            "id",
        ),
    )

    keys = find_grid_keys(keys_value)

    if not keys:
        keys = find_grid_keys(entry)

    if not keys:
        return []

    kind = direct_value(
        entry,
        (
            "kind",
            "resourceKind",
            "resource_kind",
            "type",
        ),
    )

    loot = direct_value(
        entry,
        (
            "loot",
            "drop",
            "item",
            "resource",
            "reward",
        ),
    )

    has_coal = direct_value(
        entry,
        (
            "hasCoal",
            "has_coal",
            "coal",
        ),
    )

    has_metal = direct_value(
        entry,
        (
            "hasMetal",
            "has_metal",
            "metal",
        ),
    )

    event = direct_value(
        entry,
        (
            "evt",
            "event",
            "action",
        ),
    )

    h = direct_value(entry, ("h", "health"))
    hm = direct_value(entry, ("hm", "maxHealth", "max_health"))

    rows = []

    for key in sorted(keys):
        gx_text, gz_text = key.split(",", 1)

        gx = int(gx_text)
        gz = int(gz_text)

        rows.append({
            "server": server,
            "line": line_number,
            "source": source,
            "key": key,
            "grid_x": gx,
            "grid_z": gz,
            "world_x": gx - GRID_OFFSET,
            "world_z": gz - GRID_OFFSET,
            "kind": normalize_scalar(kind),
            "loot": normalize_scalar(loot),
            "has_coal": truthy(has_coal),
            "has_metal": truthy(has_metal),
            "event": normalize_scalar(event),
            "h": normalize_scalar(h),
            "hm": normalize_scalar(hm),
            "raw": entry,
        })

    return rows


cell_data: dict[str, dict[str, Any]] = {}
raw_samples: list[dict[str, Any]] = []

player_snapshots: list[dict[str, Any]] = []

total_snap_res_entries = 0
total_res_events = 0


def get_cell(key: str, gx: int, gz: int) -> dict[str, Any]:
    if key not in cell_data:
        cell_data[key] = {
            "key": key,
            "grid_x": gx,
            "grid_z": gz,
            "world_x": gx - GRID_OFFSET,
            "world_z": gz - GRID_OFFSET,
            "observations": 0,
            "servers": Counter(),
            "sources": Counter(),
            "kinds": Counter(),
            "loots": Counter(),
            "events": Counter(),
            "h_values": Counter(),
            "hm_values": Counter(),
            "coal_true": 0,
            "metal_true": 0,
        }

    return cell_data[key]


def add_resource_row(row: dict[str, Any]) -> None:
    cell = get_cell(
        row["key"],
        row["grid_x"],
        row["grid_z"],
    )

    cell["observations"] += 1
    cell["servers"][row["server"]] += 1
    cell["sources"][row["source"]] += 1
    cell["kinds"][row["kind"]] += 1
    cell["loots"][row["loot"]] += 1
    cell["events"][row["event"]] += 1
    cell["h_values"][row["h"]] += 1
    cell["hm_values"][row["hm"]] += 1

    if row["has_coal"]:
        cell["coal_true"] += 1

    if row["has_metal"]:
        cell["metal_true"] += 1


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

            if not isinstance(frame, dict):
                continue

            message_type = str(frame.get("t") or "")

            if message_type == "snap":
                players = frame.get("players")

                if isinstance(players, list):
                    normalized_players = []

                    for player in players:
                        if not isinstance(player, dict):
                            continue

                        x = safe_float(player.get("x"))
                        z = safe_float(player.get("z"))

                        if x is None or z is None:
                            continue

                        normalized_players.append({
                            "id": str(player.get("id") or ""),
                            "x": x,
                            "z": z,
                            "act": player.get("act"),
                            "eq": player.get("eq"),
                        })

                    player_snapshots.append({
                        "server": server,
                        "line": line_number,
                        "players": normalized_players,
                    })

                resources = frame.get("res")

                if isinstance(resources, list):
                    for entry in resources:
                        total_snap_res_entries += 1

                        if len(raw_samples) < 100:
                            raw_samples.append({
                                "server": server,
                                "line": line_number,
                                "entry": entry,
                            })

                        for normalized in normalize_resource_entry(
                            entry,
                            "snap.res",
                            server,
                            line_number,
                        ):
                            add_resource_row(normalized)

                elif isinstance(resources, dict):
                    total_snap_res_entries += 1

                    if len(raw_samples) < 100:
                        raw_samples.append({
                            "server": server,
                            "line": line_number,
                            "entry": resources,
                        })

                    for normalized in normalize_resource_entry(
                        resources,
                        "snap.res",
                        server,
                        line_number,
                    ):
                        add_resource_row(normalized)

            elif message_type == "res_evt":
                total_res_events += 1

                for normalized in normalize_resource_entry(
                    frame,
                    "res_evt",
                    server,
                    line_number,
                ):
                    add_resource_row(normalized)


def unusual_loot(cell: dict[str, Any]) -> set[str]:
    values = set()

    for loot in cell["loots"]:
        normalized = str(loot).strip().lower().strip('"')

        if normalized not in NORMAL_LOOT:
            values.add(loot)

    return values


def candidate_reason(cell: dict[str, Any]) -> list[str]:
    reasons = []

    if cell["metal_true"] > 0:
        reasons.append("hasMetal")

    if unusual_loot(cell):
        reasons.append("unusualLoot")

    kind_text = " ".join(cell["kinds"]).lower()

    if any(word in kind_text for word in (
        "magma",
        "molten",
        "lava",
        "metal",
        "volcan",
    )):
        reasons.append("specialKind")

    loot_text = " ".join(cell["loots"]).lower()

    if any(word in loot_text for word in (
        "magma",
        "molten",
        "lava",
        "metal",
    )):
        reasons.append("specialLoot")

    return reasons


candidate_keys = {
    key
    for key, cell in cell_data.items()
    if candidate_reason(cell)
}


def adjacent_keys(key: str):
    gx_text, gz_text = key.split(",", 1)

    gx = int(gx_text)
    gz = int(gz_text)

    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            if dx == 0 and dz == 0:
                continue

            yield f"{gx + dx},{gz + dz}"


clusters: list[list[str]] = []
remaining = set(candidate_keys)

while remaining:
    start = remaining.pop()
    queue = deque([start])
    cluster = [start]

    while queue:
        current = queue.popleft()

        for neighbor in adjacent_keys(current):
            if neighbor in remaining:
                remaining.remove(neighbor)
                queue.append(neighbor)
                cluster.append(neighbor)

    clusters.append(cluster)

clusters.sort(
    key=lambda cluster: sum(
        cell_data[key]["observations"]
        for key in cluster
    ),
    reverse=True,
)


def players_in_bounds(
    x_min: float,
    x_max: float,
    z_min: float,
    z_max: float,
) -> dict[str, Any]:

    maximum_by_server: Counter[str] = Counter()
    last_by_server: dict[str, int] = {}

    for snapshot in player_snapshots:
        count = 0

        for player in snapshot["players"]:
            if (
                x_min <= player["x"] <= x_max
                and z_min <= player["z"] <= z_max
            ):
                count += 1

        server = snapshot["server"]

        maximum_by_server[server] = max(
            maximum_by_server[server],
            count,
        )

        last_by_server[server] = count

    return {
        "maximum_by_server": dict(
            maximum_by_server.most_common()
        ),
        "last_by_server": dict(
            sorted(last_by_server.items())
        ),
    }


cluster_reports = []

for index, cluster in enumerate(clusters, start=1):
    cells = [cell_data[key] for key in cluster]

    grid_x_values = [cell["grid_x"] for cell in cells]
    grid_z_values = [cell["grid_z"] for cell in cells]

    world_x_min = min(cell["world_x"] for cell in cells)
    world_x_max = max(cell["world_x"] for cell in cells)
    world_z_min = min(cell["world_z"] for cell in cells)
    world_z_max = max(cell["world_z"] for cell in cells)

    loot_counter = Counter()
    kind_counter = Counter()
    server_counter = Counter()
    reasons = Counter()

    for cell in cells:
        loot_counter.update(cell["loots"])
        kind_counter.update(cell["kinds"])
        server_counter.update(cell["servers"])
        reasons.update(candidate_reason(cell))

    player_counts = players_in_bounds(
        world_x_min - PLAYER_ZONE_MARGIN,
        world_x_max + PLAYER_ZONE_MARGIN,
        world_z_min - PLAYER_ZONE_MARGIN,
        world_z_max + PLAYER_ZONE_MARGIN,
    )

    cluster_reports.append({
        "cluster": index,
        "cells": sorted(cluster),
        "cell_count": len(cells),
        "observations": sum(
            cell["observations"]
            for cell in cells
        ),
        "grid_bounds": {
            "x_min": min(grid_x_values),
            "x_max": max(grid_x_values),
            "z_min": min(grid_z_values),
            "z_max": max(grid_z_values),
        },
        "world_bounds": {
            "x_min": world_x_min,
            "x_max": world_x_max,
            "z_min": world_z_min,
            "z_max": world_z_max,
        },
        "reasons": dict(reasons),
        "kinds": dict(kind_counter.most_common()),
        "loots": dict(loot_counter.most_common()),
        "servers": dict(server_counter.most_common()),
        "players": player_counts,
    })


csv_fields = [
    "key",
    "grid_x",
    "grid_z",
    "world_x",
    "world_z",
    "observations",
    "coal_true",
    "metal_true",
    "candidate_reasons",
    "kinds",
    "loots",
    "events",
    "servers",
]

with CSV_OUTPUT.open(
    "w",
    encoding="utf-8",
    newline="",
) as output_file:

    writer = csv.DictWriter(
        output_file,
        fieldnames=csv_fields,
    )

    writer.writeheader()

    for key, cell in sorted(
        cell_data.items(),
        key=lambda item: (
            item[1]["grid_z"],
            item[1]["grid_x"],
        ),
    ):
        writer.writerow({
            "key": key,
            "grid_x": cell["grid_x"],
            "grid_z": cell["grid_z"],
            "world_x": cell["world_x"],
            "world_z": cell["world_z"],
            "observations": cell["observations"],
            "coal_true": cell["coal_true"],
            "metal_true": cell["metal_true"],
            "candidate_reasons": ",".join(
                candidate_reason(cell)
            ),
            "kinds": json.dumps(
                dict(cell["kinds"].most_common()),
                ensure_ascii=False,
            ),
            "loots": json.dumps(
                dict(cell["loots"].most_common()),
                ensure_ascii=False,
            ),
            "events": json.dumps(
                dict(cell["events"].most_common()),
                ensure_ascii=False,
            ),
            "servers": json.dumps(
                dict(cell["servers"].most_common()),
                ensure_ascii=False,
            ),
        })


serialized_cells = {}

for key, cell in cell_data.items():
    serialized_cells[key] = {
        "key": cell["key"],
        "grid_x": cell["grid_x"],
        "grid_z": cell["grid_z"],
        "world_x": cell["world_x"],
        "world_z": cell["world_z"],
        "observations": cell["observations"],
        "coal_true": cell["coal_true"],
        "metal_true": cell["metal_true"],
        "candidate_reasons": candidate_reason(cell),
        "kinds": dict(cell["kinds"].most_common()),
        "loots": dict(cell["loots"].most_common()),
        "events": dict(cell["events"].most_common()),
        "servers": dict(cell["servers"].most_common()),
        "h_values": dict(cell["h_values"].most_common()),
        "hm_values": dict(cell["hm_values"].most_common()),
    }


report = {
    "capture_directory": str(CAPTURE_DIR),
    "grid_offset": GRID_OFFSET,
    "total_snap_resource_entries": total_snap_res_entries,
    "total_resource_events": total_res_events,
    "normalized_cell_count": len(cell_data),
    "candidate_cell_count": len(candidate_keys),
    "clusters": cluster_reports,
    "cells": serialized_cells,
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

SAMPLES_OUTPUT.write_text(
    json.dumps(
        raw_samples,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)


summary = []

summary.append("KINTARA MAGMA RESOURCE GRID ANALYSIS")
summary.append("=" * 76)
summary.append(f"Capture: {CAPTURE_DIR}")
summary.append(f"Grid offset: {GRID_OFFSET}")
summary.append(f"Snap resource entries: {total_snap_res_entries}")
summary.append(f"Resource events: {total_res_events}")
summary.append(f"Normalized resource cells: {len(cell_data)}")
summary.append(f"Special candidate cells: {len(candidate_keys)}")
summary.append(f"Candidate clusters: {len(cluster_reports)}")
summary.append("")

overall_coal = sum(
    cell["coal_true"]
    for cell in cell_data.values()
)

overall_metal = sum(
    cell["metal_true"]
    for cell in cell_data.values()
)

summary.append(f"hasCoal=true observations: {overall_coal}")
summary.append(f"hasMetal=true observations: {overall_metal}")
summary.append("")

if not cluster_reports:
    summary.append("NO SPECIAL MAGMA/METAL CANDIDATE WAS FOUND.")
    summary.append("")
    summary.append(
        "The current capture contains only ordinary world resources."
    )
    summary.append(
        "A longer capture or a frontend-map definition is required "
        "before defining the Magma bounds."
    )

for cluster in cluster_reports:
    summary.append("-" * 76)
    summary.append(
        f"CLUSTER {cluster['cluster']} | "
        f"cells={cluster['cell_count']} | "
        f"observations={cluster['observations']}"
    )

    bounds = cluster["world_bounds"]

    summary.append(
        "World bounds: "
        f"x={bounds['x_min']}..{bounds['x_max']} | "
        f"z={bounds['z_min']}..{bounds['z_max']}"
    )

    summary.append(
        "Grid bounds: "
        f"x={cluster['grid_bounds']['x_min']}.."
        f"{cluster['grid_bounds']['x_max']} | "
        f"z={cluster['grid_bounds']['z_min']}.."
        f"{cluster['grid_bounds']['z_max']}"
    )

    summary.append(
        "Reasons: "
        + json.dumps(
            cluster["reasons"],
            ensure_ascii=False,
        )
    )

    summary.append(
        "Loot: "
        + json.dumps(
            cluster["loots"],
            ensure_ascii=False,
        )
    )

    summary.append(
        "Kinds: "
        + json.dumps(
            cluster["kinds"],
            ensure_ascii=False,
        )
    )

    maximum_players = Counter(
        cluster["players"]["maximum_by_server"]
    )

    summary.append("Maximum players seen inside bounds:")

    if maximum_players:
        for server, count in maximum_players.most_common(10):
            summary.append(
                f"  {server}: {count}"
            )
    else:
        summary.append("  No players detected.")

summary.append("")
summary.append("=" * 76)
summary.append("FILES")
summary.append(str(CSV_OUTPUT))
summary.append(str(JSON_OUTPUT))
summary.append(str(SAMPLES_OUTPUT))

TEXT_OUTPUT.write_text(
    "\n".join(summary) + "\n",
    encoding="utf-8",
)

print()
print("\n".join(summary))
print()
print("Saved summary:")
print(TEXT_OUTPUT)
