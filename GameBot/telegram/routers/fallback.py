from __future__ import annotations
from core.locale_text import localized_literal
from aiogram import Router
from aiogram.types import Message
from telegram.helpers import message_language
from telegram.keyboards import main_menu
router = Router(name='fallback')

@router.message()
async def fallback_message(message: Message) -> None:
    lang = await message_language(message)
    await message.answer('Choose an option from the menu.' if lang == 'en' else localized_literal('telegram.routers.fallback.34ae4f96f0f4'), reply_markup=main_menu(lang))
