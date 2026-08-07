from __future__ import annotations
from core.locale_text import localized_literal
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from core.config import settings
from core.feature_flags import feature_flags
from core.runtime_settings import runtime_settings
from core.database import SessionLocal
from core.i18n import tr
from core.registry import game_registry
from core.repositories import get_user_by_telegram, get_user_preference, set_user_language, toggle_notifications
from telegram.account_view import send_my_account
from telegram.helpers import message_language, sync_telegram_user
from telegram.keyboards import BUTTONS, b, game_actions, games_keyboard, language_keyboard, main_menu, settings_menu, support_link
router = Router(name='start')

@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    await sync_telegram_user(message.from_user, language=None)
    await message.answer(tr('language_prompt', 'fa'), reply_markup=language_keyboard())

@router.message(Command('myid'))
async def my_id(message: Message) -> None:
    if not message.from_user:
        return
    username = f'@{message.from_user.username}' if message.from_user.username else '-'
    await message.answer(f'<b>Telegram identity</b>\nUser ID: <code>{message.from_user.id}</code>\nChat ID: <code>{message.chat.id}</code>\nUsername: <code>{username}</code>')

@router.callback_query(F.data.startswith('lang:'))
async def select_language(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    lang = 'en' if callback.data.endswith(':en') else 'fa'
    if callback.from_user:
        await sync_telegram_user(callback.from_user, language=lang)
        async with SessionLocal() as session:
            await set_user_language(session, callback.from_user.id, lang)
    await callback.message.answer(tr('welcome', lang), reply_markup=main_menu(lang))
    await callback.answer()

@router.message(F.text.in_({BUTTONS['fa']['menu'], BUTTONS['en']['menu']}))
async def show_main_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await message_language(message)
    await message.answer(tr('welcome', lang), reply_markup=main_menu(lang))

@router.message(F.text.in_({BUTTONS['fa']['games'], BUTTONS['en']['games']}))
async def show_games(message: Message) -> None:
    lang = await message_language(message)
    games = [p for p in game_registry.all() if feature_flags.game_enabled(p.game_id) and feature_flags.game_visible(p.game_id)]
    if not games:
        await message.answer('No game is currently available.' if lang == 'en' else localized_literal('telegram.routers.start.8af91d2a7a30'))
        return
    await message.answer(tr('choose_game', lang), reply_markup=games_keyboard(games, lang))

@router.callback_query(F.data.startswith('game:'))
async def open_game(callback: CallbackQuery) -> None:
    game_id = callback.data.split(':', 1)[1]
    plugin = game_registry.get(game_id)
    lang = await _callback_language(callback)
    if not feature_flags.game_enabled(game_id) or not feature_flags.game_visible(game_id):
        await callback.answer('Game is unavailable' if lang == 'en' else localized_literal('telegram.routers.start.72b72d52b233'), show_alert=True)
        return
    name = plugin.display_name_en if lang == 'en' else plugin.display_name_fa
    if game_id == "kintara":
        text = (
            f"<b>{name}</b>\n\nChoose a service or open Come To Molten."
            if lang == "en"
            else localized_literal("kintara.ui.game_intro")
        )
    else:
        text = (
            f"<b>{name}</b>\n\nConnect a game account or view available plans."
            if lang == "en"
            else f"<b>{name}{localized_literal('telegram.routers.start.b2787cb51ad1')}"
        )
    await callback.message.answer(text, reply_markup=game_actions(game_id, lang=lang, trial_enabled=plugin.trial().enabled))
    await callback.answer()

@router.message(F.text.in_({BUTTONS['fa']['support'], BUTTONS['en']['support']}))
async def support(message: Message) -> None:
    lang = await message_language(message)
    text = '<b>Support</b>\n\nFor payment, activation, or service problems, contact the support center.' if lang == 'en' else localized_literal('telegram.routers.start.b632e9916531')
    await message.answer(text, reply_markup=support_link(runtime_settings.support_url(), lang))

@router.message(F.text.in_({BUTTONS['fa']['guide'], BUTTONS['en']['guide']}))
async def service_guide(message: Message) -> None:
    lang = await message_language(message)
    if lang == 'en':
        text = (
            '<b>Service Guide</b>\n\n'
            '1. Choose the game and the service you need.\n'
            '2. Complete the payment and send the transaction hash.\n'
            '3. After final approval, follow the secure account-connection guide.\n'
            '4. Your service starts automatically after the account is connected.'
        )
    else:
        text = localized_literal('ui.guide.service')
    await message.answer(text, reply_markup=main_menu(lang))

@router.message(F.text.in_({BUTTONS['fa']['subscription'], BUTTONS['en']['subscription']}))
async def legacy_subscription_home(message: Message) -> None:
    """Keep older reply keyboards working while using the merged account page."""
    await send_my_account(message)

@router.message(F.text.in_({BUTTONS['fa']['settings'], BUTTONS['en']['settings']}))
async def settings_home(message: Message) -> None:
    lang = await message_language(message)
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, message.from_user.id)
        pref = await get_user_preference(session, user.id) if user else None
    state = ('Enabled' if pref and pref.notifications_enabled else 'Disabled') if lang == 'en' else localized_literal('telegram.routers.start.6f637966671d') if pref and pref.notifications_enabled else localized_literal('telegram.routers.start.d9ba41681180')
    text = f"<b>Settings</b>\n\nLanguage: <b>{('English' if lang == 'en' else 'Persian')}</b>\nNotifications: <b>{state}</b>" if lang == 'en' else f"{localized_literal('telegram.routers.start.dd3fd7142829')}{(localized_literal('telegram.routers.start.a0d317fc4712') if lang == 'en' else localized_literal('telegram.routers.start.ef3c392d9d4e'))}{localized_literal('telegram.routers.start.73a11ac9dcd1')}{state}</b>"
    await message.answer(text, reply_markup=settings_menu(lang))

@router.message(F.text.in_({BUTTONS['fa']['change_language'], BUTTONS['en']['change_language']}))
async def change_language(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(tr('language_prompt', 'fa'), reply_markup=language_keyboard())

@router.message(F.text.in_({BUTTONS['fa']['notifications'], BUTTONS['en']['notifications']}))
async def change_notifications(message: Message) -> None:
    lang = await message_language(message)
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, message.from_user.id)
        enabled = await toggle_notifications(session, user.id) if user else False
    text = f"✅ Notifications are now <b>{('enabled' if enabled else 'disabled')}</b>." if lang == 'en' else f"{localized_literal('telegram.routers.start.9920164cad4a')}{(localized_literal('telegram.routers.start.6f637966671d') if enabled else localized_literal('telegram.routers.start.d9ba41681180'))}{localized_literal('telegram.routers.start.811479497be5')}"
    await message.answer(text, reply_markup=settings_menu(lang))

async def _callback_language(callback: CallbackQuery) -> str:
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
    return 'en' if user and user.language == 'en' else 'fa'
