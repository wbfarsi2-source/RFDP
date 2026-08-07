from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from core.database import SessionLocal
from core.models import User
from core.repositories import list_enabled_shared_service_access, update_shared_service_message
from core.shared_service_manager import KINTARA_EMBER_SERVICE_KEY
from core.shared_service_store import shared_service_store
from games.kintara.ember_view import format_ember_snapshot
from telegram.keyboards import ember_access_keyboard

logger = logging.getLogger(__name__)


class EmberAccessUpdateService:
    """Edits one saved Telegram message per enrolled user when the shared snapshot changes."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_seen_version = ""

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                snapshot = shared_service_store.read_snapshot(KINTARA_EMBER_SERVICE_KEY)
                version = str(snapshot.get("version") or snapshot.get("updated_at") or "")
                if snapshot and version and version != self._last_seen_version:
                    await self._publish(snapshot, version)
                    self._last_seen_version = version
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Ember access updater failed")
            await asyncio.sleep(10)

    async def _publish(self, snapshot: dict, version: str) -> None:
        async with SessionLocal() as session:
            accesses = await list_enabled_shared_service_access(
                session,
                service_key=KINTARA_EMBER_SERVICE_KEY,
            )
            rows = []
            for access in accesses:
                if not access.chat_id or not access.message_id:
                    continue
                if str(access.last_snapshot_version or "") == version:
                    continue
                user = await session.get(User, access.user_id)
                lang = "en" if user and user.language == "en" else "fa"
                rows.append((access.id, int(access.chat_id), int(access.message_id), lang))

        for access_id, chat_id, message_id, lang in rows:
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_ember_snapshot(snapshot, lang),
                    reply_markup=ember_access_keyboard(lang, True),
                )
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    logger.warning("Cannot update Ember message chat=%s msg=%s: %s", chat_id, message_id, exc)
            except TelegramForbiddenError:
                logger.warning("User blocked bot; Ember update skipped chat=%s", chat_id)
            except Exception:
                logger.exception("Ember message update failed chat=%s msg=%s", chat_id, message_id)
            else:
                async with SessionLocal() as session:
                    await update_shared_service_message(
                        session,
                        access_id=access_id,
                        chat_id=chat_id,
                        message_id=message_id,
                        snapshot_version=version,
                    )
            await asyncio.sleep(0.06)
