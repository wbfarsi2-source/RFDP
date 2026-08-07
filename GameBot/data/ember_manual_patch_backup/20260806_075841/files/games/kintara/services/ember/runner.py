#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility runner for manual Ember mode.

The old continuous Ember scanner is intentionally disabled. This process remains
idle so a shared-service supervisor does not repeatedly restart the legacy scan.
Actual scans are started only by the Telegram manual-update handler.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "app.py").exists():
            return parent
    return Path.cwd().resolve()


def _candidate_dirs(root: Path) -> list[Path]:
    rows = [
        root / "data" / "shared_services" / "ember",
        root / "games" / "kintara" / "runtime" / "shared" / "ember",
    ]
    for arg in sys.argv[1:]:
        try:
            path = Path(arg).expanduser().resolve()
            if path.exists() and path.is_dir():
                rows.append(path)
        except Exception:
            pass
    unique: list[Path] = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return unique


def _touch_state(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    state_file = directory / "service.json"
    current: dict[str, Any] = {}
    try:
        if state_file.exists():
            loaded = json.loads(state_file.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(loaded, dict):
                current = loaded
    except Exception:
        current = {}
    current.update({
        "status": "manual_mode_idle",
        "desired_status": "manual_mode_idle",
        "pid": os.getpid(),
        "heartbeat_at": now,
        "updated_at": now,
        "manual_scan_only": True,
    })
    temp = state_file.with_suffix(".tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(state_file)
    (directory / "heartbeat.txt").write_text(now + "\n", encoding="utf-8")


def main() -> None:
    root = _root()
    while True:
        for directory in _candidate_dirs(root):
            try:
                _touch_state(directory)
            except Exception:
                pass
        time.sleep(20.0)


def run() -> None:
    main()


if __name__ == "__main__":
    main()
