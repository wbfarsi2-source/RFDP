#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram integration for the manual Ember population scan."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from aiogram.types import CallbackQuery, Message

LOGGER = logging.getLogger(__name__)
COOLDOWN_SECONDS = 360
STATE_STALE_SECONDS = 1800
RUNNER_HEARTBEAT_STALE_SECONDS = 45
JOB_TIMEOUT_SECONDS = 1200
WAIT_MESSAGE = "Please wait and do not submit another request until the update is complete."
_TASKS: set[asyncio.Task[Any]] = set()
_STATE_LOCK: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _STATE_LOCK
    if _STATE_LOCK is None:
        _STATE_LOCK = asyncio.Lock()
    return _STATE_LOCK


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "app.py").exists() and (parent / "games" / "kintara").exists():
            return parent
    return Path.cwd().resolve()


def _state_file() -> Path:
    return _project_root() / "data" / "ember_manual_scan_state.json"


def _jobs_dir() -> Path:
    path = _project_root() / "data" / "ember_manual_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runner_heartbeat_file() -> Path:
    return _jobs_dir() / "runner_heartbeat.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _read_state() -> dict[str, Any]:
    return _read_json(_state_file())


def _write_state(state: dict[str, Any]) -> None:
    _write_json(_state_file(), state)


def _env_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = _project_root() / ".env"
    if not env_file.exists():
        return ""
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, item = line.split("=", 1)
        if key.strip() != name:
            continue
        item = item.strip()
        if len(item) >= 2 and item[0] == item[-1] and item[0] in {"'", '"'}:
            item = item[1:-1]
        return item
    return ""


def ember_manual_callback_filter(event: CallbackQuery) -> bool:
    data = str(getattr(event, "data", "") or "").strip().lower()
    if not data:
        return False
    normalized = data.replace("-", "_").replace(":", "_").replace("/", "_")
    area = any(token in normalized for token in ("ember", "molten", "magma"))
    action = any(token in normalized for token in (
        "update", "refresh", "reload", "rescan", "scan", "check"
    ))
    known = normalized in {
        "kintara_ember_update", "kintara_ember_refresh", "kintara_ember_scan",
        "kintara_molten_update", "kintara_molten_refresh", "kintara_molten_scan",
        "ember_update", "ember_refresh", "molten_update", "molten_refresh",
    }
    return bool(known or (area and action))


def _unidentified_names(report: dict[str, Any]) -> list[str]:
    rows = report.get("unidentified_servers") if isinstance(report, dict) else []
    names: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("server") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _format_result(report: dict[str, Any]) -> str:
    top3 = report.get("top3") if isinstance(report, dict) else []
    lines = ["🔥 Come To Molten — Live Server Status"]
    if isinstance(top3, list) and top3:
        for rank, row in enumerate(top3[:3], start=1):
            lines.append(f"{rank}) {row.get('server', '?')} — {int(row.get('count') or 0)} player(s)")
    else:
        lines.append("No server result was detected.")
    unidentified = _unidentified_names(report)
    if unidentified:
        lines.extend(["", "Not detected: " + ", ".join(unidentified)])
    return "\n".join(lines)


def _format_channel(report: dict[str, Any]) -> str:
    top3 = report.get("top3") if isinstance(report, dict) else []
    lines = ["🔥 Come To Molten — Top Servers"]
    if isinstance(top3, list) and top3:
        for rank, row in enumerate(top3[:3], start=1):
            lines.append(f"{rank}) {row.get('server', '?')} — {int(row.get('count') or 0)} player(s)")
    else:
        lines.append("No server result was detected.")
    unidentified = _unidentified_names(report)
    if unidentified:
        lines.extend(["", "Not detected: " + ", ".join(unidentified)])
    return "\n".join(lines)


async def _safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except Exception:
        try:
            await message.answer(text)
        except Exception:
            LOGGER.exception("Could not update Ember message")


async def _publish_channel(bot: Any, report: dict[str, Any]) -> None:
    raw_channel = _env_value("KINTARA_CHANNEL_ID")
    if not raw_channel:
        raise RuntimeError("KINTARA_CHANNEL_ID is not configured")
    try:
        channel_id: int | str = int(raw_channel)
    except Exception:
        channel_id = raw_channel
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            await bot.send_message(channel_id, _format_channel(report))
            return
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2.0 + attempt * 2.0)
    raise RuntimeError(f"channel publish failed: {last_error}")


def _runner_is_alive() -> bool:
    data = _read_json(_runner_heartbeat_file())
    updated = float(data.get("updated_at") or 0.0)
    return bool(updated and time.time() - updated <= RUNNER_HEARTBEAT_STALE_SECONDS)


def _ensure_runner() -> None:
    if _runner_is_alive():
        return
    root = _project_root()
    runner = root / "games" / "kintara" / "services" / "ember" / "runner.py"
    if not runner.exists():
        raise RuntimeError("Ember runner is missing")
    creationflags = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0)) if os.name == "nt" else 0
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "creationflags": creationflags,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    subprocess.Popen([sys.executable, str(runner)], **kwargs)
    deadline = time.time() + 12.0
    while time.time() < deadline:
        if _runner_is_alive():
            return
        time.sleep(0.25)
    raise RuntimeError("Ember runner did not start")


def _submit_job(requester_id: int) -> str:
    job_id = f"{int(time.time())}_{uuid.uuid4().hex[:10]}"
    request = _jobs_dir() / f"{job_id}.request.json"
    _write_json(request, {
        "job_id": job_id,
        "requester_id": int(requester_id),
        "created_at": time.time(),
        "bot_pid": os.getpid(),
    })
    return job_id


def _wait_for_job(job_id: str) -> dict[str, Any]:
    jobs = _jobs_dir()
    result_path = jobs / f"{job_id}.result.json"
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    while time.time() < deadline:
        if result_path.exists():
            payload = _read_json(result_path)
            try:
                result_path.unlink()
            except Exception:
                pass
            if not bool(payload.get("ok")):
                raise RuntimeError(str(payload.get("error") or "Ember scan failed"))
            report = payload.get("report")
            if not isinstance(report, dict):
                raise RuntimeError("Ember runner returned no report")
            return report
        time.sleep(0.5)
    raise TimeoutError("Ember runner timed out")


async def _run_scan(bot: Any, progress_message: Message, requester_id: int) -> None:
    try:
        await asyncio.to_thread(_ensure_runner)
        job_id = await asyncio.to_thread(_submit_job, requester_id)
        report = await asyncio.to_thread(_wait_for_job, job_id)

        try:
            await _publish_channel(bot, report)
        except Exception:
            LOGGER.exception("Ember result could not be published to channel")

        await _safe_edit(progress_message, _format_result(report))
        finished = time.time()
        async with _lock():
            _write_state({
                "running": False,
                "finished_at": finished,
                "cooldown_until": finished + COOLDOWN_SECONDS,
                "requester_id": requester_id,
                "process_id": os.getpid(),
            })
    except Exception as exc:
        LOGGER.exception("Manual Ember scan failed")
        finished = time.time()
        async with _lock():
            _write_state({
                "running": False,
                "finished_at": finished,
                "cooldown_until": finished + COOLDOWN_SECONDS,
                "requester_id": requester_id,
                "process_id": os.getpid(),
                "error": str(exc),
            })
        await _safe_edit(progress_message, "The update could not be completed. Please try again later.")


async def _accept_request(bot: Any, chat_message: Message, requester_id: int) -> None:
    now = time.time()
    async with _lock():
        state = _read_state()
        running = bool(state.get("running"))
        process_id = int(state.get("process_id") or 0)
        accepted_at = float(state.get("accepted_at") or 0.0)
        if running and (process_id != os.getpid() or now - accepted_at > STATE_STALE_SECONDS):
            running = False
            state = {}
        if running:
            await chat_message.answer(WAIT_MESSAGE)
            return
        cooldown_until = float(state.get("cooldown_until") or 0.0)
        if cooldown_until > now:
            remaining = max(1, int(math.ceil(cooldown_until - now)))
            minutes = max(1, int(math.ceil(remaining / 60)))
            await chat_message.answer(
                f"The next update will be available in about {minutes} minute"
                f"{'s' if minutes != 1 else ''}."
            )
            return
        _write_state({
            "running": True,
            "accepted_at": now,
            "cooldown_until": 0,
            "requester_id": requester_id,
            "process_id": os.getpid(),
        })

    progress_message = await chat_message.answer(WAIT_MESSAGE)
    task = asyncio.create_task(_run_scan(bot, progress_message, requester_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def handle_ember_manual_callback(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except Exception:
        pass
    if callback.message is None:
        return
    await _accept_request(callback.bot, callback.message, int(callback.from_user.id))


async def handle_ember_manual_command(message: Message) -> None:
    await _accept_request(message.bot, message, int(message.from_user.id if message.from_user else 0))
