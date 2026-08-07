from __future__ import annotations
from core.locale_text import localized_literal
import asyncio
import html
import json
import logging
from datetime import timedelta
from decimal import Decimal
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from core.config import settings
from core.database import SessionLocal
from core.models import CryptoOrder, OrderStatus
from core.services.payments.verifier import CryptoPaymentVerifier
from core.registry import game_registry
from core.repositories import activate_subscription, get_account, get_user_by_telegram, latest_active_subscription, pending_crypto_orders, set_order_verification
from core.runtime_settings import runtime_settings
from core.worker_manager import WorkerManager
logger = logging.getLogger(__name__)

class PaymentMonitor:
    """Verifies blockchain payments and routes Kintara orders to final admin review."""

    def __init__(self, bot: Bot, worker_manager: WorkerManager) -> None:
        self.bot = bot
        self.worker_manager = worker_manager
        self.verifier = CryptoPaymentVerifier()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._locks: dict[str, asyncio.Lock] = {}

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

    async def verify_order(self, order_code: str) -> tuple[str, str]:
        lock = self._locks.setdefault(order_code, asyncio.Lock())
        async with lock:
            return await self._verify_order_locked(order_code)

    @staticmethod
    def _load_detail(order: CryptoOrder) -> dict:
        try:
            value = json.loads(order.verification_detail_json or '{}')
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _review_keyboard(order_code: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=localized_literal('custom.admin.payment.approve_button'), callback_data=f'admin:order_approve:{order_code}'), InlineKeyboardButton(text=localized_literal('custom.admin.payment.reject_button'), callback_data=f'admin:order_reject:{order_code}')]])

    async def _notify_admins(self, session, order: CryptoOrder, *, review_state: str, detail: dict) -> dict:
        notice_states = list(detail.get('admin_notice_states') or [])
        if review_state in notice_states:
            return detail
        account = await get_account(session, order.account_id)
        user = await get_user_by_telegram(session, order.telegram_user_id)
        username = f"@{user.username.lstrip('@')}" if user and user.username else '-'
        account_label = account.label if account else f'Account {order.account_id}'
        auto_status = str(detail.get('auto_status') or order.status)
        auto_message = str(detail.get('message') or '-')
        tx_hash = str(order.tx_hash or '-')
        text = f"{localized_literal('custom.admin.payment.review_title')}\n\nOrder: <code>{html.escape(order.order_code)}</code>\nUser: <code>{order.telegram_user_id}</code> {html.escape(username)}\nAccount: <code>{order.account_id}</code> — {html.escape(account_label)}\nPlan: <b>{html.escape(order.plan_key)}</b>\nAmount: <b>{html.escape(order.amount_usdc)} USDC</b>\nNetwork: <b>{html.escape(order.network)}</b>\nTransaction: <code>{html.escape(tx_hash)}</code>\nAutomatic check: <b>{html.escape(auto_status)}</b>\nDetail: <code>{html.escape(auto_message[:500])}</code>\n\n{localized_literal('custom.admin.payment.review_footer')}"
        sent_to: list[int] = []
        for admin_id in sorted(settings.admin_user_ids):
            try:
                await self.bot.send_message(admin_id, text, reply_markup=self._review_keyboard(order.order_code))
                sent_to.append(admin_id)
            except Exception:
                logger.exception('Could not send payment review %s to admin %s', order.order_code, admin_id)
        notice_states.append(review_state)
        detail['admin_notice_states'] = notice_states[-10:]
        detail['last_admin_notice_state'] = review_state
        detail['last_admin_notice_recipients'] = sent_to
        return detail

    async def _notify_user_review_state(self, session, order: CryptoOrder, *, review_state: str, detail: dict) -> dict:
        notice_states = list(detail.get('user_notice_states') or [])
        if review_state in notice_states:
            return detail
        user = await get_user_by_telegram(session, order.telegram_user_id)
        language = 'en' if user and user.language == 'en' else 'fa'
        auto_status = str(detail.get('auto_status') or 'pending')
        if auto_status == 'passed':
            text = '✅ <b>The blockchain payment was verified.</b>\nYour order is waiting for final administrator approval. The service is not active yet.' if language == 'en' else localized_literal('core.payment_service.9efbe85cb36e')
        elif auto_status == 'failed':
            text = '⚠️ The automatic payment check found a problem. The order was sent to the administrator for final review.' if language == 'en' else localized_literal('core.payment_service.4c1ba76a1563')
        else:
            text = '⏳ The transaction was received. Network checks will continue and the administrator has been notified.' if language == 'en' else localized_literal('core.payment_service.e1c4300d19d8')
        try:
            await self.bot.send_message(order.telegram_user_id, text)
        except Exception:
            logger.exception('Could not notify user about payment review %s', order.order_code)
        notice_states.append(review_state)
        detail['user_notice_states'] = notice_states[-10:]
        return detail

    async def _save_review_state(self, session, order: CryptoOrder, *, status: str, detail: dict, notice_state: str) -> None:
        await set_order_verification(session, order, status=status, detail=detail)
        detail = await self._notify_admins(session, order, review_state=notice_state, detail=detail)
        detail = await self._notify_user_review_state(session, order, review_state=notice_state, detail=detail)
        await set_order_verification(session, order, status=status, detail=detail)

    async def _activate_verified_order(self, session, order: CryptoOrder, duration_days: int) -> None:
        plugin = game_registry.get(order.game_id)
        plan = next((item for item in plugin.all_plans() if item.key == order.plan_key), None)
        if plan is None or getattr(plan, 'runtime_kind', 'account') == 'shared':
            return
        if order.game_id == 'kintara' and order.status != OrderStatus.VERIFIED.value:
            return
        if await latest_active_subscription(session, order.account_id) is None:
            await activate_subscription(session, account_id=order.account_id, plan_key=order.plan_key, duration=timedelta(days=duration_days))
        await self.worker_manager.start_account(order.account_id)

    async def _verify_order_locked(self, order_code: str) -> tuple[str, str]:
        async with SessionLocal() as session:
            from core.repositories import get_crypto_order
            order = await get_crypto_order(session, order_code)
            if order is None or not order.tx_hash:
                return ('failed', 'Order or transaction was not found')
            plugin = game_registry.get(order.game_id)
            plan = next((item for item in plugin.all_plans() if item.key == order.plan_key), None)
            if plan is None:
                return ('failed', 'Plan no longer exists')
            if order.status == OrderStatus.VERIFIED.value:
                await self._activate_verified_order(session, order, plan.duration_days)
                return ('passed', 'Payment was already approved')
            if order.status == OrderStatus.AWAITING_ADMIN.value:
                detail = self._load_detail(order)
                return ('awaiting_admin', str(detail.get('message') or 'Waiting for final administrator approval'))
            try:
                result = await self.verifier.verify(network=order.network, tx_hash=order.tx_hash, wallet=order.destination_wallet, expected_usdc=Decimal(order.amount_usdc), order_created_at=order.created_at)
            except Exception as exc:
                detail = self._load_detail(order)
                detail.update({
                    'auto_status': 'error',
                    'message': f'Blockchain verification error: {type(exc).__name__}: {exc}',
                })
                await self._save_review_state(
                    session,
                    order,
                    status=OrderStatus.PENDING.value,
                    detail=detail,
                    notice_state='blockchain_verification_error',
                )
                logger.exception('Blockchain verification error for %s', order.order_code)
                return ('pending', detail['message'])
            await session.refresh(order)
            if order.status == OrderStatus.VERIFIED.value:
                await self._activate_verified_order(session, order, plan.duration_days)
                return ('passed', 'The order was approved while blockchain verification was running')
            if order.status == OrderStatus.REJECTED.value:
                return ('failed', 'The order was rejected while blockchain verification was running')
            detail = self._load_detail(order)
            detail.update({'auto_status': result.status, 'message': result.message, 'received_usdc': str(result.received_usdc), 'confirmations': result.confirmations, **result.detail})
            require_admin = True if order.game_id == 'kintara' else runtime_settings.require_admin_payment_approval(order.game_id, default=False)
            if result.status == 'passed':
                if require_admin:
                    notice_state = 'blockchain_passed_waiting_admin'
                    await self._save_review_state(session, order, status=OrderStatus.AWAITING_ADMIN.value, detail=detail, notice_state=notice_state)
                    return ('awaiting_admin', result.message)
                await set_order_verification(session, order, status=OrderStatus.VERIFIED.value, detail=detail)
                await self._activate_verified_order(session, order, plan.duration_days)
                return ('passed', result.message)
            if result.status == 'failed':
                if require_admin:
                    notice_state = 'automatic_check_failed_waiting_admin'
                    await self._save_review_state(session, order, status=OrderStatus.AWAITING_ADMIN.value, detail=detail, notice_state=notice_state)
                    return ('awaiting_admin', result.message)
                await set_order_verification(session, order, status=OrderStatus.REJECTED.value, detail=detail)
                return ('failed', result.message)
            notice_state = 'transaction_received_pending_network'
            await self._save_review_state(session, order, status=OrderStatus.PENDING.value, detail=detail, notice_state=notice_state)
            return ('pending', result.message)

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                async with SessionLocal() as session:
                    orders = await pending_crypto_orders(session)
                    codes = [row.order_code for row in orders]
                for code in codes:
                    try:
                        await self.verify_order(code)
                    except Exception:
                        logger.exception('Payment verification failed for %s', code)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception('Payment monitor iteration failed')
            await asyncio.sleep(runtime_settings.payment_check_seconds())
