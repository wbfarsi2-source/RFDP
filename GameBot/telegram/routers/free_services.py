from __future__ import annotations
from core.locale_text import localized_literal
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from core.database import SessionLocal
from core.repositories import disable_shared_service_access, enable_shared_service_access, get_user_by_telegram, update_shared_service_message
from core.runtime_settings import runtime_settings
from core.shared_service_manager import KINTARA_EMBER_SERVICE_KEY, SharedServiceManager
from core.shared_service_store import shared_service_store
from games.kintara.ember_view import format_ember_snapshot, format_ember_waiting
from telegram.helpers import message_language, telegram_language
from telegram.keyboards import BUTTONS, ember_access_keyboard, main_menu
router = Router(name='free_services')

def _available() -> bool:
    return runtime_settings.ember_enabled() and runtime_settings.ember_visible()

async def _current_text(lang: str) -> str:
    snapshot = shared_service_store.read_snapshot(KINTARA_EMBER_SERVICE_KEY)
    if snapshot:
        return format_ember_snapshot(snapshot, lang)
    return format_ember_waiting(lang)

async def _activate_access(*, target_message: Message, telegram_user_id: int, lang: str, shared_service_manager: SharedServiceManager) -> None:
    if not _available():
        await target_message.answer('The free Ember monitor is currently unavailable.' if lang == 'en' else localized_literal('telegram.routers.free_services.650fa9eda796'), reply_markup=main_menu(lang))
        return
    workspace = shared_service_manager.provision_ember_workspace()
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, telegram_user_id)
        if user is None:
            await target_message.answer('Send /start first.' if lang == 'en' else localized_literal('telegram.routers.free_services.3588b8b0ea9c'))
            return
        access = await enable_shared_service_access(session, user_id=user.id, service_key=KINTARA_EMBER_SERVICE_KEY, chat_id=target_message.chat.id)
    status = shared_service_manager.ember_status()
    if not status.get('running'):
        await shared_service_manager.start_ember(reset_restart=False)
        status = shared_service_manager.ember_status()
    if not status.get('configured'):
        text = '🔥 <b>Free Ember access enabled.</b>\n\nThe shared service workspace was created, but the administrator must add the central Kintara cookie. This message will update automatically after the central process starts.' if lang == 'en' else localized_literal('telegram.routers.free_services.bcd1b679ea16')
    else:
        text = await _current_text(lang)
    sent = await target_message.answer(text, reply_markup=ember_access_keyboard(lang, True))
    snapshot = shared_service_store.read_snapshot(KINTARA_EMBER_SERVICE_KEY)
    async with SessionLocal() as session:
        await update_shared_service_message(session, access_id=access.id, chat_id=sent.chat.id, message_id=sent.message_id, snapshot_version=str(snapshot.get('version') or ''))

@router.message(F.text.in_({BUTTONS['fa']['ember'], BUTTONS['en']['ember']}))
async def open_free_ember(message: Message, shared_service_manager: SharedServiceManager) -> None:
    if not message.from_user:
        return
    await _activate_access(target_message=message, telegram_user_id=message.from_user.id, lang=await message_language(message), shared_service_manager=shared_service_manager)

@router.callback_query(F.data == 'ember:open')
async def open_free_ember_callback(callback: CallbackQuery, shared_service_manager: SharedServiceManager) -> None:
    if not callback.from_user or not callback.message:
        return
    await _activate_access(target_message=callback.message, telegram_user_id=callback.from_user.id, lang=await telegram_language(callback.from_user.id), shared_service_manager=shared_service_manager)
    await callback.answer()

@router.callback_query(F.data == 'ember:refresh')
async def refresh_free_ember(callback: CallbackQuery, shared_service_manager: SharedServiceManager) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await telegram_language(callback.from_user.id)
    if not _available():
        await callback.answer('Service unavailable' if lang == 'en' else localized_literal('telegram.routers.free_services.a2a7a241beb6'), show_alert=True)
        return
    if not shared_service_manager.ember_status().get('running'):
        await shared_service_manager.start_ember(reset_restart=False)
    text = await _current_text(lang)
    try:
        await callback.message.edit_text(text, reply_markup=ember_access_keyboard(lang, True))
    except Exception:
        await callback.message.answer(text, reply_markup=ember_access_keyboard(lang, True))
    await callback.answer('Updated' if lang == 'en' else localized_literal('telegram.routers.free_services.95fba6ae3441'))

@router.callback_query(F.data == 'ember:enable')
async def enable_free_ember(callback: CallbackQuery, shared_service_manager: SharedServiceManager) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await telegram_language(callback.from_user.id)
    if not _available():
        await callback.answer('Service unavailable' if lang == 'en' else localized_literal('telegram.routers.free_services.a2a7a241beb6'), show_alert=True)
        return

    shared_service_manager.provision_ember_workspace()
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
        if user is None:
            await callback.answer('Send /start first.' if lang == 'en' else localized_literal('telegram.routers.free_services.3588b8b0ea9c'), show_alert=True)
            return
        access = await enable_shared_service_access(
            session,
            user_id=user.id,
            service_key=KINTARA_EMBER_SERVICE_KEY,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )

    status = shared_service_manager.ember_status()
    if not status.get('running'):
        await shared_service_manager.start_ember(reset_restart=False)
        status = shared_service_manager.ember_status()

    if not status.get('configured'):
        text = '🔥 <b>Free Ember access enabled.</b>\n\nThe shared service is waiting for the administrator to configure the central Kintara cookie.' if lang == 'en' else localized_literal('telegram.routers.free_services.bcd1b679ea16')
    else:
        text = await _current_text(lang)

    sent_message = callback.message
    try:
        await callback.message.edit_text(text, reply_markup=ember_access_keyboard(lang, True))
    except Exception:
        sent_message = await callback.message.answer(text, reply_markup=ember_access_keyboard(lang, True))

    snapshot = shared_service_store.read_snapshot(KINTARA_EMBER_SERVICE_KEY)
    async with SessionLocal() as session:
        await update_shared_service_message(
            session,
            access_id=access.id,
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
            snapshot_version=str(snapshot.get('version') or ''),
        )
    await callback.answer('Enabled' if lang == 'en' else localized_literal('telegram.routers.free_services.ember_enabled_toast'))

@router.callback_query(F.data == 'ember:disable')
async def disable_free_ember(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await telegram_language(callback.from_user.id)
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
        if user:
            await disable_shared_service_access(session, user_id=user.id, service_key=KINTARA_EMBER_SERVICE_KEY)
    text = 'Ember updates are disabled for you. Use the Enable button below whenever you want to turn them back on.' if lang == 'en' else localized_literal('telegram.routers.free_services.e08d1f1ca28f')
    try:
        await callback.message.edit_text(text, reply_markup=ember_access_keyboard(lang, False))
    except Exception:
        await callback.message.answer(text, reply_markup=ember_access_keyboard(lang, False))
    await callback.answer('Disabled' if lang == 'en' else localized_literal('telegram.routers.free_services.ember_disabled_toast'))
