from __future__ import annotations
from core.locale_text import localized_literal
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from core.config import settings
from core.database import SessionLocal
from core.models import GameAccount, NotificationLog, Subscription, User, UserPreference
from core.time_utils import display_datetime, ensure_utc
from core.runtime_settings import runtime_settings
logger = logging.getLogger(__name__)

class NotificationService:

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._stopping = False

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

    async def _claim_once(self, session, user_id: int, notification_type: str, reference: str) -> bool:
        row = NotificationLog(user_id=user_id, notification_type=notification_type, reference=reference)
        session.add(row)
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False

    async def check(self) -> None:
        now = datetime.now(timezone.utc)
        threshold = now + timedelta(hours=runtime_settings.expiry_warning_hours())
        async with SessionLocal() as session:
            rows = await session.execute(select(Subscription, GameAccount, User, UserPreference).join(GameAccount, GameAccount.id == Subscription.account_id).join(User, User.id == GameAccount.user_id).outerjoin(UserPreference, UserPreference.user_id == User.id).where(Subscription.status == 'active', Subscription.expires_at <= threshold))
            records = list(rows.all())
        for sub, account, user, preference in records:
            expiry = ensure_utc(sub.expires_at)
            expired = expiry <= now
            if expired:
                async with SessionLocal() as session:
                    db_sub = await session.get(Subscription, sub.id)
                    if db_sub and db_sub.status == 'active':
                        db_sub.status = 'expired'
                        await session.commit()
            if preference is not None and (not preference.notifications_enabled):
                continue
            kind = 'subscription_expired' if expired else 'subscription_expiry_warning'
            reference = f'{sub.id}:{expiry.isoformat()}'
            async with SessionLocal() as session:
                if not await self._claim_once(session, user.id, kind, reference):
                    continue
            lang = 'en' if user.language == 'en' else 'fa'
            if expired:
                text = f'⛔ <b>Subscription expired</b>\nAccount: <b>{account.label}</b>' if lang == 'en' else f"{localized_literal('core.notification_service.901c2e9d3d13')}{account.label}</b>"
            else:
                text = f'⏳ <b>Your subscription will expire soon.</b>\nAccount: <b>{account.label}</b>\nExpires: <b>{display_datetime(expiry, lang)}</b>' if lang == 'en' else f"{localized_literal('core.notification_service.1a43b88a4b84')}{account.label}{localized_literal('core.notification_service.ad39cec0a590')}{display_datetime(expiry, lang)}</b>"
            try:
                await self.bot.send_message(user.telegram_user_id, text)
            except Exception:
                logger.exception('Failed to send subscription notification user=%s', user.telegram_user_id)

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception('Notification service iteration failed')
            await asyncio.sleep(runtime_settings.expiry_check_seconds())
