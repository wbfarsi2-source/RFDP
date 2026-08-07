#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram integration for the manual sequential Ember scan."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

from aiogram.types import CallbackQuery, Message

from games.kintara.services.ember.manual_scanner import scan_all_servers

LOGGER = logging.getLogger(__name__)
COOLDOWN_SECONDS = 300
STATE_STALE_SECONDS = 1800
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


def _read_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_state(state: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


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


def _format_result(report: dict[str, Any]) -> str:
    top3 = report.get("top3") if isinstance(report, dict) else []
    lines = ["🔥 نتیجه بررسی Emberstone"]
    if isinstance(top3, list) and top3:
        for rank, row in enumerate(top3[:3], start=1):
            lines.append(f"{rank}) {row.get('server', '?')} — {int(row.get('count') or 0)} بازیکن")
    else:
        lines.append("هیچ نتیجهٔ معتبر و قابل شمارشی دریافت نشد.")
    checked = int(report.get("servers_checked") or 0)
    successful = int(report.get("servers_successful") or 0)
    failed = int(report.get("servers_failed") or 0)
    lines.extend([
        "",
        f"بررسی‌شده: {checked}/25 | موفق: {successful} | ناموفق: {failed}",
        "درخواست بعدی ۵ دقیقه پس از پایان این بررسی پذیرفته می‌شود.",
    ])
    return "\n".join(lines)


def _format_channel(report: dict[str, Any]) -> str:
    top3 = report.get("top3") if isinstance(report, dict) else []
    lines = ["🔥 وضعیت Emberstone"]
    if isinstance(top3, list) and top3:
        for rank, row in enumerate(top3[:3], start=1):
            lines.append(f"{rank}) {row.get('server', '?')} — {int(row.get('count') or 0)} بازیکن")
    else:
        lines.append("نتیجه معتبر دریافت نشد.")
    return "\n".join(lines)


async def _safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except Exception:
        try:
            await message.answer(text)
        except Exception:
            LOGGER.exception("Could not update Ember scan message")


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


async def _run_scan(bot: Any, progress_message: Message, requester_id: int) -> None:
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[tuple[int, int, str, bool]] = asyncio.Queue()

    def progress(index: int, total: int, result: Any) -> None:
        loop.call_soon_threadsafe(
            progress_queue.put_nowait,
            (index, total, str(result.server), bool(result.ok)),
        )

    scan_future = asyncio.create_task(asyncio.to_thread(scan_all_servers, progress))
    last_shown = 0
    try:
        while not scan_future.done():
            try:
                index, total, server, ok = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                if index == 1 or index % 5 == 0 or index == total:
                    last_shown = index
                    await _safe_edit(
                        progress_message,
                        f"در حال بررسی Emberstone…\n{index}/{total} سرور بررسی شد.\n"
                        f"آخرین سرور: {server} {'✅' if ok else '⚠️'}\n\n"
                        "تا پایان بررسی، درخواست جدیدی پذیرفته نمی‌شود.",
                    )
            except asyncio.TimeoutError:
                continue
        report = await scan_future
        if last_shown < 25:
            await _safe_edit(progress_message, "بررسی ۲۵ سرور تمام شد؛ در حال انتشار نتیجه…")

        channel_error = ""
        try:
            await _publish_channel(bot, report)
        except Exception as exc:
            channel_error = str(exc)
            LOGGER.exception("Ember result could not be published to channel")

        text = _format_result(report)
        if channel_error:
            text += "\n\n⚠️ نتیجه آماده شد اما ارسال به کانال ناموفق بود؛ دسترسی ادمین بات و KINTARA_CHANNEL_ID را بررسی کن."
        await _safe_edit(progress_message, text)

        finished = time.time()
        async with _lock():
            _write_state({
                "running": False,
                "finished_at": finished,
                "cooldown_until": finished + COOLDOWN_SECONDS,
                "requester_id": requester_id,
                "process_id": os.getpid(),
                "channel_published": not bool(channel_error),
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
        await _safe_edit(
            progress_message,
            "بررسی Ember کامل نشد. خطا ثبت شد و برای محافظت از حساب، "
            "تا ۵ دقیقه درخواست تازه پذیرفته نمی‌شود.\n\n"
            f"خطا: {type(exc).__name__}: {exc}",
        )


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
            await chat_message.answer("یک بررسی Ember در حال اجراست. تا پایان آن درخواست دیگری پذیرفته نمی‌شود.")
            return
        cooldown_until = float(state.get("cooldown_until") or 0.0)
        if cooldown_until > now:
            remaining = max(1, int(math.ceil(cooldown_until - now)))
            minutes, seconds = divmod(remaining, 60)
            await chat_message.answer(
                f"درخواست جدید فعلاً بسته است. زمان باقی‌مانده: {minutes}:{seconds:02d}"
            )
            return
        _write_state({
            "running": True,
            "accepted_at": now,
            "cooldown_until": 0,
            "requester_id": requester_id,
            "process_id": os.getpid(),
        })

    progress_message = await chat_message.answer(
        "درخواست پذیرفته شد. بررسی ۲۵ سرور به‌ترتیب آغاز شد.\n"
        "شروع بررسی هر سرور حداقل ۵ ثانیه با سرور قبلی فاصله دارد."
    )
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
