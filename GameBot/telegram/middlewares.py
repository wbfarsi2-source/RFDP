from __future__ import annotations
from core.locale_text import localized_literal
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from core.config import settings
from core.runtime_settings import runtime_settings

class MaintenanceMiddleware(BaseMiddleware):

    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        if not runtime_settings.maintenance_enabled():
            return await handler(event, data)
        user = getattr(event, 'from_user', None)
        if user and user.id in settings.admin_user_ids:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(runtime_settings.maintenance_message('fa'), show_alert=True)
            return None
        if isinstance(event, Message):
            await event.answer(f"{localized_literal('telegram.middlewares.2949745cf8b4')}{runtime_settings.maintenance_message('fa')}\n\n{runtime_settings.maintenance_message('en')}")
            return None
        return None
