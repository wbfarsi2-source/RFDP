#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated visible CMD runner for manual Ember scans."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 8.0
_STATUS_LOCK = threading.Lock()
_STATUS = "ready"
_ACTIVE_JOB = ""


def _root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "app.py").exists():
            return parent
    return Path.cwd().resolve()


def _jobs_dir(root: Path) -> Path:
    path = root / "data" / "ember_manual_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _service_dirs(root: Path) -> list[Path]:
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


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _set_status(status: str, job_id: str = "") -> None:
    global _STATUS, _ACTIVE_JOB
    with _STATUS_LOCK:
        _STATUS = status
        _ACTIVE_JOB = job_id


def _status() -> tuple[str, str]:
    with _STATUS_LOCK:
        return _STATUS, _ACTIVE_JOB


def _heartbeat_loop(root: Path, stop: threading.Event) -> None:
    jobs = _jobs_dir(root)
    while not stop.is_set():
        status, job_id = _status()
        now_epoch = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "pid": os.getpid(),
            "status": status,
            "active_job": job_id,
            "updated_at": now_epoch,
            "updated_at_iso": now_iso,
        }
        try:
            _write_json(jobs / "runner_heartbeat.json", payload)
        except Exception:
            pass
        for directory in _service_dirs(root):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                current: dict[str, Any] = {}
                state_file = directory / "service.json"
                if state_file.exists():
                    try:
                        loaded = json.loads(state_file.read_text(encoding="utf-8", errors="ignore"))
                        if isinstance(loaded, dict):
                            current = loaded
                    except Exception:
                        current = {}
                current.update({
                    "status": f"manual_mode_{status}",
                    "desired_status": "manual_mode_ready",
                    "pid": os.getpid(),
                    "heartbeat_at": now_iso,
                    "updated_at": now_iso,
                    "manual_scan_only": True,
                    "active_job": job_id,
                })
                _write_json(state_file, current)
                (directory / "heartbeat.txt").write_text(now_iso + "\n", encoding="utf-8")
            except Exception:
                pass
        stop.wait(HEARTBEAT_SECONDS)


def _set_console_title() -> None:
    if os.name == "nt":
        try:
            os.system("title Kintara Ember Scanner")
        except Exception:
            pass


def _print_header(root: Path) -> None:
    print("=" * 72, flush=True)
    print("KINTARA EMBER SCANNER", flush=True)
    print("Dedicated manual scan console", flush=True)
    print(f"Project: {root}", flush=True)
    print("Waiting for an update request from Telegram...", flush=True)
    print("=" * 72, flush=True)


def _recover_interrupted_jobs(jobs: Path) -> None:
    for running in jobs.glob("*.running.json"):
        job_id = running.name[:-len(".running.json")]
        result = jobs / f"{job_id}.result.json"
        request = jobs / f"{job_id}.request.json"
        if result.exists():
            try:
                running.unlink()
            except Exception:
                pass
            continue
        try:
            running.replace(request)
        except Exception:
            pass


def _claim_next_job(jobs: Path) -> Path | None:
    for request in sorted(jobs.glob("*.request.json"), key=lambda p: p.stat().st_mtime):
        job_id = request.name[:-len(".request.json")]
        running = jobs / f"{job_id}.running.json"
        try:
            request.replace(running)
            return running
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return None


def _job_id(path: Path) -> str:
    suffix = ".running.json"
    return path.name[:-len(suffix)] if path.name.endswith(suffix) else path.stem


def _duration(result: Any) -> float:
    try:
        return max(0.0, float(result.finished_at) - float(result.started_at))
    except Exception:
        return 0.0


def _process_job(
    root: Path,
    running_path: Path,
    scan_func: Callable[[Callable[[int, int, Any], None]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    job_id = _job_id(running_path)
    jobs = _jobs_dir(root)
    result_path = jobs / f"{job_id}.result.json"
    _set_status("scanning", job_id)
    print("", flush=True)
    print("-" * 72, flush=True)
    print(f"New Ember update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("Checking 25 servers with 6-8 second start gaps...", flush=True)
    print("-" * 72, flush=True)

    if scan_func is None:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from games.kintara.services.ember.manual_scanner import scan_all_servers
        scan_func = scan_all_servers

    def progress(index: int, total: int, result: Any) -> None:
        server = str(getattr(result, "server", "?") or "?")
        attempts = int(getattr(result, "attempts", 1) or 1)
        elapsed = _duration(result)
        if bool(getattr(result, "ok", False)):
            count = int(getattr(result, "count", 0) or 0)
            retry_text = f" | attempts={attempts}" if attempts > 1 else ""
            print(
                f"[{index:02d}/{total:02d}] {server:<12} | players={count:<3} | {elapsed:5.2f}s{retry_text}",
                flush=True,
            )
        else:
            error = str(getattr(result, "error", "") or "not detected")
            print(
                f"[{index:02d}/{total:02d}] {server:<12} | NOT DETECTED | {elapsed:5.2f}s | attempts={attempts}",
                flush=True,
            )
            print(f"             {error}", flush=True)

    try:
        report = scan_func(progress)
        top3 = report.get("top3") if isinstance(report, dict) else []
        unidentified = report.get("unidentified_servers") if isinstance(report, dict) else []
        print("-" * 72, flush=True)
        print("TOP 3", flush=True)
        if isinstance(top3, list) and top3:
            for rank, row in enumerate(top3[:3], start=1):
                print(f"{rank}) {row.get('server', '?')} - {int(row.get('count') or 0)} player(s)", flush=True)
        else:
            print("No valid result.", flush=True)
        if isinstance(unidentified, list) and unidentified:
            names = ", ".join(str(row.get("server") or "?") for row in unidentified if isinstance(row, dict))
            print(f"Not detected: {names}", flush=True)
        payload = {"ok": True, "job_id": job_id, "finished_at": time.time(), "report": report}
        _write_json(result_path, payload)
        print("Result sent back to Telegram bot.", flush=True)
        print("Waiting for the next update request...", flush=True)
        return payload
    except Exception as exc:
        print("SCAN FAILED", flush=True)
        print(f"{type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        payload = {
            "ok": False,
            "job_id": job_id,
            "finished_at": time.time(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_json(result_path, payload)
        print("Waiting for the next update request...", flush=True)
        return payload
    finally:
        try:
            running_path.unlink()
        except Exception:
            pass
        _set_status("ready", "")


def main() -> None:
    root = _root()
    jobs = _jobs_dir(root)
    _set_console_title()
    _recover_interrupted_jobs(jobs)
    stop = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(root, stop), daemon=True)
    heartbeat.start()
    _print_header(root)
    try:
        while True:
            job = _claim_next_job(jobs)
            if job is None:
                time.sleep(POLL_SECONDS)
                continue
            _process_job(root, job)
    except KeyboardInterrupt:
        print("Ember scanner stopped.", flush=True)
    finally:
        stop.set()
        heartbeat.join(timeout=2.0)


def run() -> None:
    main()


if __name__ == "__main__":
    main()
