from __future__ import annotations

import html

from aiogram.types import Message

from core.database import SessionLocal
from core.models import OrderStatus
from core.i18n import tr
from core.locale_text import localized_literal
from core.registry import game_registry
from core.repositories import (
    active_service_entitlement,
    get_user_by_telegram,
    list_accounts,
    list_user_active_subscriptions,
    list_user_orders,
)
from core.time_utils import display_datetime
from games.kintara.molten.access import SERVICE_KEY as COME_TO_MOLTEN_SERVICE_KEY
from telegram.helpers import message_language
from telegram.keyboards import account_actions, main_menu, pending_connection_keyboard


def _account_status(status: str, lang: str) -> str:
    labels_en = {
        "running": "Running",
        "ready": "Ready",
        "stopped": "Paused",
        "error": "Needs attention",
        "disabled": "Unavailable",
        "pending": "Preparing",
    }
    if lang == "en":
        return labels_en.get(str(status), "Ready")
    key = {
        "running": "ui.account.status.running",
        "ready": "ui.account.status.ready",
        "stopped": "ui.account.status.stopped",
        "error": "ui.account.status.error",
        "disabled": "ui.account.status.disabled",
        "pending": "ui.account.status.pending",
    }.get(str(status), "ui.account.status.ready")
    return localized_literal(key)


def _order_status(status: str, lang: str) -> str:
    labels_en = {
        "awaiting_tx": "Waiting for payment",
        "pending": "Payment is being checked",
        "awaiting_admin": "Waiting for final approval",
        "awaiting_credential": "Waiting for account connection",
        "verified": "Completed",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
    }
    if lang == "en":
        return labels_en.get(status, status.replace("_", " ").title())
    key = {
        "awaiting_tx": "ui.order.status.awaiting_tx",
        "pending": "ui.order.status.pending",
        "awaiting_admin": "ui.order.status.awaiting_admin",
        "awaiting_credential": "ui.order.status.awaiting_credential",
        "verified": "ui.order.status.verified",
        "rejected": "ui.order.status.rejected",
        "cancelled": "ui.order.status.cancelled",
    }.get(status)
    return localized_literal(key) if key else status


def _plan_label(game_id: str, plan_key: str, lang: str) -> str:
    try:
        plugin = game_registry.get(game_id)
        plan = next((row for row in plugin.all_plans() if row.key == plan_key), None)
    except Exception:
        plan = None
    if plan is None:
        return plan_key.replace("_", " ").title()
    if game_id == "kintara" and plan_key == "molten_access":
        return "Come To Molten"
    return plan.label_en if lang == "en" else plan.label_fa


async def send_my_account(message: Message) -> None:
    lang = await message_language(message)
    if not message.from_user:
        return

    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, message.from_user.id)
        if user is None:
            await message.answer(
                "Send /start first." if lang == "en" else localized_literal("telegram.routers.accounts.3588b8b0ea9c")
            )
            return
        accounts = await list_accounts(session, user.id)
        active_rows = await list_user_active_subscriptions(session, user.id)
        orders = await list_user_orders(session, message.from_user.id, limit=20)
        latest_orders = orders[:1]
        pending_connection_order = next(
            (
                order
                for order in orders
                if order.game_id == "kintara"
                and order.status == OrderStatus.AWAITING_CREDENTIAL.value
            ),
            None,
        )
        come_to_molten_access = await active_service_entitlement(
            session,
            user_id=user.id,
            service_key=COME_TO_MOLTEN_SERVICE_KEY,
        )

    subscriptions = {account.id: subscription for account, subscription in active_rows}
    title = "<b>My Account</b>" if lang == "en" else localized_literal("ui.account.home.title")
    overview: list[str] = [title]

    if come_to_molten_access is not None:
        if come_to_molten_access.expires_at is None:
            validity = "Active" if lang == "en" else localized_literal("ui.account.active")
        else:
            validity = display_datetime(come_to_molten_access.expires_at, lang)
        if lang == "en":
            overview.append(f"\n🔥 <b>Come To Molten</b>\nAccess: <b>{validity}</b>")
        else:
            overview.append(
                localized_literal("ui.account.come_to_molten").format(validity=validity)
            )

    if latest_orders:
        order = latest_orders[0]
        status = _order_status(order.status, lang)
        service = _plan_label(order.game_id, order.plan_key, lang)
        if lang == "en":
            overview.append(
                f"\n<b>Latest request</b>\nService: <b>{html.escape(service)}</b>\nStatus: <b>{html.escape(status)}</b>"
            )
        else:
            overview.append(
                localized_literal("ui.account.latest_order").format(
                    service=html.escape(service),
                    status=html.escape(status),
                )
            )

    if not accounts and come_to_molten_access is None and not latest_orders:
        overview.append(
            "\nNo active service is connected yet." if lang == "en" else localized_literal("ui.account.empty")
        )

    await message.answer("\n".join(overview), reply_markup=main_menu(lang))

    if pending_connection_order is not None:
        service = _plan_label(
            pending_connection_order.game_id,
            pending_connection_order.plan_key,
            lang,
        )
        if lang == "en":
            pending_text = (
                "<b>Account setup is not finished</b>\n\n"
                f"Service: <b>{html.escape(service)}</b>\n"
                "Your approved order is saved. Continue the game connection whenever you are ready. "
                "You do not need to pay again."
            )
        else:
            pending_text = localized_literal("kintara.purchase.connection_pending").format(
                service=html.escape(service)
            )
        await message.answer(
            pending_text,
            reply_markup=pending_connection_keyboard(pending_connection_order.order_code, lang),
        )

    for account in accounts:
        plugin = game_registry.get(account.game_id)
        game_name = plugin.display_name_en if lang == "en" else plugin.display_name_fa
        subscription = subscriptions.get(account.id)
        status = _account_status(account.status, lang)
        if subscription is not None:
            plan = _plan_label(account.game_id, subscription.plan_key, lang)
            expires = display_datetime(subscription.expires_at, lang)
        else:
            plan = "No active service" if lang == "en" else localized_literal("ui.account.no_active_service")
            expires = "-"

        if lang == "en":
            text = (
                f"🎮 <b>{html.escape(game_name)}</b>\n"
                f"Account: <b>{html.escape(account.label)}</b>\n"
                f"Service: <b>{html.escape(plan)}</b>\n"
                f"Valid until: <b>{html.escape(expires)}</b>\n"
                f"Status: <b>{html.escape(status)}</b>"
            )
        else:
            text = localized_literal("ui.account.card").format(
                game=html.escape(game_name),
                account=html.escape(account.label),
                service=html.escape(plan),
                expires=html.escape(expires),
                status=html.escape(status),
            )
        await message.answer(
            text,
            reply_markup=account_actions(account.id, account.status == "running", lang, game_id=account.game_id),
        )
