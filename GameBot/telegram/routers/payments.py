from __future__ import annotations
from core.locale_text import localized_literal
from decimal import Decimal
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from core.config import settings
from core.feature_flags import feature_flags
from core.runtime_settings import runtime_settings
from core.database import SessionLocal
from core.models import OrderStatus
from core.payment_service import PaymentMonitor
from core.payment_verifier import CryptoPaymentVerifier
from core.registry import game_registry
from core.repositories import attach_transaction, claim_trial, create_crypto_order, get_account, get_crypto_order, get_user_by_telegram, list_accounts
from core.worker_manager import WorkerManager
from core.time_utils import display_datetime
from telegram.helpers import message_language
from telegram.keyboards import BUTTONS, account_select_keyboard, main_menu, network_keyboard, configured_payment_networks, plans_keyboard, kintara_plans_keyboard
router = Router(name='payments')

class PaymentFlow(StatesGroup):
    waiting_transaction = State()


async def _send_kintara_plans(message: Message, lang: str) -> None:
    plugin = game_registry.get("kintara")
    if lang == "en":
        text = "<b>Kintara services</b>\n\nChoose a service. Payment is completed before account connection information is requested."
    else:
        text = localized_literal("kintara.purchase.plans_short")
    await message.answer(text, reply_markup=kintara_plans_keyboard(plugin.plans(), lang))

@router.message(F.text.in_({BUTTONS['fa']['plans'], BUTTONS['en']['plans']}))
async def choose_plan_home(message: Message) -> None:
    """Keep old keyboards compatible while routing every service flow through Games."""
    lang = await message_language(message)
    plugins = [
        plugin
        for plugin in game_registry.all()
        if feature_flags.game_enabled(plugin.game_id)
        and feature_flags.game_visible(plugin.game_id)
    ]
    if not plugins:
        await message.answer(
            'No game is currently available.'
            if lang == 'en'
            else localized_literal('telegram.routers.start.8af91d2a7a30')
        )
        return
    from telegram.keyboards import games_keyboard
    await message.answer(
        'Choose a game:'
        if lang == 'en'
        else localized_literal('telegram.routers.payments.d45a10bf32a1'),
        reply_markup=games_keyboard(plugins, lang),
    )

@router.callback_query(F.data.startswith('plans:'))
async def show_plans(callback: CallbackQuery) -> None:
    game_id = callback.data.split(':', 1)[1]
    lang = await _callback_language(callback)
    if game_id == "kintara":
        await _send_kintara_plans(callback.message, lang)
    else:
        await _send_plans(callback.message, game_id, lang)
    await callback.answer()

async def _send_plans(message: Message, game_id: str, lang: str) -> None:
    if not feature_flags.game_enabled(game_id) or not feature_flags.game_visible(game_id):
        await message.answer('This game is unavailable.' if lang == 'en' else localized_literal('telegram.routers.payments.d2396ab9189d'))
        return
    plugin = game_registry.get(game_id)
    name = plugin.display_name_en if lang == 'en' else plugin.display_name_fa
    lines = [f"<b>{name} — {('Plans' if lang == 'en' else localized_literal('telegram.routers.payments.8b311a528325'))}</b>"]
    for plan in plugin.plans():
        features = plugin.visible_features(plan, lang)
        feature_text = localized_literal('telegram.routers.payments.8715d7bc598d').join(features) if features else 'Base service' if lang == 'en' else localized_literal('telegram.routers.payments.94824f94ffcc')
        lines.append(f"\n• <b>{(plan.label_en if lang == 'en' else plan.label_fa)}</b>\n{('Price' if lang == 'en' else localized_literal('telegram.routers.payments.f5668e5b2c4a'))}: <b>{plan.price_usdc} USDC</b>\n{('Duration' if lang == 'en' else localized_literal('telegram.routers.payments.c46aff053990'))}: <b>{plan.duration_days} {('days' if lang == 'en' else localized_literal('telegram.routers.payments.c48a4b443df5'))}</b>\n{('Features' if lang == 'en' else localized_literal('telegram.routers.payments.7bc5ab805b73'))}: <b>{feature_text}</b>")
    trial = plugin.trial()
    if trial.enabled:
        lines.append(f"\n🎁 {('Free trial is available.' if lang == 'en' else localized_literal('telegram.routers.payments.ab9bce0a0fe2'))}")
    await message.answer('\n'.join(lines), reply_markup=plans_keyboard(game_id, plugin.plans(), lang, trial_enabled=trial.enabled))

@router.callback_query(F.data.startswith('buy:'))
async def choose_account_for_purchase(callback: CallbackQuery) -> None:
    _, game_id, plan_key = callback.data.split(':', 2)
    lang = await _callback_language(callback)
    if not feature_flags.game_enabled(game_id) or not feature_flags.game_visible(game_id):
        await callback.answer('Game is unavailable' if lang == 'en' else localized_literal('telegram.routers.payments.72b72d52b233'), show_alert=True)
        return
    plugin = game_registry.get(game_id)
    if not any((plan.key == plan_key for plan in plugin.plans())):
        await callback.answer('Plan is unavailable' if lang == 'en' else localized_literal('telegram.routers.payments.476f42cc0e70'), show_alert=True)
        return
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
        accounts = await list_accounts(session, user.id, game_id) if user else []
    if not accounts:
        await callback.message.answer('Add a game account before purchasing a plan.' if lang == 'en' else localized_literal('telegram.routers.payments.be3004adb15e'))
        await callback.answer()
        return
    if not configured_payment_networks():
        await callback.message.answer('Crypto payment networks are not configured. Contact support.' if lang == 'en' else localized_literal('telegram.routers.payments.1a59b3da3fdc'))
        await callback.answer()
        return
    if len(accounts) == 1:
        await callback.message.answer('Choose the payment network:' if lang == 'en' else localized_literal('telegram.routers.payments.f9b711123044'), reply_markup=network_keyboard(accounts[0].id, plan_key, lang))
    else:
        await callback.message.answer('Choose the account for this plan:' if lang == 'en' else localized_literal('telegram.routers.payments.26784d6c6d39'), reply_markup=account_select_keyboard(accounts, 'payacct', plan_key))
    await callback.answer()

@router.callback_query(F.data.startswith('payacct:'))
async def choose_network_after_account(callback: CallbackQuery) -> None:
    _, account_id, plan_key = callback.data.split(':', 2)
    lang = await _callback_language(callback)
    if not configured_payment_networks():
        await callback.message.answer('Crypto payment networks are not configured. Contact support.' if lang == 'en' else localized_literal('telegram.routers.payments.1a59b3da3fdc'))
        await callback.answer()
        return
    await callback.message.answer('Choose the payment network:' if lang == 'en' else localized_literal('telegram.routers.payments.f9b711123044'), reply_markup=network_keyboard(int(account_id), plan_key, lang))
    await callback.answer()

@router.callback_query(F.data.startswith('paynet:'))
async def create_order(callback: CallbackQuery, state: FSMContext) -> None:
    _, account_id_raw, plan_key, network_short = callback.data.split(':', 3)
    account_id = int(account_id_raw)
    lang = await _callback_language(callback)
    network = 'solana_usdc' if network_short == 'sol' else 'base_usdc'
    payment_network = runtime_settings.payment_network(network)
    wallet = str(payment_network.get('wallet') or '')
    if not payment_network.get('enabled') or not wallet or (not payment_network.get('token')):
        await callback.message.answer('Payment wallet is not configured. Contact support.' if lang == 'en' else localized_literal('telegram.routers.payments.ee67ab351522'))
        await callback.answer()
        return
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        user = await get_user_by_telegram(session, callback.from_user.id)
        if account is None or user is None or account.user_id != user.id:
            await callback.answer('Invalid access' if lang == 'en' else localized_literal('telegram.routers.payments.4a3e74bfeb30'), show_alert=True)
            return
        if not feature_flags.game_enabled(account.game_id) or not feature_flags.game_visible(account.game_id):
            await callback.answer('Game is unavailable' if lang == 'en' else localized_literal('telegram.routers.payments.72b72d52b233'), show_alert=True)
            return
        plugin = game_registry.get(account.game_id)
        plan = next((x for x in plugin.plans() if x.key == plan_key), None)
        if plan is None:
            await callback.answer('Plan not found' if lang == 'en' else localized_literal('telegram.routers.payments.78b6714d45ac'), show_alert=True)
            return
        order = await create_crypto_order(session, telegram_user_id=callback.from_user.id, account_id=account.id, game_id=account.game_id, plan_key=plan.key, network=network, destination_wallet=wallet, amount_usdc=plan.price_usdc)
    await state.set_state(PaymentFlow.waiting_transaction)
    await state.update_data(order_code=order.order_code)
    network_label = 'USDC Solana' if network == 'solana_usdc' else 'USDC Base'
    text = f'<b>Crypto Payment</b>\n\nOrder: <code>{order.order_code}</code>\nAmount: <b>{order.amount_usdc} USDC</b>\nNetwork: <b>{network_label}</b>\n\nWallet:\n<code>{wallet}</code>\n\nSend only USDC on this exact network, then send the transaction hash here.' if lang == 'en' else f"{localized_literal('telegram.routers.payments.a9334ea1bcfb')}{order.order_code}{localized_literal('telegram.routers.payments.2cf690fb2ce6')}{order.amount_usdc}{localized_literal('telegram.routers.payments.8f8a036b8499')}{network_label}{localized_literal('telegram.routers.payments.f072ffa9dc90')}{wallet}{localized_literal('telegram.routers.payments.7c29f94cf279')}"
    await callback.message.answer(text)
    await callback.answer()

@router.message(PaymentFlow.waiting_transaction)
async def receive_transaction(message: Message, state: FSMContext, payment_monitor: PaymentMonitor) -> None:
    lang = await message_language(message)
    data = await state.get_data()
    order_code = str(data.get('order_code') or '')
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        if order is None or order.telegram_user_id != message.from_user.id:
            await state.clear()
            await message.answer('Order not found.' if lang == 'en' else localized_literal('telegram.routers.payments.a073b87c2875'))
            return
        try:
            tx_hash = CryptoPaymentVerifier.normalize_tx_hash(order.network, message.text or '')
            await attach_transaction(session, order, tx_hash)
        except ValueError as exc:
            code = str(exc)
            if code == 'duplicate_transaction':
                text = 'This transaction hash was already used.' if lang == 'en' else localized_literal('telegram.routers.payments.8a84dbd9c660')
            else:
                text = 'The transaction hash format is invalid.' if lang == 'en' else localized_literal('telegram.routers.payments.ded56f92e909')
            await message.answer(text)
            return
    status, detail = await payment_monitor.verify_order(order_code)
    await state.clear()
    if status == 'passed':
        text = '✅ Payment verified and service activated.' if lang == 'en' else localized_literal('telegram.routers.payments.f44b94e9f74d')
    elif status == 'awaiting_admin':
        text = '✅ Transaction received and checked. The order is waiting for final administrator approval; the service is not active yet.' if lang == 'en' else localized_literal('telegram.routers.payments.147e8768b58e')
    elif status == 'pending':
        text = '⏳ Transaction received. Network verification will continue and the administrator has been notified.' if lang == 'en' else localized_literal('telegram.routers.payments.e1c4300d19d8')
    else:
        text = f'⚠️ Payment verification failed: {detail}' if lang == 'en' else f"{localized_literal('telegram.routers.payments.a943a0c7f5e1')}{detail}"
    await message.answer(text, reply_markup=main_menu(lang))

@router.callback_query(F.data == 'payments:cancel')
async def cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    lang = await _callback_language(callback)
    await callback.message.answer('Payment flow cancelled.' if lang == 'en' else localized_literal('telegram.routers.payments.d898faea4afd'), reply_markup=main_menu(lang))
    await callback.answer()

@router.callback_query(F.data.startswith('trial:'))
async def choose_trial_account(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    game_id = callback.data.split(':', 1)[1]
    lang = await _callback_language(callback)
    plugin = game_registry.get(game_id)
    if not feature_flags.game_enabled(game_id):
        await callback.answer('Game is disabled' if lang == 'en' else localized_literal('telegram.routers.payments.60257f2c154e'), show_alert=True)
        return
    if not plugin.trial().enabled:
        await callback.answer('Trial is disabled' if lang == 'en' else localized_literal('telegram.routers.payments.1678c056fbd5'), show_alert=True)
        return
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
        accounts = await list_accounts(session, user.id, game_id) if user else []
    if not accounts:
        await callback.message.answer('Add an account first.' if lang == 'en' else localized_literal('telegram.routers.payments.7ca5d1f8d327'))
    elif len(accounts) == 1:
        await _activate_trial(callback, accounts[0].id, worker_manager)
        return
    else:
        await callback.message.answer('Choose an account:' if lang == 'en' else localized_literal('telegram.routers.payments.c813e28e7e03'), reply_markup=account_select_keyboard(accounts, 'trialacct'))
    await callback.answer()

@router.callback_query(F.data.startswith('trialacct:'))
async def activate_trial_callback(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    account_id = int(callback.data.split(':', 1)[1])
    await _activate_trial(callback, account_id, worker_manager)

async def _activate_trial(callback: CallbackQuery, account_id: int, worker_manager: WorkerManager) -> None:
    lang = await _callback_language(callback)
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
        account = await get_account(session, account_id)
        if user is None or account is None or account.user_id != user.id:
            await callback.answer('Invalid access' if lang == 'en' else localized_literal('telegram.routers.payments.4a3e74bfeb30'), show_alert=True)
            return
        plugin = game_registry.get(account.game_id)
        trial = plugin.trial()
        try:
            subscription = await claim_trial(session, game_id=account.game_id, telegram_user_id=callback.from_user.id, account=account, plan_key=trial.plan_key, duration_minutes=trial.duration_minutes, slot_limit=trial.slot_limit)
        except ValueError as exc:
            if str(exc) == 'trial_capacity_full':
                text = 'Free-trial capacity is full.' if lang == 'en' else localized_literal('telegram.routers.payments.2a3ea73ed4fb')
            elif str(exc) == 'active_subscription':
                text = 'This account already has an active subscription.' if lang == 'en' else localized_literal('telegram.routers.payments.5627e1e7b740')
            else:
                text = 'The free trial was already used for this user or game account.' if lang == 'en' else localized_literal('telegram.routers.payments.2550ec0921c8')
            await callback.message.answer(f'❌ {text}')
            await callback.answer()
            return
    started, start_text = await worker_manager.start_account(account_id)
    await callback.message.answer(f"🎁 <b>Free trial activated</b>\nExpires: <b>{display_datetime(subscription.expires_at, lang)}</b>\nService: <b>{('started automatically' if started else start_text)}</b>" if lang == 'en' else f"{localized_literal('telegram.routers.payments.23dc356b4b8f')}{display_datetime(subscription.expires_at, lang)}{localized_literal('telegram.routers.payments.b52e4c4abb94')}{(localized_literal('telegram.routers.payments.fefc7f5231b5') if started else start_text)}</b>")
    await callback.answer()

async def _callback_language(callback: CallbackQuery) -> str:
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, callback.from_user.id)
    return 'en' if user and user.language == 'en' else 'fa'
