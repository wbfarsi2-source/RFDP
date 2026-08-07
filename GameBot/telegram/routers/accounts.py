from __future__ import annotations
from core.locale_text import localized_literal
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from core.crypto import CredentialVault
from core.feature_flags import feature_flags
from core.instance_store import instance_store
from core.database import SessionLocal
from core.models import GameAccount, User
from core.registry import game_registry
from core.repositories import get_account, get_user_by_telegram, list_accounts, stable_external_hash
from core.worker_manager import WorkerManager
from telegram.account_view import send_my_account
from telegram.helpers import message_language
from telegram.keyboards import BUTTONS, main_menu
router = Router(name='accounts')

class AddAccountFlow(StatesGroup):
    waiting_credential = State()

async def current_user(session, telegram_user_id: int) -> User | None:
    return await get_user_by_telegram(session, telegram_user_id)

@router.callback_query(F.data.startswith('account:add:'))
async def begin_add_account(callback: CallbackQuery, state: FSMContext) -> None:
    game_id = callback.data.split(':', 2)[2]
    lang = await _callback_language(callback)
    if not feature_flags.game_enabled(game_id) or not feature_flags.game_visible(game_id):
        await callback.answer('Game is unavailable' if lang == 'en' else localized_literal('telegram.routers.accounts.72b72d52b233'), show_alert=True)
        return
    if game_id == 'kintara':
        await callback.message.answer(
            'Choose a Kintara service first. Account connection is requested only after payment approval.'
            if lang == 'en'
            else localized_literal('kintara.account.purchase_first')
        )
        await callback.answer()
        return
    await state.set_state(AddAccountFlow.waiting_credential)
    await state.update_data(game_id=game_id)
    text = 'Send the account connection code. The message will be deleted after processing.\n\nFor Kintara, send the Cookie or the <code>eyJ...</code> value.' if lang == 'en' else localized_literal('telegram.routers.accounts.e1e77f97270f')
    await callback.message.answer(text)
    await callback.answer()

@router.message(AddAccountFlow.waiting_credential)
async def save_account(message: Message, state: FSMContext) -> None:
    lang = await message_language(message)
    data = await state.get_data()
    game_id = str(data.get('game_id') or '')
    plugin = game_registry.get(game_id)
    if not feature_flags.game_enabled(game_id):
        await state.clear()
        await message.answer('This game is disabled.' if lang == 'en' else localized_literal('telegram.routers.accounts.e09ba1a1dd75'))
        return
    raw = message.text or ''
    try:
        await message.delete()
    except Exception:
        pass
    result = await plugin.validate_credentials(raw)
    if not result.valid or not result.normalized:
        await message.answer(f"❌ {result.error or ('Invalid connection information.' if lang == 'en' else localized_literal('telegram.routers.accounts.d4992b905b66'))}")
        return
    try:
        ciphertext = CredentialVault().encrypt(result.normalized)
    except RuntimeError as exc:
        await message.answer(f'❌ <code>{exc}</code>')
        await state.clear()
        return
    async with SessionLocal() as session:
        user = await current_user(session, message.from_user.id)
        if user is None:
            await message.answer('Send /start first.' if lang == 'en' else localized_literal('telegram.routers.accounts.3588b8b0ea9c'))
            await state.clear()
            return
        external_hash = stable_external_hash(game_id, result.external_id)
        exists = await session.scalar(select(GameAccount).where(GameAccount.user_id == user.id, GameAccount.game_id == game_id, GameAccount.external_account_hash == external_hash))
        if exists:
            exists.credential_ciphertext = ciphertext
            exists.credential_hint = result.hint
            exists.label = result.display_name or exists.label
            exists.status = 'ready'
            account = exists
        else:
            account = GameAccount(user_id=user.id, game_id=game_id, label=result.display_name or f'{plugin.display_name_en} Account', external_account_hash=external_hash, credential_ciphertext=ciphertext, credential_hint=result.hint, status='ready')
            session.add(account)
        await session.commit()
        await session.refresh(account)
    await state.clear()
    await message.answer(f'✅ Account <b>{account.label}</b> was saved.\nChoose a plan or activate the free trial.' if lang == 'en' else f"{localized_literal('telegram.routers.accounts.9e484a6cb1fd')}{account.label}{localized_literal('telegram.routers.accounts.d98fd1c9f8f6')}", reply_markup=main_menu(lang))

@router.message(F.text.in_({BUTTONS['fa']['accounts'], BUTTONS['en']['accounts'], localized_literal('ui.main.accounts_legacy'), '👤 My Accounts'}))
async def my_account(message: Message) -> None:
    await send_my_account(message)

@router.callback_query(F.data.startswith('account:start:'))
async def start_account(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    account_id = int(callback.data.rsplit(':', 1)[1])
    lang = await _callback_language(callback)
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        user = await current_user(session, callback.from_user.id)
        if account is None or user is None or account.user_id != user.id:
            await callback.answer('Invalid access' if lang == 'en' else localized_literal('telegram.routers.accounts.4a3e74bfeb30'), show_alert=True)
            return
    ok, text = await worker_manager.start_account(account_id)
    await callback.message.answer(('✅ ' if ok else '⚠️ ') + text)
    await callback.answer()

@router.callback_query(F.data.startswith('account:stop:'))
async def stop_account(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    account_id = int(callback.data.rsplit(':', 1)[1])
    lang = await _callback_language(callback)
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        user = await current_user(session, callback.from_user.id)
        if account is None or user is None or account.user_id != user.id:
            await callback.answer('Invalid access' if lang == 'en' else localized_literal('telegram.routers.accounts.4a3e74bfeb30'), show_alert=True)
            return
    ok, text = await worker_manager.stop_account(account_id)
    await callback.message.answer(('✅ ' if ok else '⚠️ ') + text)
    await callback.answer()

@router.callback_query(F.data.startswith('account:delete:'))
async def delete_account(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    account_id = int(callback.data.rsplit(':', 1)[1])
    lang = await _callback_language(callback)
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        user = await current_user(session, callback.from_user.id)
        if account is None or user is None or account.user_id != user.id:
            await callback.answer('Invalid access' if lang == 'en' else localized_literal('telegram.routers.accounts.4a3e74bfeb30'), show_alert=True)
            return
        await worker_manager.stop_account(account_id)
        game_id = account.game_id
        await session.execute(delete(GameAccount).where(GameAccount.id == account_id))
        await session.commit()
    instance_store.delete(game_id, account_id)
    await callback.message.answer('✅ Account and encrypted credentials were deleted.' if lang == 'en' else localized_literal('telegram.routers.accounts.e9bac0693410'))
    await callback.answer()

async def _callback_language(callback: CallbackQuery) -> str:
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
    return 'en' if user and user.language == 'en' else 'fa'
