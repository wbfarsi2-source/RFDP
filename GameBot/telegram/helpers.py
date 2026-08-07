from __future__ import annotations

from aiogram.types import Message, User as TelegramUser

from core.config import settings
from core.database import SessionLocal
from core.i18n import normalize_language
from core.models import User
from core.repositories import get_or_create_user, get_user_by_telegram


async def sync_telegram_user(telegram_user: TelegramUser, language: str | None = None) -> User:
    async with SessionLocal() as session:
        return await get_or_create_user(
            session,
            telegram_user_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language=language,
            is_admin=telegram_user.id in settings.admin_user_ids,
        )


async def message_language(message: Message) -> str:
    if not message.from_user:
        return "fa"
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, message.from_user.id)
    return normalize_language(user.language if user else "fa")


async def telegram_language(telegram_user_id: int) -> str:
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, telegram_user_id)
    return normalize_language(user.language if user else "fa")
