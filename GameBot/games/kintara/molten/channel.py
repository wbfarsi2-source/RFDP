from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from core.config import settings
from core.database import SessionLocal
from core.models import ServiceEntitlement, User
from core.repositories import active_service_entitlement, list_service_entitlements, set_service_channel_state
from core.runtime.shared_services.store import shared_service_store
from core.runtime_settings import runtime_settings
from core.time_utils import ensure_utc
from games.kintara.molten.access import SERVICE_KEY, access_mode
from games.kintara.molten.view import format_snapshot

logger = logging.getLogger(__name__)


class MoltenChannelService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_post_at = 0.0
        self._last_reconcile_at = 0.0
        self._legacy_invite_checked = False
        self._history_checked = False

    @property
    def channel_id(self) -> int:
        return int(runtime_settings.get("services.kintara_ember.channel_id", settings.kintara_channel_id) or 0)

    @property
    def _message_history_path(self) -> Path:
        return shared_service_store.workspace(SERVICE_KEY) / "channel_message_ids.json"

    def _read_message_ids(self) -> list[int]:
        try:
            payload = json.loads(self._message_history_path.read_text(encoding="utf-8"))
            values = payload.get("message_ids") if isinstance(payload, dict) else []
            return sorted({int(value) for value in values if int(value) > 0})
        except Exception:
            return []

    def _write_message_ids(self, message_ids: list[int]) -> None:
        values = sorted({int(value) for value in message_ids if int(value) > 0})
        temp = self._message_history_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"message_ids": values}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self._message_history_path)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _revoke_legacy_invite_once(self) -> None:
        if self._legacy_invite_checked:
            return
        self._legacy_invite_checked = True
        link = str(settings.kintara_channel_legacy_invite_link or "").strip()
        if not self.channel_id or not link:
            return
        try:
            await self.bot.revoke_chat_invite_link(self.channel_id, link)
            logger.info("Revoked configured legacy Kintara channel invite")
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Could not revoke configured legacy channel invite: %s", exc)

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def create_personal_invite(self, user: User) -> str:
        if not self.channel_id:
            raise RuntimeError("Kintara channel is not configured")
        entitlement = await self._active_entitlement(user.id)
        if entitlement is None:
            raise PermissionError("Come To Molten access is not active")
        try:
            await self.bot.unban_chat_member(
                self.channel_id,
                user.telegram_user_id,
                only_if_banned=True,
            )
        except TelegramBadRequest:
            pass
        expires = int(time.time()) + max(60, int(settings.kintara_channel_invite_expire_seconds))
        link = await self.bot.create_chat_invite_link(
            self.channel_id,
            name=f"molten-{user.telegram_user_id}"[:32],
            expire_date=expires,
            member_limit=1,
        )
        async with SessionLocal() as session:
            await set_service_channel_state(
                session,
                entitlement_id=entitlement.id,
                active=True,
                invite_link=link.invite_link,
            )
        return link.invite_link

    async def remove_user(self, telegram_user_id: int, entitlement_id: int | None = None) -> None:
        if not self.channel_id:
            return
        try:
            await self.bot.ban_chat_member(self.channel_id, telegram_user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        try:
            await self.bot.unban_chat_member(
                self.channel_id,
                telegram_user_id,
                only_if_banned=True,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        if entitlement_id:
            async with SessionLocal() as session:
                await set_service_channel_state(
                    session,
                    entitlement_id=entitlement_id,
                    active=False,
                )

    async def revoke_free_members(self) -> int:
        removed = 0
        async with SessionLocal() as session:
            rows = await list_service_entitlements(session, service_key=SERVICE_KEY)
            user_ids = [row.user_id for row in rows if row.source == "free" and row.status == "active"]
            for row in rows:
                if row.source == "free" and row.status == "active":
                    row.status = "revoked"
            await session.commit()
        for row in rows:
            if row.user_id not in user_ids:
                continue
            async with SessionLocal() as session:
                user = await session.get(User, row.user_id)
            if user:
                await self.remove_user(user.telegram_user_id, row.id)
                removed += 1
        return removed

    async def _delete_message_ids(self, message_ids: list[int]) -> None:
        ids = sorted({int(value) for value in message_ids if int(value) > 0})
        if not ids or not self.channel_id:
            return

        delete_many = getattr(self.bot, "delete_messages", None)
        if callable(delete_many):
            for index in range(0, len(ids), 100):
                batch = ids[index : index + 100]
                try:
                    await delete_many(chat_id=self.channel_id, message_ids=batch)
                    continue
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
                for message_id in batch:
                    try:
                        await self.bot.delete_message(self.channel_id, message_id)
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
            return

        for message_id in ids:
            try:
                await self.bot.delete_message(self.channel_id, message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

    async def _cleanup_existing_channel_messages_once(self) -> None:
        if self._history_checked or not self.channel_id:
            return
        self._history_checked = True

        cleanup_key = "services.kintara_ember.channel_cleanup_v3"
        if int(runtime_settings.get(cleanup_key, 0) or 0) == self.channel_id:
            return

        marker = await self.bot.send_message(self.channel_id, "Preparing live updates...")
        marker_id = int(marker.message_id)
        first_id = 1
        max_sweep = 5000
        if marker_id > max_sweep:
            first_id = marker_id - max_sweep + 1
            logger.warning(
                "Channel cleanup is limited to the most recent %s messages because the channel history is large",
                max_sweep,
            )

        await self._delete_message_ids(list(range(first_id, marker_id + 1)))
        self._write_message_ids([])
        await runtime_settings.set(cleanup_key, self.channel_id)
        await runtime_settings.set("services.kintara_ember.channel_message_id", 0)
        await runtime_settings.set("services.kintara_ember.channel_last_snapshot_version", "")

    async def publish_now(self) -> bool:
        if not self.channel_id:
            return False

        snapshot = shared_service_store.read_snapshot(SERVICE_KEY)
        if not snapshot or str(snapshot.get("source") or "scheduled") != "scheduled":
            return False

        version = str(snapshot.get("version") or "")
        if not version:
            return False
        last_version_key = "services.kintara_ember.channel_last_snapshot_version"
        if str(runtime_settings.get(last_version_key, "") or "") == version:
            return False

        await self._cleanup_existing_channel_messages_once()
        text = format_snapshot(snapshot, "en", channel=True)
        setting_key = "services.kintara_ember.channel_message_id"
        previous_message_id = int(runtime_settings.get(setting_key, 0) or 0)
        tracked_ids = self._read_message_ids()
        if previous_message_id:
            tracked_ids.append(previous_message_id)

        await self._delete_message_ids(tracked_ids)

        message = await self.bot.send_message(
            self.channel_id,
            text,
            protect_content=True,
        )
        message_id = int(message.message_id)
        self._write_message_ids([message_id])
        await runtime_settings.set(setting_key, message_id)
        await runtime_settings.set(last_version_key, version)
        self._last_post_at = time.time()
        return True

    async def reconcile_access(self) -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            rows = await list_service_entitlements(session, service_key=SERVICE_KEY)
            users = {row.id: await session.get(User, row.user_id) for row in rows}
            expired: list[tuple[ServiceEntitlement, User]] = []
            for row in rows:
                invalid = row.status != "active"
                if row.expires_at is not None and ensure_utc(row.expires_at) <= now:
                    row.status = "expired"
                    invalid = True
                if access_mode() == "paid" and row.source == "free":
                    row.status = "revoked"
                    invalid = True
                user = users.get(row.id)
                if invalid and user:
                    expired.append((row, user))
            await session.commit()
        for row, user in expired:
            await self.remove_user(user.telegram_user_id, row.id)

    async def _active_entitlement(self, user_id: int):
        async with SessionLocal() as session:
            return await active_service_entitlement(session, user_id=user_id, service_key=SERVICE_KEY)

    async def _loop(self) -> None:
        reconcile_interval = 20.0
        while not self._stopping:
            try:
                await self._revoke_legacy_invite_once()
                now = time.time()

                if now - self._last_reconcile_at >= reconcile_interval:
                    await self.reconcile_access()
                    self._last_reconcile_at = time.time()

                interval = max(
                    20,
                    int(
                        runtime_settings.get(
                            "services.kintara_ember.channel_post_interval_seconds",
                            settings.kintara_channel_post_interval_seconds,
                        )
                        or 20
                    ),
                )
                if now - self._last_post_at >= interval:
                    await self.publish_now()

                sleep_for = 1.0
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Come To Molten channel service iteration failed")
                sleep_for = 3.0

            await asyncio.sleep(sleep_for)
