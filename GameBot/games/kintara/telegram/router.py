from __future__ import annotations

import asyncio
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from core.database import SessionLocal
from core.localization import tr
from core.models import OrderStatus
from core.payment_service import PaymentMonitor
from core.payment_verifier import CryptoPaymentVerifier
from core.repositories import attach_transaction, get_crypto_order, get_user_by_telegram
from core.runtime.shared_services.store import shared_service_store
from core.runtime_settings import runtime_settings
from core.shared_service_manager import SharedServiceManager
from core.time_utils import display_datetime
from core.worker_manager import WorkerManager
from games.kintara.molten.access import SERVICE_KEY, access_mode, ensure_free_access, get_active_access
from games.kintara.molten.channel import MoltenChannelService
from games.kintara.molten.view import format_snapshot
from games.kintara.plugin import KintaraPlugin
from games.kintara.purchases.messages import cookie_guide
from games.kintara.purchases.service import (
    complete_credential_activation,
    create_free_purchase_order,
    create_paid_purchase_order,
    create_trial_order,
    find_plan,
    plan_access_mode,
)
from telegram.account_view import send_my_account
from telegram.helpers import sync_telegram_user, telegram_language
from telegram.keyboards import (
    BUTTONS,
    channel_invite_keyboard,
    credential_prompt_keyboard,
    credential_wait_keyboard,
    kintara_network_keyboard,
    kintara_plans_keyboard,
    main_menu,
    molten_keyboard,
    molten_purchase_keyboard,
)

router = Router(name="kintara")

# BEGIN KINTARA EMBER MANUAL PATCH V1
from aiogram.filters import Command as _EmberManualCommand
from games.kintara.telegram.ember_manual_patch import (
    ember_manual_callback_filter as _ember_manual_callback_filter,
    handle_ember_manual_callback as _handle_ember_manual_callback,
    handle_ember_manual_command as _handle_ember_manual_command,
)

@router.callback_query(_ember_manual_callback_filter)
async def _kintara_ember_manual_update_handler(callback):
    await _handle_ember_manual_callback(callback)

@router.message(_EmberManualCommand("emberscan"))
async def _kintara_ember_manual_command_handler(message):
    await _handle_ember_manual_command(message)
# END KINTARA EMBER MANUAL PATCH V1



class KintaraPurchaseFlow(StatesGroup):
    waiting_transaction = State()
    waiting_credential = State()


async def _language(user_id: int) -> str:
    return await telegram_language(user_id)


async def _ensure_callback_user(callback: CallbackQuery):
    """Ensure Telegram callbacks always have a local GameBot user record.

    This removes the fragile requirement that the user must manually send /start
    again after a database restore or interrupted migration.
    """
    if callback.from_user is None:
        return None
    return await sync_telegram_user(callback.from_user)


async def _plans_text(lang: str) -> str:
    plugin = KintaraPlugin()
    lines = [
        tr(lang, "kintara.purchase.plans_title", "<b>Kintara services</b>"),
        "",
        tr(lang, "kintara.purchase.plans_intro", "Choose the service you need."),
    ]
    for plan in plugin.plans():
        if plan.runtime_kind != "account":
            continue
        mode = plan_access_mode(plan.key)
        label = plan.label_en if lang == "en" else plan.label_fa
        features = ", ".join(plugin.visible_features(plan, lang))
        detail = f"{plan.duration_days} {tr(lang, 'ui.days', 'days')}"
        if mode == "paid":
            detail = f"{plan.price_usdc} USDC | {detail}"
        lines.extend(["", f"<b>{label}</b>", detail, features])
    return "\n".join(line for line in lines if line is not None)


@router.callback_query(F.data == "kintara:plans")
async def show_plans(callback: CallbackQuery) -> None:
    lang = await _language(callback.from_user.id)
    plugin = KintaraPlugin()
    await callback.message.answer(await _plans_text(lang), reply_markup=kintara_plans_keyboard(plugin.plans(), lang))
    await callback.answer()


@router.callback_query(F.data.startswith("kintara:plan:"))
async def choose_plan(callback: CallbackQuery, state: FSMContext, molten_channel_service: MoltenChannelService) -> None:
    plan_key = callback.data.split(":", 2)[2]
    lang = await _language(callback.from_user.id)
    plan = find_plan(plan_key)
    if plan is None or not runtime_settings.plan_enabled("kintara", plan_key, True):
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return

    mode = plan_access_mode(plan_key)
    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return
    async with SessionLocal() as session:
        order = await create_free_purchase_order(session, user=user, plan=plan) if mode == "free" else None

    if mode == "free":
        if plan.runtime_kind == "shared":
            link = ""
            if molten_channel_service.channel_id:
                try:
                    link = await molten_channel_service.create_personal_invite(user)
                except Exception:
                    link = ""
            await callback.message.answer(
                tr(lang, "kintara.molten.access_activated", "Come To Molten access is active."),
                reply_markup=channel_invite_keyboard(link, lang) if link else molten_keyboard(lang, channel_available=False),
            )
        else:
            await callback.message.answer(cookie_guide(lang), reply_markup=credential_prompt_keyboard(order.order_code, lang))
        await callback.answer()
        return

    if not runtime_settings.configured_payment_networks():
        await callback.message.answer(tr(lang, "kintara.payment.unavailable", "Payment is temporarily unavailable. Contact support."))
        await callback.answer()
        return

    await callback.message.answer(
        tr(lang, "kintara.payment.choose_network", "Choose the payment network."),
        reply_markup=kintara_network_keyboard(plan_key, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("kintara:network:"))
async def create_order(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, plan_key, short_network = callback.data.split(":", 3)
    lang = await _language(callback.from_user.id)
    plan = find_plan(plan_key)
    if plan is None:
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return
    network = "solana_usdc" if short_network == "sol" else "base_usdc"
    payment = runtime_settings.payment_network(network)
    wallet = str(payment.get("wallet") or "")
    if not payment.get("enabled") or not wallet or not payment.get("token"):
        await callback.message.answer(tr(lang, "kintara.payment.network_missing", "This payment network is not configured."))
        await callback.answer()
        return

    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return
    async with SessionLocal() as session:
        order = await create_paid_purchase_order(session, user=user, plan=plan, network=network, wallet=wallet)

    await state.set_state(KintaraPurchaseFlow.waiting_transaction)
    await state.update_data(order_code=order.order_code)
    label = plan.label_en if lang == "en" else plan.label_fa
    network_label = "USDC Solana" if network == "solana_usdc" else "USDC Base"
    await callback.message.answer(
        tr(
            lang,
            "kintara.payment.details",
            "<b>Payment details</b>\n\nService: <b>{service}</b>\nAmount: <b>{amount} USDC</b>\nNetwork: <b>{network}</b>\n\nWallet:\n<code>{wallet}</code>\n\nAfter payment, send the transaction hash here. Kintara account access is requested only after final approval.",
            service=label,
            amount=order.amount_usdc,
            network=network_label,
            wallet=wallet,
        )
    )
    await callback.answer()


@router.message(KintaraPurchaseFlow.waiting_transaction)
async def receive_transaction(message: Message, state: FSMContext, payment_monitor: PaymentMonitor) -> None:
    if not message.from_user:
        return
    lang = await _language(message.from_user.id)
    data = await state.get_data()
    order_code = str(data.get("order_code") or "")
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        if order is None or order.telegram_user_id != message.from_user.id:
            await state.clear()
            await message.answer(tr(lang, "kintara.order.not_found", "Order not found."))
            return
        try:
            tx_hash = CryptoPaymentVerifier.normalize_tx_hash(order.network, message.text or "")
            await attach_transaction(session, order, tx_hash)
        except ValueError as exc:
            key = "kintara.payment.hash_used" if str(exc) == "duplicate_transaction" else "kintara.payment.hash_invalid"
            english = "This transaction hash was already used." if str(exc) == "duplicate_transaction" else "The transaction hash is invalid."
            await message.answer(tr(lang, key, english))
            return

    status, _detail = await payment_monitor.verify_order(order_code)
    await state.clear()
    key = {
        "awaiting_admin": "kintara.payment.waiting_admin",
        "pending": "kintara.payment.pending_network",
    }.get(status, "kintara.payment.received")
    english = {
        "awaiting_admin": "Payment received. Your order is waiting for final approval.",
        "pending": "Payment received. Network verification is still in progress.",
    }.get(status, "Payment received and sent for review.")
    await message.answer(tr(lang, key, english), reply_markup=main_menu(lang))


@router.callback_query(F.data.startswith("kintara:credential:"))
async def begin_credential(callback: CallbackQuery, state: FSMContext) -> None:
    order_code = callback.data.split(":", 2)[2]
    lang = await _language(callback.from_user.id)
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        valid = order is not None and order.telegram_user_id == callback.from_user.id and order.status == OrderStatus.AWAITING_CREDENTIAL.value
    if not valid:
        await callback.answer(tr(lang, "kintara.credential.unavailable", "This activation request is not available."), show_alert=True)
        return
    await state.set_state(KintaraPurchaseFlow.waiting_credential)
    await state.update_data(order_code=order_code)
    await callback.message.answer(
        cookie_guide(lang),
        reply_markup=credential_wait_keyboard(order_code, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("kintara:credential_later:"))
async def postpone_credential(callback: CallbackQuery, state: FSMContext) -> None:
    order_code = callback.data.split(":", 2)[2]
    lang = await _language(callback.from_user.id)
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        valid = (
            order is not None
            and order.telegram_user_id == callback.from_user.id
            and order.status == OrderStatus.AWAITING_CREDENTIAL.value
        )
    await state.clear()
    if not valid:
        await callback.answer(
            tr(lang, "kintara.credential.unavailable", "This activation request is not available."),
            show_alert=True,
        )
        return
    await callback.message.answer(
        tr(
            lang,
            "kintara.purchase.saved_for_later",
            "Your request is saved. Open My Account whenever you are ready to continue.",
        ),
        reply_markup=main_menu(lang),
    )
    await callback.answer()


@router.message(KintaraPurchaseFlow.waiting_credential)
async def receive_credential(message: Message, state: FSMContext, worker_manager: WorkerManager) -> None:
    if not message.from_user:
        return
    lang = await _language(message.from_user.id)
    order_code = str((await state.get_data()).get("order_code") or "")
    raw = (message.text or "").strip()

    account_menu_labels = {
        BUTTONS["fa"]["accounts"],
        BUTTONS["en"]["accounts"],
        BUTTONS["fa"]["subscription"],
        BUTTONS["en"]["subscription"],
        "👤 My Accounts",
    }
    if raw in account_menu_labels:
        await state.clear()
        await send_my_account(message)
        return

    try:
        await message.delete()
    except Exception:
        pass

    if not raw:
        await message.answer(
            tr(
                lang,
                "kintara.credential.empty_retry",
                "No connection information was received. Send it here, or choose Do this later.",
            ),
            reply_markup=credential_wait_keyboard(order_code, lang),
        )
        return

    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        if order is None or order.telegram_user_id != message.from_user.id or order.status != OrderStatus.AWAITING_CREDENTIAL.value:
            await state.clear()
            await message.answer(tr(lang, "kintara.credential.request_missing", "Activation request not found."))
            return
        try:
            account, subscription = await complete_credential_activation(session, order=order, raw_credential=raw)
        except ValueError as exc:
            await message.answer(
                tr(
                    lang,
                    "kintara.credential.rejected_retry",
                    "The connection information was not accepted.\n{reason}\n\nSend it again, or choose Do this later.",
                    reason=str(exc),
                ),
                reply_markup=credential_wait_keyboard(order_code, lang),
            )
            return

    started, detail = await worker_manager.start_account(account.id)
    await state.clear()
    await message.answer(
        tr(
            lang,
            "kintara.activation.success",
            "<b>Service activated</b>\n\nAccount: <b>{account}</b>\nValid until: <b>{expires}</b>\nRuntime: <b>{runtime}</b>",
            account=account.label,
            expires=display_datetime(subscription.expires_at, lang),
            runtime=tr(lang, "ui.runtime.running", "Running") if started else detail,
        ),
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "kintara:trial")
async def start_trial(callback: CallbackQuery) -> None:
    lang = await _language(callback.from_user.id)
    plugin = KintaraPlugin()
    if not plugin.trial().enabled:
        await callback.answer(tr(lang, "kintara.trial.unavailable", "The trial is currently unavailable."), show_alert=True)
        return
    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return
    async with SessionLocal() as session:
        order = await create_trial_order(session, user=user)
    await callback.message.answer(cookie_guide(lang), reply_markup=credential_prompt_keyboard(order.order_code, lang))
    await callback.answer()


async def _ensure_molten_runtime(manager: SharedServiceManager) -> None:
    manager.provision_ember_workspace()
    if not manager.ember_status().get("running"):
        await manager.start_ember(reset_restart=False)


@router.callback_query(F.data == "kintara:molten")
async def open_molten(callback: CallbackQuery, shared_service_manager: SharedServiceManager, molten_channel_service: MoltenChannelService) -> None:
    lang = await _language(callback.from_user.id)
    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.error.unavailable", "This service is currently unavailable."), show_alert=True)
        return

    if access_mode() == "free":
        await ensure_free_access(user)
    if await get_active_access(user.id) is None:
        await callback.message.answer(
            tr(lang, "kintara.molten.subscription_required", "An active Come To Molten subscription is required."),
            reply_markup=molten_purchase_keyboard(lang),
        )
        await callback.answer()
        return

    await _ensure_molten_runtime(shared_service_manager)
    await callback.message.answer(
        tr(lang, "kintara.molten.ready", "Press Refresh to get the current Come To Molten servers."),
        reply_markup=molten_keyboard(lang, channel_available=bool(molten_channel_service.channel_id)),
    )
    await callback.answer()


@router.callback_query(F.data == "kintara:molten_refresh")
async def refresh_molten(callback: CallbackQuery, shared_service_manager: SharedServiceManager, molten_channel_service: MoltenChannelService) -> None:
    lang = await _language(callback.from_user.id)
    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.molten.access_expired", "Access is not active."), show_alert=True)
        return
    if access_mode() == "free":
        await ensure_free_access(user)
    if await get_active_access(user.id) is None:
        await callback.answer(tr(lang, "kintara.molten.access_expired", "Access is not active."), show_alert=True)
        return

    await callback.answer(tr(lang, "kintara.molten.refreshing", "Refreshing current data..."))
    await _ensure_molten_runtime(shared_service_manager)
    request_id = uuid.uuid4().hex
    shared_service_store.request_refresh(SERVICE_KEY, request_id=request_id)
    deadline = asyncio.get_running_loop().time() + 18.0
    snapshot: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.25)
        candidate = shared_service_store.read_snapshot(SERVICE_KEY)
        request_ids = [str(item) for item in (candidate.get("request_ids") or [])]
        if request_id in request_ids:
            snapshot = candidate
            break
    text = format_snapshot(snapshot, lang)
    markup = molten_keyboard(lang, channel_available=bool(molten_channel_service.channel_id))
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "kintara:molten_channel")
async def molten_channel_access(callback: CallbackQuery, molten_channel_service: MoltenChannelService) -> None:
    lang = await _language(callback.from_user.id)
    user = await _ensure_callback_user(callback)
    if user is None:
        await callback.answer(tr(lang, "kintara.molten.access_expired", "Access is not active."), show_alert=True)
        return
    if access_mode() == "free":
        await ensure_free_access(user)
    if await get_active_access(user.id) is None:
        await callback.answer(tr(lang, "kintara.molten.access_expired", "Access is not active."), show_alert=True)
        return
    try:
        link = await molten_channel_service.create_personal_invite(user)
    except Exception:
        await callback.message.answer(tr(lang, "kintara.molten.channel_unavailable", "Channel access is not ready. Contact support."))
        await callback.answer()
        return
    await callback.message.answer(
        tr(lang, "kintara.molten.personal_link", "This link is personal, one-use and expires shortly."),
        reply_markup=channel_invite_keyboard(link, lang),
    )
    await callback.answer()


@router.chat_join_request()
async def guard_molten_join_request(event, molten_channel_service: MoltenChannelService) -> None:
    if not molten_channel_service.channel_id or int(event.chat.id) != molten_channel_service.channel_id:
        return
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, event.from_user.id)
    allowed = user is not None and await get_active_access(user.id) is not None
    if allowed:
        await event.approve()
    else:
        await event.decline()


@router.chat_member()
async def guard_molten_membership(event, molten_channel_service: MoltenChannelService) -> None:
    if not molten_channel_service.channel_id or int(event.chat.id) != molten_channel_service.channel_id:
        return
    member = event.new_chat_member.user
    if member.is_bot:
        return
    status = str(getattr(event.new_chat_member.status, "value", event.new_chat_member.status))
    if status not in {"member", "restricted"}:
        return
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, member.id)
    if user is None or await get_active_access(user.id) is None:
        await molten_channel_service.remove_user(member.id)
