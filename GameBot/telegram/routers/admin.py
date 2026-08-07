from __future__ import annotations
from core.locale_text import localized_literal
from core.admin_text import admin_literal
import html
import json
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import func, select
from core.backup_service import BackupService
from core.config import settings
from core.database import SessionLocal
from core.crypto import CredentialVault
from core.feature_flags import feature_flags
from core.models import CryptoOrder, GameAccount, OrderStatus, SharedServiceAccess, Subscription, TrialClaim, User
from core.registry import game_registry
from core.repositories import activate_subscription, get_account, get_crypto_order, get_user_by_telegram, latest_active_subscription, set_order_verification, shared_service_access_count
from core.runtime_settings import runtime_settings
from core.shared_service_manager import KINTARA_EMBER_SERVICE_KEY, SharedServiceManager
from core.shared_service_store import shared_service_store
from core.worker_manager import WorkerManager

from games.kintara.molten.channel import MoltenChannelService
from games.kintara.purchases.messages import approved_waiting_cookie, cookie_guide
from games.kintara.purchases.service import approve_order as approve_kintara_order, cancel_placeholder_for_order
from telegram.keyboards import channel_invite_keyboard, credential_prompt_keyboard
from telegram.admin_keyboards import admin_home_keyboard, back_home, come_to_molten_admin_keyboard, feature_admin_keyboard, feature_server_locked_keyboard, features_admin_keyboard, features_games_keyboard, game_admin_keyboard, games_admin_keyboard, maintenance_admin_keyboard, network_admin_keyboard, orders_admin_keyboard, payments_admin_keyboard, plan_admin_keyboard, plans_admin_keyboard, plans_games_keyboard, support_admin_keyboard, system_admin_keyboard, trial_admin_keyboard, trials_games_keyboard, workers_admin_keyboard
router = Router(name='admin')

class AdminInput(StatesGroup):
    waiting_value = State()

def admin_id_from_event(event: Message | CallbackQuery) -> int | None:
    user = event.from_user
    return int(user.id) if user and user.id in settings.admin_user_ids else None

async def require_admin_message(message: Message) -> bool:
    if admin_id_from_event(message) is None:
        await message.answer(admin_literal('telegram.routers.admin.1eef86e516ba'))
        return False
    return True

async def require_admin_callback(callback: CallbackQuery) -> bool:
    if admin_id_from_event(callback) is None:
        await callback.answer(admin_literal('telegram.routers.admin.602fca45b277'), show_alert=True)
        return False
    return True

async def _stats_text() -> str:
    async with SessionLocal() as session:
        users = await session.scalar(select(func.count()).select_from(User))
        accounts = await session.scalar(select(func.count()).select_from(GameAccount))
        running = await session.scalar(select(func.count()).select_from(GameAccount).where(GameAccount.status == 'running'))
        subscriptions = await session.scalar(select(func.count()).select_from(Subscription))
        orders = await session.scalar(select(func.count()).select_from(CryptoOrder))
        pending = await session.scalar(select(func.count()).select_from(CryptoOrder).where(CryptoOrder.status.in_([OrderStatus.AWAITING_TX.value, OrderStatus.PENDING.value, OrderStatus.AWAITING_ADMIN.value])))
        trials = await session.scalar(select(func.count()).select_from(TrialClaim))
        ember_users = await shared_service_access_count(session, KINTARA_EMBER_SERVICE_KEY)
    maintenance = admin_literal('telegram.routers.admin.6f637966671d') if runtime_settings.maintenance_enabled() else admin_literal('telegram.routers.admin.d9ba41681180')
    return f"{admin_literal('telegram.routers.admin.7cfb7c75e9fb')}{users or 0}{admin_literal('telegram.routers.admin.8531f9b0b849')}{accounts or 0}{admin_literal('telegram.routers.admin.7173c2e29ede')}{running or 0}{admin_literal('telegram.routers.admin.28e55aef2265')}{subscriptions or 0}{admin_literal('telegram.routers.admin.6b7c13bccfe4')}{orders or 0}{admin_literal('telegram.routers.admin.cb47ef23635f')}{pending or 0}{admin_literal('telegram.routers.admin.8fa19d6d90dc')}{trials or 0}{admin_literal('telegram.routers.admin.9db9378e6ebd')}{ember_users}{admin_literal('telegram.routers.admin.afccbce6bc38')}{maintenance}{admin_literal('telegram.routers.admin.8886158fbbd7')}"

@router.message(Command('admin'))
async def admin_panel(message: Message, state: FSMContext) -> None:
    if not await require_admin_message(message):
        return
    await state.clear()
    await message.answer(await _stats_text(), reply_markup=admin_home_keyboard())

@router.callback_query(F.data == 'admin:home')
async def admin_home(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    await state.clear()
    await callback.message.answer(await _stats_text(), reply_markup=admin_home_keyboard())
    await callback.answer()

@router.callback_query(F.data == 'admin:games')
async def admin_games(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(admin_literal('telegram.routers.admin.3e1b6f3e34ee'), reply_markup=games_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:game:'))
async def admin_game_detail(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.split(':', 2)[2]
    plugin = game_registry.get(game_id)
    async with SessionLocal() as session:
        account_count = await session.scalar(select(func.count()).select_from(GameAccount).where(GameAccount.game_id == game_id))
        running_count = await session.scalar(select(func.count()).select_from(GameAccount).where(GameAccount.game_id == game_id, GameAccount.status == 'running'))
    await callback.message.answer(f"🎮 <b>{plugin.display_name_en}{admin_literal('telegram.routers.admin.b00a83f1cf3b')}{game_id}{admin_literal('telegram.routers.admin.695efa26111a')}{(admin_literal('telegram.routers.admin.6f637966671d') if feature_flags.game_enabled(game_id) else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.b82211b0fd8d')}{(admin_literal('telegram.routers.admin.6f637966671d') if feature_flags.game_visible(game_id) else admin_literal('telegram.routers.admin.cd99bfd023c6'))}{admin_literal('telegram.routers.admin.4770f8ae422a')}{account_count or 0}{admin_literal('telegram.routers.admin.19fbc1699397')}{running_count or 0}</b>", reply_markup=game_admin_keyboard(game_id))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:game_toggle:'))
async def admin_game_toggle(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, field = callback.data.split(':', 3)
    admin_id = admin_id_from_event(callback)
    if field == 'enabled':
        new_value = not feature_flags.game_enabled(game_id)
        await runtime_settings.set(f'games.{game_id}.enabled', new_value, updated_by=admin_id)
        feature_flags.touch_runtime_overrides()
        stopped = 0
        if not new_value:
            stopped = await worker_manager.stop_game(game_id)
        async with SessionLocal() as session:
            accounts = list(await session.scalars(select(GameAccount).where(GameAccount.game_id == game_id)))
            for account in accounts:
                if new_value and account.status == 'disabled':
                    account.status = 'ready'
                    account.last_error = None
                elif not new_value:
                    account.status = 'disabled'
                    account.worker_pid = None
                    account.last_error = 'Game disabled by administrator'
            await session.commit()
        text = f"{admin_literal('telegram.routers.admin.a00806d40606')}{(admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.75fd0511b2e9')}{stopped}"
    else:
        new_value = not feature_flags.game_visible(game_id)
        await runtime_settings.set(f'games.{game_id}.visible', new_value, updated_by=admin_id)
        feature_flags.touch_runtime_overrides()
        text = f"{admin_literal('telegram.routers.admin.c881fd608e29')}{(admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.cd99bfd023c6'))}{admin_literal('telegram.routers.admin.53d0644851f1')}"
    await callback.message.answer(text, reply_markup=game_admin_keyboard(game_id))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:game_stop:'))
async def admin_game_stop(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.rsplit(':', 1)[1]
    count = await worker_manager.stop_game(game_id)
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.403ad06d7c0a')}{count}{admin_literal('telegram.routers.admin.35809ac24438')}", reply_markup=game_admin_keyboard(game_id))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:game_restart:'))
async def admin_game_restart(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.rsplit(':', 1)[1]
    if not feature_flags.game_enabled(game_id):
        await callback.answer(admin_literal('telegram.routers.admin.f9a04593afc0'), show_alert=True)
        return
    started, failed = await worker_manager.restart_game(game_id)
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.db8e3c2aab1b')}{started}{admin_literal('telegram.routers.admin.7d1893295245')}{failed}</b>", reply_markup=game_admin_keyboard(game_id))
    await callback.answer()

@router.callback_query(F.data == 'admin:payments')
async def admin_payments(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(admin_literal('telegram.routers.admin.c99b9757a84e'), reply_markup=payments_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:payment_approval_toggle:'))
async def admin_payment_approval_toggle(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.rsplit(':', 1)[1]
    current = runtime_settings.require_admin_payment_approval(game_id, default=game_id == 'kintara')
    new_value = not current
    await runtime_settings.set(f'games.{game_id}.payments.require_admin_approval', new_value, updated_by=admin_id_from_event(callback))
    await callback.message.answer(admin_literal('custom.admin.payment.manual_enabled') if new_value else admin_literal('custom.admin.payment.manual_disabled'), reply_markup=payments_admin_keyboard())
    await callback.answer()

def _network_id(short: str) -> str:
    return 'solana_usdc' if short == 'sol' else 'base_usdc'

def _network_prefix(short: str) -> str:
    return 'payments.solana' if short == 'sol' else 'payments.base'

@router.callback_query(F.data.startswith('admin:network:'))
async def admin_network_detail(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    short = callback.data.rsplit(':', 1)[1]
    data = runtime_settings.payment_network(_network_id(short))
    token_name = 'Mint' if short == 'sol' else 'Contract'
    await callback.message.answer(f"💳 <b>{('Solana USDC' if short == 'sol' else 'Base USDC')}{admin_literal('telegram.routers.admin.0d53ad78620f')}{(admin_literal('telegram.routers.admin.6f637966671d') if data['enabled'] else admin_literal('telegram.routers.admin.d9ba41681180'))}</b>\nWallet: <code>{html.escape(runtime_settings.masked(_network_prefix(short) + '.wallet', data['wallet']))}</code>\n{token_name}: <code>{html.escape(runtime_settings.masked(_network_prefix(short) + ('.mint' if short == 'sol' else '.contract'), data['token']))}</code>\nRPC: <code>{html.escape(str(data['rpc_url']))}</code>", reply_markup=network_admin_keyboard(short, bool(data['enabled'])))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:network_toggle:'))
async def admin_network_toggle(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    short = callback.data.rsplit(':', 1)[1]
    network = runtime_settings.payment_network(_network_id(short))
    new_value = not bool(network['enabled'])
    if new_value and (not network['wallet'] or not network['token']):
        await callback.answer(admin_literal('telegram.routers.admin.a464e38c86be'), show_alert=True)
        return
    await runtime_settings.set(f'{_network_prefix(short)}.enabled', new_value, updated_by=admin_id_from_event(callback))
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.04fae85c26d1')}{(admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.53d0644851f1')}", reply_markup=network_admin_keyboard(short, new_value))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:network_set:'))
async def admin_network_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, short, field = callback.data.split(':', 3)
    labels = {'wallet': admin_literal('telegram.routers.admin.ef9e4c9226f3'), 'token': admin_literal('telegram.routers.admin.c2920de650a8'), 'rpc': 'RPC URL'}
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='network', short=short, field=field)
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.61ce8f959ab3')}{labels[field]}{admin_literal('telegram.routers.admin.58af843d33eb')}")
    await callback.answer()

@router.callback_query(F.data.startswith('admin:network_reset:'))
async def admin_network_reset(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    short = callback.data.rsplit(':', 1)[1]
    prefix = _network_prefix(short)
    suffixes = ('enabled', 'wallet', 'mint', 'contract', 'rpc_url')
    for suffix in suffixes:
        await runtime_settings.delete(f'{prefix}.{suffix}')
    await callback.message.answer(admin_literal('telegram.routers.admin.5f639b680c2b'), reply_markup=payments_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data == 'admin:plans')
async def admin_plans(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(admin_literal('telegram.routers.admin.dc29a65d9fce'), reply_markup=plans_games_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:plans_game:'))
async def admin_plans_game(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.split(':', 2)[2]
    await callback.message.answer(admin_literal('telegram.routers.admin.559c727c2565'), reply_markup=plans_admin_keyboard(game_id))
    await callback.answer()

def _plan_defaults(game_id: str, plan_key: str) -> tuple[Decimal, int, str]:
    plugin = game_registry.get(game_id)
    found = next((p for p in plugin.all_plans() if p.key == plan_key), None)
    if found:
        return (found.price_usdc, found.duration_days, 'Come To Molten' if game_id == 'kintara' and plan_key == 'molten_access' else found.label_en)
    return (Decimal('0'), 7, plan_key)

@router.callback_query(F.data.startswith('admin:plan:'))
async def admin_plan_detail(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, plan_key = callback.data.split(':', 3)
    if game_id == 'kintara' and plan_key == 'molten_access':
        await callback.message.answer(
            await _come_to_molten_admin_text(shared_service_manager),
            reply_markup=_come_to_molten_keyboard(shared_service_manager),
        )
        await callback.answer()
        return
    default_price, default_days, label = _plan_defaults(game_id, plan_key)
    price = runtime_settings.plan_price(game_id, plan_key, default_price)
    days = runtime_settings.plan_duration_days(game_id, plan_key, default_days)
    enabled = runtime_settings.plan_enabled(game_id, plan_key, True)
    mode = runtime_settings.plan_access_mode(game_id, plan_key, 'free' if game_id == 'kintara' and plan_key == 'molten_access' else 'paid')
    mode_label = admin_literal('admin.plan.free') if mode == 'free' else admin_literal('admin.plan.paid')
    text = (
        f"💎 <b>{label}</b>"
        f"{admin_literal('telegram.routers.admin.0d53ad78620f')}"
        f"{admin_literal('telegram.routers.admin.6f637966671d') if enabled else admin_literal('telegram.routers.admin.d9ba41681180')}"
        f"{admin_literal('telegram.routers.admin.f0633dc70778')}{price}"
        f"{admin_literal('telegram.routers.admin.7e2f1eaa62bc')}{days}"
        f"{admin_literal('telegram.routers.admin.a728d962e233')}"
        f"\n{admin_literal('admin.plan.access_mode')}: <b>{mode_label}</b>"
    )
    await callback.message.answer(text, reply_markup=plan_admin_keyboard(game_id, plan_key, enabled))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:plan_mode:'))
async def admin_plan_mode(
    callback: CallbackQuery,
    molten_channel_service: MoltenChannelService,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, plan_key = callback.data.split(':', 3)
    current = runtime_settings.plan_access_mode(game_id, plan_key, 'free' if game_id == 'kintara' and plan_key == 'molten_access' else 'paid')
    new_mode = 'paid' if current == 'free' else 'free'
    await runtime_settings.set(
        f'games.{game_id}.plans.{plan_key}.access_mode',
        new_mode,
        updated_by=admin_id_from_event(callback),
    )
    removed = 0
    if game_id == 'kintara' and plan_key == 'molten_access' and new_mode == 'paid':
        removed = await molten_channel_service.revoke_free_members()
    message = admin_literal('admin.plan.mode_paid') if new_mode == 'paid' else admin_literal('admin.plan.mode_free')
    if removed:
        message += admin_literal('admin.plan.revoked_free').format(count=removed)
    reply_markup = (
        _come_to_molten_keyboard(shared_service_manager)
        if game_id == 'kintara' and plan_key == 'molten_access'
        else plan_admin_keyboard(game_id, plan_key, runtime_settings.plan_enabled(game_id, plan_key, True))
    )
    await callback.message.answer(message, reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data.startswith('admin:plan_toggle:'))
async def admin_plan_toggle(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, plan_key = callback.data.split(':', 3)
    new_value = not runtime_settings.plan_enabled(game_id, plan_key, True)
    await runtime_settings.set(f'games.{game_id}.plans.{plan_key}.enabled', new_value, updated_by=admin_id_from_event(callback))
    reply_markup = (
        _come_to_molten_keyboard(shared_service_manager)
        if game_id == 'kintara' and plan_key == 'molten_access'
        else plan_admin_keyboard(game_id, plan_key, new_value)
    )
    await callback.message.answer(
        f"{admin_literal('telegram.routers.admin.2a31ccb79e67')}"
        f"{admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.d9ba41681180')}"
        f"{admin_literal('telegram.routers.admin.53d0644851f1')}",
        reply_markup=reply_markup,
    )
    await callback.answer()

@router.callback_query(F.data.startswith('admin:plan_set:'))
async def admin_plan_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, plan_key, field = callback.data.split(':', 4)
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='plan', game_id=game_id, plan_key=plan_key, field=field)
    await callback.message.answer(admin_literal('telegram.routers.admin.330614083250') if field == 'price' else admin_literal('telegram.routers.admin.b15872b61e56'))
    await callback.answer()

@router.callback_query(F.data == 'admin:trials')
async def admin_trials(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(admin_literal('telegram.routers.admin.111b5339be36'), reply_markup=trials_games_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:trial:'))
async def admin_trial_detail(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.split(':', 2)[2]
    trial = game_registry.get(game_id).trial()
    async with SessionLocal() as session:
        used = await session.scalar(select(func.count()).select_from(TrialClaim).where(TrialClaim.game_id == game_id))
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.429ea30401a7')}{game_id}{admin_literal('telegram.routers.admin.0d53ad78620f')}{(admin_literal('telegram.routers.admin.6f637966671d') if trial.enabled else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.0afbd7295df0')}{trial.duration_minutes}{admin_literal('telegram.routers.admin.8c1d5408696d')}{(trial.slot_limit if trial.slot_limit else admin_literal('telegram.routers.admin.58c54168f817'))}{admin_literal('telegram.routers.admin.c04b94250e86')}{used or 0}</b>", reply_markup=trial_admin_keyboard(game_id, trial.enabled))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:trial_toggle:'))
async def admin_trial_toggle(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.rsplit(':', 1)[1]
    new_value = not game_registry.get(game_id).trial().enabled
    await runtime_settings.set(f'games.{game_id}.trial.enabled', new_value, updated_by=admin_id_from_event(callback))
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.9aa0208d2eab')}{(admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.53d0644851f1')}", reply_markup=trial_admin_keyboard(game_id, new_value))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:trial_set:'))
async def admin_trial_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, field = callback.data.split(':', 3)
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='trial', game_id=game_id, field=field)
    prompt = admin_literal('telegram.routers.admin.eb06b38998b0') if field == 'duration' else admin_literal('telegram.routers.admin.583185e23fe8')
    await callback.message.answer(prompt)
    await callback.answer()

@router.callback_query(F.data.startswith('admin:trial_claims:'))
async def admin_trial_claims(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.rsplit(':', 1)[1]
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(TrialClaim).where(TrialClaim.game_id == game_id).order_by(TrialClaim.claimed_at.desc()).limit(30)))
    if not rows:
        text = admin_literal('telegram.routers.admin.2058e209a592')
    else:
        text = admin_literal('telegram.routers.admin.39e7769e289b') + '\n'.join((f'• User <code>{row.telegram_user_id}</code> | Account <code>{row.account_id}</code>' for row in rows))
    await callback.message.answer(text, reply_markup=trial_admin_keyboard(game_id, game_registry.get(game_id).trial().enabled))
    await callback.answer()

def _feature_names(game_id: str) -> list[str]:
    path = Path('games') / game_id / 'features.json'
    names: list[str] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                names.extend((str(x) for x in raw.keys() if not str(x).startswith('_')))
        except Exception:
            pass
    prefix = f'games.{game_id}.features.'
    for key in runtime_settings.keys():
        if key.startswith(prefix):
            rest = key[len(prefix):].split('.', 1)[0]
            if rest and rest not in names:
                names.append(rest)
    return sorted(set(names))

@router.callback_query(F.data == 'admin:features')
async def admin_features(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(admin_literal('telegram.routers.admin.3b29075e050a'), reply_markup=features_games_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:features_game:'))
async def admin_features_game(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    game_id = callback.data.split(':', 2)[2]
    names = _feature_names(game_id)
    await callback.message.answer(admin_literal('telegram.routers.admin.33579e962656'), reply_markup=features_admin_keyboard(game_id, names))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:feature:'))
async def admin_feature_detail(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, name = callback.data.split(':', 3)
    enabled = feature_flags.enabled(game_id, name, False)
    visible = feature_flags.visible(game_id, name, False)
    label = game_registry.get(game_id).feature_label(name, 'en')
    if name == 'molten':
        label = 'Come To Molten'
    server_locked = game_id == 'kintara' and name == 'merchant'
    lock_note = admin_literal('telegram.routers.admin.817f2eae7343') if server_locked else ''
    await callback.message.answer(f"🧩 <b>{label}{admin_literal('telegram.routers.admin.1da2ed76cd34')}{(admin_literal('telegram.routers.admin.6f637966671d') if enabled else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.b82211b0fd8d')}{(admin_literal('telegram.routers.admin.6f637966671d') if visible else admin_literal('telegram.routers.admin.cd99bfd023c6'))}</b>{lock_note}", reply_markup=feature_server_locked_keyboard(game_id) if server_locked else feature_admin_keyboard(game_id, name, enabled, visible))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:feature_toggle:'))
async def admin_feature_toggle(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, name, field = callback.data.split(':', 4)
    if game_id == 'kintara' and name == 'merchant':
        await callback.answer(admin_literal('telegram.routers.admin.8a71a0811d94'), show_alert=True)
        return
    current = feature_flags.enabled(game_id, name, False) if field == 'enabled' else feature_flags.visible(game_id, name, False)
    await runtime_settings.set(f'games.{game_id}.features.{name}.{field}', not current, updated_by=admin_id_from_event(callback))
    feature_flags.touch_runtime_overrides()
    enabled = feature_flags.enabled(game_id, name, False)
    visible = feature_flags.visible(game_id, name, False)
    await callback.message.answer(admin_literal('telegram.routers.admin.1fc836964f3b'), reply_markup=feature_admin_keyboard(game_id, name, enabled, visible))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:feature_reset:'))
async def admin_feature_reset(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    _, _, game_id, name = callback.data.split(':', 3)
    if game_id == 'kintara' and name == 'merchant':
        await callback.answer(admin_literal('telegram.routers.admin.099bf20633c3'), show_alert=True)
        return
    await runtime_settings.delete(f'games.{game_id}.features.{name}.enabled')
    await runtime_settings.delete(f'games.{game_id}.features.{name}.visible')
    feature_flags.touch_runtime_overrides()
    await callback.message.answer(admin_literal('telegram.routers.admin.ca70527ecd90'), reply_markup=features_admin_keyboard(game_id, _feature_names(game_id)))
    await callback.answer()

@router.callback_query(F.data == 'admin:server_locked')
async def admin_server_locked(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.answer(admin_literal('telegram.routers.admin.0a1fb798b8eb'), show_alert=True)

@router.callback_query(F.data == 'admin:support')
async def admin_support(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.86b43fbbff07')}{html.escape(runtime_settings.support_handle())}</code>\nURL: <code>{html.escape(runtime_settings.support_url())}</code>", reply_markup=support_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:support_set:'))
async def admin_support_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    field = callback.data.rsplit(':', 1)[1]
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='support', field=field)
    await callback.message.answer(admin_literal('telegram.routers.admin.cea3e6ffebe4') if field == 'handle' else admin_literal('telegram.routers.admin.c6a8d9ad493a'))
    await callback.answer()

@router.callback_query(F.data == 'admin:maintenance')
async def admin_maintenance(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    enabled = runtime_settings.maintenance_enabled()
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.3a1d4d0b4ea6')}{(admin_literal('telegram.routers.admin.6f637966671d') if enabled else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.56135df8fbe4')}{html.escape(runtime_settings.maintenance_message('fa'))}\nEnglish: {html.escape(runtime_settings.maintenance_message('en'))}", reply_markup=maintenance_admin_keyboard(enabled))
    await callback.answer()

@router.callback_query(F.data == 'admin:maintenance_toggle')
async def admin_maintenance_toggle(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    new_value = not runtime_settings.maintenance_enabled()
    await runtime_settings.set('platform.maintenance.enabled', new_value, updated_by=admin_id_from_event(callback))
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.9fa15a68a2e3')}{(admin_literal('telegram.routers.admin.6f637966671d') if new_value else admin_literal('telegram.routers.admin.d9ba41681180'))}{admin_literal('telegram.routers.admin.53d0644851f1')}", reply_markup=maintenance_admin_keyboard(new_value))
    await callback.answer()

@router.callback_query(F.data.startswith('admin:maintenance_set:'))
async def admin_maintenance_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    lang = callback.data.rsplit(':', 1)[1]
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='maintenance', lang=lang)
    await callback.message.answer(admin_literal('telegram.routers.admin.d13b5ee971cb'))
    await callback.answer()

def _come_to_molten_top3_text(snapshot: dict) -> str:
    top3 = snapshot.get("top3") if isinstance(snapshot.get("top3"), list) else []
    if not top3:
        return "-"
    return "\n".join(
        f"{index}. {html.escape(str(row.get('server') or '?'))} — <b>{int(row.get('count') or 0)}</b>"
        for index, row in enumerate(top3[:3], start=1)
        if isinstance(row, dict)
    ) or "-"


def _come_to_molten_keyboard(shared_service_manager: SharedServiceManager):
    status = shared_service_manager.ember_status()
    return come_to_molten_admin_keyboard(
        running=bool(status.get("running")),
        enabled=bool(status.get("enabled")),
        visible=bool(status.get("visible")),
        auto_start=bool(status.get("auto_start")),
        plan_enabled=runtime_settings.plan_enabled("kintara", "molten_access", True),
        access_mode=runtime_settings.plan_access_mode("kintara", "molten_access", "free"),
    )


async def _come_to_molten_admin_text(shared_service_manager: SharedServiceManager) -> str:
    status = shared_service_manager.ember_status()
    snapshot = status.get("snapshot") if isinstance(status.get("snapshot"), dict) else {}
    async with SessionLocal() as session:
        access_count = await shared_service_access_count(session, KINTARA_EMBER_SERVICE_KEY)

    default_price, default_days, _ = _plan_defaults("kintara", "molten_access")
    price = runtime_settings.plan_price("kintara", "molten_access", default_price)
    duration_days = runtime_settings.plan_duration_days("kintara", "molten_access", default_days)
    access_mode = runtime_settings.plan_access_mode("kintara", "molten_access", "free")
    plan_enabled = runtime_settings.plan_enabled("kintara", "molten_access", True)

    yes_no = lambda value: "Yes" if value else "No"
    access_label = "Free" if access_mode == "free" else "Paid"
    text = (
        "🔥 <b>Come To Molten</b>\n\n"
        f"CMD status: <b>{'Running' if status.get('running') else 'Stopped'}</b>\n"
        f"PID: <code>{status.get('pid') or '-'}</code>\n"
        f"Service enabled: <b>{yes_no(status.get('enabled'))}</b>\n"
        f"Visible to users: <b>{yes_no(status.get('visible'))}</b>\n"
        f"Auto-start: <b>{yes_no(status.get('auto_start'))}</b>\n"
        f"Central Cookie: <b>{'Configured' if status.get('configured') else 'Not configured'}</b>\n"
        f"Credential source: <code>{html.escape(str(status.get('credential_source') or 'project'))}</code>\n"
        f"Monitor interval: <b>{status.get('update_seconds') or 20} seconds</b>\n"
        f"Channel ID: <code>{runtime_settings.get('services.kintara_ember.channel_id', settings.kintara_channel_id) or '-'}</code>\n\n"
        "<b>Access settings</b>\n"
        f"Access plan enabled: <b>{yes_no(plan_enabled)}</b>\n"
        f"Access mode: <b>{access_label}</b>\n"
        f"Price: <b>{price} USDC</b>\n"
        f"Duration: <b>{duration_days} day(s)</b>\n"
        f"Users with access: <b>{access_count}</b>\n\n"
        "<b>Current result</b>\n"
        f"{_come_to_molten_top3_text(snapshot)}\n\n"
        f"Workspace: <code>{html.escape(str(status.get('workspace') or '-'))}</code>"
    )
    return text


@router.callback_query(F.data == "admin:ember")
@router.callback_query(F.data == "admin:kintara:come_to_molten")
async def admin_come_to_molten(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(
        await _come_to_molten_admin_text(shared_service_manager),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_start")
async def admin_ember_start(
    callback: CallbackQuery,
    state: FSMContext,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    if not runtime_settings.ember_enabled():
        await runtime_settings.set(
            "services.kintara_ember.enabled",
            True,
            updated_by=admin_id_from_event(callback),
        )
    workspace = shared_service_manager.provision_ember_workspace()
    if not shared_service_manager.has_ember_cookie():
        await state.set_state(AdminInput.waiting_value)
        await state.update_data(action="ember", field="credential", start_after_save=True)
        await callback.message.answer(
            "Come To Molten workspace is ready.\n"
            f"<code>{html.escape(str(workspace))}</code>\n\n"
            "Send the central Kintara Cookie. The message will be deleted immediately, "
            "the value will be encrypted, and the CMD will start automatically."
        )
        await callback.answer()
        return
    ok, detail = await shared_service_manager.start_ember()
    await callback.message.answer(
        ("✅ " if ok else "⚠️ ") + html.escape(detail),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_stop")
async def admin_ember_stop(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    ok, detail = await shared_service_manager.stop_ember()
    await callback.message.answer(
        ("✅ " if ok else "⚠️ ") + html.escape(detail),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_restart")
async def admin_ember_restart(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    ok, detail = await shared_service_manager.restart_ember()
    await callback.message.answer(
        ("✅ " if ok else "⚠️ ") + html.escape(detail),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ember_toggle:"))
async def admin_ember_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    field = callback.data.rsplit(":", 1)[1]
    key_map = {
        "enabled": "services.kintara_ember.enabled",
        "visible": "services.kintara_ember.visible",
        "auto_start": "services.kintara_ember.auto_start",
    }
    key = key_map[field]
    current = {
        "enabled": runtime_settings.ember_enabled(),
        "visible": runtime_settings.ember_visible(),
        "auto_start": runtime_settings.ember_auto_start(),
    }[field]
    new_value = not current
    await runtime_settings.set(key, new_value, updated_by=admin_id_from_event(callback))
    workspace = shared_service_manager.provision_ember_workspace()
    detail = "The setting was saved."
    if field == "enabled":
        if not new_value:
            _, detail = await shared_service_manager.stop_ember()
        elif not shared_service_manager.has_ember_cookie():
            await state.set_state(AdminInput.waiting_value)
            await state.update_data(action="ember", field="credential", start_after_save=True)
            await callback.message.answer(
                "Come To Molten was enabled and its workspace was created.\n"
                f"<code>{html.escape(str(workspace))}</code>\n\n"
                "Send the central Kintara Cookie. After validation, the CMD will start automatically."
            )
            await callback.answer()
            return
        elif runtime_settings.ember_auto_start():
            _, detail = await shared_service_manager.start_ember(reset_restart=False)
    elif field == "auto_start" and new_value and runtime_settings.ember_enabled():
        if not shared_service_manager.has_ember_cookie():
            await state.set_state(AdminInput.waiting_value)
            await state.update_data(action="ember", field="credential", start_after_save=True)
            await callback.message.answer(
                "Auto-start is enabled. Send the central Kintara Cookie; "
                "after validation, the Come To Molten CMD will start automatically."
            )
            await callback.answer()
            return
        _, detail = await shared_service_manager.start_ember(reset_restart=False)
    await callback.message.answer(
        f"✅ {html.escape(detail)}",
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ember_set:"))
async def admin_ember_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    field = callback.data.rsplit(":", 1)[1]
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action="ember", field=field)
    if field == "credential":
        await callback.message.answer(
            "Send the central Kintara Cookie. The message will be deleted immediately and the value will be encrypted.\n"
            "This account is used only to retrieve Come To Molten server information."
        )
    elif field == "channel":
        await callback.message.answer(
            "Send the private channel numeric ID, for example: <code>-1004463401405</code>"
        )
    else:
        await callback.message.answer(
            "Send the monitor interval in seconds. The minimum value is <code>20</code>."
        )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_use_project_cookie")
async def admin_ember_use_project_cookie(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    await runtime_settings.set(
        "services.kintara_ember.cookie_source",
        "project",
        updated_by=admin_id_from_event(callback),
    )
    shared_service_manager.provision_ember_workspace()
    if runtime_settings.ember_enabled() and runtime_settings.ember_auto_start():
        ok, detail = await shared_service_manager.restart_ember()
    else:
        ok, detail = True, "The project .env Cookie was selected."
    await callback.message.answer(
        ("✅ " if ok else "⚠️ ") + html.escape(detail),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_publish")
async def admin_ember_publish(
    callback: CallbackQuery,
    molten_channel_service: MoltenChannelService,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    ok = await molten_channel_service.publish_now()
    await callback.message.answer(
        "The latest Come To Molten report was published to the channel."
        if ok
        else "Accurate data is not ready yet, or the channel is not configured correctly.",
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ember_users")
async def admin_ember_users(
    callback: CallbackQuery,
    shared_service_manager: SharedServiceManager,
) -> None:
    if not await require_admin_callback(callback):
        return
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(SharedServiceAccess, User)
                    .join(User, User.id == SharedServiceAccess.user_id)
                    .where(
                        SharedServiceAccess.service_key == KINTARA_EMBER_SERVICE_KEY,
                        SharedServiceAccess.enabled.is_(True),
                    )
                    .order_by(SharedServiceAccess.updated_at.desc())
                    .limit(50)
                )
            ).all()
        )
    lines = [f"👥 <b>Come To Molten Users</b> — {len(rows)} user(s)"]
    for access, user in rows:
        label = "@" + user.username.lstrip("@") if user.username else user.first_name or "-"
        lines.append(f"• {html.escape(label)} | <code>{user.telegram_user_id}</code>")
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=_come_to_molten_keyboard(shared_service_manager),
    )
    await callback.answer()


@router.callback_query(F.data == 'admin:workers')
async def admin_workers(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    lines = [f"{admin_literal('telegram.routers.admin.c4727b0e6a25')}{len(worker_manager.handles)}</b>"]
    for account_id, handle in list(worker_manager.handles.items())[:20]:
        lines.append(f'• Account <code>{account_id}</code> | {handle.game_id} | PID <code>{handle.pid}</code>')
    await callback.message.answer('\n'.join(lines), reply_markup=workers_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data == 'admin:workers_stop_all')
async def admin_workers_stop_all(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    count = await worker_manager.stop_all()
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.403ad06d7c0a')}{count}{admin_literal('telegram.routers.admin.35809ac24438')}", reply_markup=workers_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data == 'admin:workers_restart_all')
async def admin_workers_restart_all(callback: CallbackQuery, worker_manager: WorkerManager) -> None:
    if not await require_admin_callback(callback):
        return
    started, failed = await worker_manager.restart_all_active()
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.d2938ecf81cf')}{started}{admin_literal('telegram.routers.admin.7d1893295245')}{failed}</b>", reply_markup=workers_admin_keyboard())
    await callback.answer()

async def _pending_rows() -> list[CryptoOrder]:
    async with SessionLocal() as session:
        result = await session.scalars(select(CryptoOrder).where(CryptoOrder.status.in_([OrderStatus.PENDING.value, OrderStatus.AWAITING_ADMIN.value]), CryptoOrder.tx_hash.is_not(None)).order_by(CryptoOrder.created_at.desc()).limit(20))
        return list(result)

@router.callback_query(F.data == 'admin:orders')
async def admin_orders(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    rows = await _pending_rows()
    if not rows:
        await callback.message.answer(admin_literal('telegram.routers.admin.b166f39076c7'), reply_markup=back_home())
    else:
        lines = [admin_literal('telegram.routers.admin.906355b636ab')]
        for row in rows[:10]:
            try:
                detail = json.loads(row.verification_detail_json or '{}')
            except Exception:
                detail = {}
            auto_status = str(detail.get('auto_status') or '-')
            lines.append(f"\n• <code>{row.order_code}</code> | {row.amount_usdc} USDC | {row.network}\nUser <code>{row.telegram_user_id}</code> | Status <b>{row.status}</b> | Auto <b>{html.escape(auto_status)}</b>\nTX <code>{html.escape(str(row.tx_hash or '-'))}</code>")
        await callback.message.answer('\n'.join(lines), reply_markup=orders_admin_keyboard(rows))
    await callback.answer()

async def _approve_order(
    order_code: str,
    reviewer: int,
    worker_manager: WorkerManager,
) -> tuple[bool, str, CryptoOrder | None, str]:
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        if order is None:
            return (False, admin_literal('telegram.routers.admin.a073b87c2875'), None, 'missing')
        if order.status in {OrderStatus.VERIFIED.value, OrderStatus.AWAITING_CREDENTIAL.value}:
            return (False, admin_literal('telegram.routers.admin.62ac6685ebf7'), order, 'already_processed')
        if not order.tx_hash and order.network not in {'free', 'trial'}:
            return (False, admin_literal('telegram.routers.admin.3e6bcc734f3c'), order, 'missing_tx')
        if order.game_id == 'kintara':
            result = await approve_kintara_order(session, order=order, reviewer=reviewer)
            return (True, admin_literal('custom.payment.admin.approved'), result.order, result.action)

        plugin = game_registry.get(order.game_id)
        plan = next((row for row in plugin.all_plans() if row.key == order.plan_key), None)
        if plan is None:
            return (False, admin_literal('telegram.routers.admin.b1d67399cf5c'), order, 'plan_missing')
        try:
            detail = json.loads(order.verification_detail_json or '{}')
        except Exception:
            detail = {}
        detail.update({'manual': True, 'manual_action': 'approved'})
        await set_order_verification(
            session,
            order,
            status=OrderStatus.VERIFIED.value,
            detail=detail,
            reviewed_by=reviewer,
        )
        await activate_subscription(
            session,
            account_id=order.account_id,
            plan_key=order.plan_key,
            duration=timedelta(days=plan.duration_days),
        )
    await worker_manager.start_account(order.account_id)
    return (True, admin_literal('telegram.routers.admin.8c66df35b1d7'), order, 'account_started')


async def _notify_order_decision(
    bot,
    order: CryptoOrder,
    approved: bool,
    action: str = '',
    molten_channel_service: MoltenChannelService | None = None,
) -> None:
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, order.telegram_user_id)
    language = 'en' if user and user.language == 'en' else 'fa'
    if not approved:
        text = (
            '<b>Payment rejected</b>\n\nThe service was not activated. Contact support if you need a review.'
            if language == 'en'
            else localized_literal('custom.payment.user.rejected')
        )
        await bot.send_message(order.telegram_user_id, text)
        return

    if action == 'credential_required':
        await bot.send_message(
            order.telegram_user_id,
            approved_waiting_cookie(language) + '\n\n' + cookie_guide(language),
            reply_markup=credential_prompt_keyboard(order.order_code, language),
        )
        return

    if action == 'shared_activated':
        link = ''
        if user and molten_channel_service and molten_channel_service.channel_id:
            try:
                link = await molten_channel_service.create_personal_invite(user)
            except Exception:
                link = ''
        text = (
            '<b>Come To Molten activated</b>\n\nYou can now refresh the current servers in the bot.'
            if language == 'en'
            else localized_literal('kintara.molten.payment_approved')
        )
        await bot.send_message(
            order.telegram_user_id,
            text,
            reply_markup=channel_invite_keyboard(link, language) if link else None,
        )
        return

    text = (
        '<b>Payment approved</b>\n\nYour service is active.'
        if language == 'en'
        else localized_literal('custom.payment.user.approved')
    )
    await bot.send_message(order.telegram_user_id, text)


async def _reject_order(order_code: str, reviewer: int) -> tuple[bool, str, CryptoOrder | None]:
    async with SessionLocal() as session:
        order = await get_crypto_order(session, order_code)
        if order is None:
            return (False, admin_literal('telegram.routers.admin.a073b87c2875'), None)
        if order.status == OrderStatus.VERIFIED.value:
            return (False, admin_literal('telegram.routers.admin.3be0419687e6'), order)
        try:
            detail = json.loads(order.verification_detail_json or '{}')
        except Exception:
            detail = {}
        detail.update({'manual': True, 'manual_action': 'rejected'})
        await set_order_verification(
            session,
            order,
            status=OrderStatus.REJECTED.value,
            detail=detail,
            reviewed_by=reviewer,
        )
        if order.game_id == 'kintara':
            await cancel_placeholder_for_order(session, order)
    return (True, admin_literal('telegram.routers.admin.d3d8e7a1dd5b'), order)


@router.callback_query(F.data.startswith('admin:order_approve:'))
async def admin_order_approve(
    callback: CallbackQuery,
    worker_manager: WorkerManager,
    molten_channel_service: MoltenChannelService,
) -> None:
    if not await require_admin_callback(callback):
        return
    code = callback.data.split(':', 2)[2]
    ok, text, order, action = await _approve_order(
        code,
        admin_id_from_event(callback) or 0,
        worker_manager,
    )
    if ok and order:
        await _notify_order_decision(
            callback.bot,
            order,
            True,
            action=action,
            molten_channel_service=molten_channel_service,
        )
    await callback.message.answer(('✅ ' if ok else '⚠️ ') + text, reply_markup=back_home())
    await callback.answer()


@router.callback_query(F.data.startswith('admin:order_reject:'))
async def admin_order_reject(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    code = callback.data.split(':', 2)[2]
    ok, text, order = await _reject_order(code, admin_id_from_event(callback) or 0)
    if ok and order:
        await _notify_order_decision(callback.bot, order, False)
    await callback.message.answer(('✅ ' if ok else '⚠️ ') + text, reply_markup=back_home())
    await callback.answer()

@router.callback_query(F.data == 'admin:users')
async def admin_users(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(User).order_by(User.created_at.desc()).limit(30)))
    lines = [admin_literal('telegram.routers.admin.6603c735de4c')]
    for user in rows:
        name = '@' + user.username.lstrip('@') if user.username else user.first_name or '-'
        lines.append(f'• {html.escape(name)} | <code>{user.telegram_user_id}</code> | {user.language}')
    await callback.message.answer('\n'.join(lines) if rows else admin_literal('telegram.routers.admin.799c08248ff3'), reply_markup=back_home())
    await callback.answer()

@router.callback_query(F.data == 'admin:backup')
async def admin_backup_callback(callback: CallbackQuery, backup_service: BackupService) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.answer(admin_literal('telegram.routers.admin.7672a423a606'))
    try:
        archive = await backup_service.create_backup()
        await callback.message.answer_document(FSInputFile(archive), caption=admin_literal('telegram.routers.admin.7386d0fe35a5'), protect_content=True)
    except Exception as exc:
        await callback.message.answer(f"{admin_literal('telegram.routers.admin.4f6d6282fd21')}{html.escape(str(exc))}</code>")

@router.callback_query(F.data == 'admin:reload')
async def admin_reload(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await runtime_settings.load()
    feature_flags.load_local()
    feature_flags.touch_runtime_overrides()
    remote = ''
    if settings.feature_flags_url:
        try:
            await feature_flags.refresh_remote()
            remote = admin_literal('telegram.routers.admin.ddbf294803bb')
        except Exception as exc:
            remote = f"{admin_literal('telegram.routers.admin.2cb9d0bf92b6')}{html.escape(str(exc))}"
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.81f17c729d72')}{remote}{admin_literal('telegram.routers.admin.a10f2132fbb3')}", reply_markup=admin_home_keyboard())
    await callback.answer()

@router.callback_query(F.data == 'admin:system')
async def admin_system(callback: CallbackQuery) -> None:
    if not await require_admin_callback(callback):
        return
    await callback.message.answer(f"{admin_literal('telegram.routers.admin.68ae9548c296')}{runtime_settings.payment_check_seconds()}{admin_literal('telegram.routers.admin.ae370194313a')}{runtime_settings.payment_min_confirmations()}{admin_literal('telegram.routers.admin.340f51470859')}{runtime_settings.worker_restart_limit()}</b>\nHeartbeat timeout: <b>{runtime_settings.worker_heartbeat_timeout()}{admin_literal('telegram.routers.admin.1cdd3844c5d3')}{runtime_settings.expiry_warning_hours()}{admin_literal('telegram.routers.admin.e53ba1568def')}{runtime_settings.backup_interval_seconds()}{admin_literal('telegram.routers.admin.7251dbec5941')}{runtime_settings.backup_keep_last()}</b>", reply_markup=system_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith('admin:system_set:'))
async def admin_system_set_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not await require_admin_callback(callback):
        return
    field = callback.data.rsplit(':', 1)[1]
    prompts = {'payment_check': admin_literal('telegram.routers.admin.6aa416ea8610'), 'confirmations': admin_literal('telegram.routers.admin.fec37b190eaa'), 'restart_limit': admin_literal('telegram.routers.admin.f6b6a8ffc618'), 'heartbeat': admin_literal('telegram.routers.admin.621cc67ba714'), 'expiry_warning': admin_literal('telegram.routers.admin.4a97e116e5c7'), 'backup_interval': admin_literal('telegram.routers.admin.f9c74d69d056'), 'backup_keep': admin_literal('telegram.routers.admin.41abae56572a')}
    await state.set_state(AdminInput.waiting_value)
    await state.update_data(action='system', field=field)
    await callback.message.answer(prompts[field])
    await callback.answer()

@router.message(Command('cancel'))
async def admin_cancel(message: Message, state: FSMContext) -> None:
    if not await require_admin_message(message):
        return
    await state.clear()
    await message.answer(admin_literal('telegram.routers.admin.9181590e0672'), reply_markup=admin_home_keyboard())

def _validate_network_value(short: str, field: str, value: str) -> tuple[bool, str]:
    value = value.strip()
    if ' ' in value or len(value) > 300:
        return (False, admin_literal('telegram.routers.admin.9d27a6ae1977'))
    if field == 'rpc':
        return (value.startswith('https://') or value.startswith('http://'), admin_literal('telegram.routers.admin.c0461f7159b3'))
    if short == 'base':
        return (bool(re.fullmatch('0x[a-fA-F0-9]{40}', value)), admin_literal('telegram.routers.admin.845e06056b52'))
    return (bool(re.fullmatch('[1-9A-HJ-NP-Za-km-z]{32,60}', value)), admin_literal('telegram.routers.admin.c89940bd0f4c'))

@router.message(AdminInput.waiting_value)
async def admin_receive_value(message: Message, state: FSMContext, shared_service_manager: SharedServiceManager) -> None:
    if not await require_admin_message(message):
        return
    value = (message.text or '').strip()
    data = await state.get_data()
    action = str(data.get('action') or '')
    admin_id = admin_id_from_event(message)
    try:
        if action == 'network':
            short = str(data['short'])
            field = str(data['field'])
            valid, error = _validate_network_value(short, field, value)
            if not valid:
                await message.answer(f'❌ {error}')
                return
            prefix = _network_prefix(short)
            suffix = 'rpc_url' if field == 'rpc' else 'mint' if short == 'sol' and field == 'token' else 'contract' if field == 'token' else 'wallet'
            await runtime_settings.set(f'{prefix}.{suffix}', value, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.396f6497b4dd')
        elif action == 'plan':
            game_id, plan_key, field = (str(data['game_id']), str(data['plan_key']), str(data['field']))
            if field == 'price':
                number = Decimal(value)
                if number <= 0 or number > Decimal('100000'):
                    raise ValueError(admin_literal('telegram.routers.admin.68f77dc9b35e'))
                await runtime_settings.set(f'games.{game_id}.plans.{plan_key}.price_usdc', str(number), updated_by=admin_id)
            else:
                number_int = int(value)
                if number_int < 1 or number_int > 3650:
                    raise ValueError(admin_literal('telegram.routers.admin.6f83c51f779a'))
                await runtime_settings.set(f'games.{game_id}.plans.{plan_key}.duration_days', number_int, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.981311490c22')
        elif action == 'trial':
            game_id, field = (str(data['game_id']), str(data['field']))
            number = int(value)
            if field == 'duration':
                if number < 1 or number > 43200:
                    raise ValueError(admin_literal('telegram.routers.admin.a9b2808c7d48'))
                await runtime_settings.set(f'games.{game_id}.trial.duration_minutes', number, updated_by=admin_id)
            else:
                if number < 0 or number > 1000000:
                    raise ValueError(admin_literal('telegram.routers.admin.21b938b85906'))
                await runtime_settings.set(f'games.{game_id}.trial.slot_limit', number, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.d367b207e8cd')
        elif action == 'support':
            field = str(data['field'])
            if field == 'handle':
                if not re.fullmatch('@[A-Za-z0-9_]{4,64}', value):
                    raise ValueError(admin_literal('telegram.routers.admin.b74df5e64dff'))
                await runtime_settings.set('platform.support_handle', value, updated_by=admin_id)
            else:
                if not value.startswith(('https://', 'http://')):
                    raise ValueError(admin_literal('telegram.routers.admin.af16e31ef2fe'))
                await runtime_settings.set('platform.support_url', value, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.974a180607d1')
        elif action == 'maintenance':
            lang = str(data['lang'])
            if len(value) < 3 or len(value) > 1000:
                raise ValueError(admin_literal('telegram.routers.admin.4cb78b996a4b'))
            await runtime_settings.set(f'platform.maintenance.message.{lang}', value, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.20922a4d9875')
        elif action == 'ember':
            field = str(data['field'])
            if field == 'channel':
                channel_id = int(value)
                if channel_id >= 0:
                    raise ValueError(admin_literal('admin.molten.channel_invalid'))
                await runtime_settings.set('services.kintara_ember.channel_id', channel_id, updated_by=admin_id)
                reply = admin_literal('admin.molten.channel_saved')
            elif field == 'credential':
                try:
                    await message.delete()
                except Exception:
                    pass
                plugin = game_registry.get('kintara')
                result = await plugin.validate_credentials(value)
                if not result.valid or not result.normalized:
                    raise ValueError(result.error or admin_literal('telegram.routers.admin.54bca6c45468'))
                encrypted = CredentialVault().encrypt(result.normalized)
                await runtime_settings.set('services.kintara_ember.credential_ciphertext', encrypted, is_secret=True, updated_by=admin_id)
                await runtime_settings.set('services.kintara_ember.cookie_source', 'admin_override', updated_by=admin_id)
                shared_service_manager.provision_ember_workspace()
                should_start = bool(data.get('start_after_save')) or (runtime_settings.ember_enabled() and runtime_settings.ember_auto_start())
                if should_start and runtime_settings.ember_enabled():
                    ok, detail = await shared_service_manager.restart_ember()
                    reply = admin_literal('custom.admin.ember.cookie_saved').format(detail=html.escape(detail if ok else f'Startup result: {detail}'))
                else:
                    reply = admin_literal('custom.admin.ember.cookie_saved').format(detail='')
            else:
                number = int(value)
                if number < 20 or number > 86400:
                    raise ValueError(admin_literal('telegram.routers.admin.f5acf1375c9a'))
                await runtime_settings.set('services.kintara_ember.update_seconds', number, updated_by=admin_id)
                reply = admin_literal('telegram.routers.admin.cfc5ad48801d')
                if shared_service_manager.ember_status().get('running'):
                    await shared_service_manager.restart_ember()
        elif action == 'system':
            field = str(data['field'])
            number = int(value)
            specs = {'payment_check': ('system.payment_check_seconds', 15, 86400), 'confirmations': ('system.payment_min_confirmations', 1, 1000), 'restart_limit': ('system.worker_restart_limit', 0, 100), 'heartbeat': ('system.worker_heartbeat_timeout', 30, 86400), 'expiry_warning': ('system.expiry_warning_hours', 1, 8760), 'backup_interval': ('system.backup_interval_seconds', 3600, 31536000), 'backup_keep': ('system.backup_keep_last', 1, 365)}
            key, minimum, maximum = specs[field]
            if number < minimum or number > maximum:
                raise ValueError(f"{admin_literal('telegram.routers.admin.ac80c4fc51ae')}{minimum}{admin_literal('telegram.routers.admin.cc57bcc77391')}{maximum}{admin_literal('telegram.routers.admin.155460a6fd73')}")
            await runtime_settings.set(key, number, updated_by=admin_id)
            reply = admin_literal('telegram.routers.admin.2202351aa22c')
        else:
            raise ValueError(admin_literal('telegram.routers.admin.873bc9171517'))
    except (ValueError, InvalidOperation, KeyError) as exc:
        await message.answer(f'❌ {html.escape(str(exc))}')
        return
    await state.clear()
    if action == 'plan' and str(data.get('game_id')) == 'kintara' and str(data.get('plan_key')) == 'molten_access':
        reply_markup = _come_to_molten_keyboard(shared_service_manager)
    elif action == 'ember':
        reply_markup = _come_to_molten_keyboard(shared_service_manager)
    else:
        reply_markup = admin_home_keyboard()
    await message.answer(reply, reply_markup=reply_markup)

@router.message(Command('approve'))
async def approve_order_command(
    message: Message,
    worker_manager: WorkerManager,
    molten_channel_service: MoltenChannelService,
) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 2:
        await message.answer(admin_literal('telegram.routers.admin.c82949cc3022'))
        return
    ok, text, order, action = await _approve_order(parts[1].upper(), message.from_user.id, worker_manager)
    if ok and order:
        await _notify_order_decision(
            message.bot,
            order,
            True,
            action=action,
            molten_channel_service=molten_channel_service,
        )
    await message.answer(('✅ ' if ok else '⚠️ ') + text)

@router.message(Command('reject'))
async def reject_order_command(message: Message) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 2:
        await message.answer(admin_literal('telegram.routers.admin.c0daaabc2042'))
        return
    ok, text, order = await _reject_order(parts[1].upper(), message.from_user.id)
    if ok and order:
        await _notify_order_decision(message.bot, order, False)
    await message.answer(('✅ ' if ok else '⚠️ ') + text)

@router.message(Command('backup'))
async def create_backup_command(message: Message, backup_service: BackupService) -> None:
    if not await require_admin_message(message):
        return
    archive = await backup_service.create_backup()
    await message.answer_document(FSInputFile(archive), caption=admin_literal('telegram.routers.admin.50cbbb80324d'), protect_content=True)

@router.message(Command('pending'))
async def pending_orders_command(message: Message) -> None:
    if not await require_admin_message(message):
        return
    rows = await _pending_rows()
    if not rows:
        await message.answer(admin_literal('telegram.routers.admin.b166f39076c7'))
        return
    await message.answer('\n'.join((f'<code>{row.order_code}</code> | {row.amount_usdc} USDC | {row.status}' for row in rows)))

@router.message(Command('users'))
async def list_users_command(message: Message) -> None:
    if not await require_admin_message(message):
        return
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(User).order_by(User.created_at.desc()).limit(30)))
    await message.answer('\n'.join((f"<code>{u.telegram_user_id}</code> | {html.escape(u.username or u.first_name or '-')}" for u in rows)) or admin_literal('telegram.routers.admin.528b10fcc311'))

@router.message(Command('runaccount'))
async def run_account_admin(message: Message, worker_manager: WorkerManager) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(admin_literal('telegram.routers.admin.7e0b08f62a55'))
        return
    ok, detail = await worker_manager.start_account(int(parts[1]))
    await message.answer(('✅ ' if ok else '⚠️ ') + detail)

@router.message(Command('stopaccount'))
async def stop_account_admin(message: Message, worker_manager: WorkerManager) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(admin_literal('telegram.routers.admin.c976d8221569'))
        return
    ok, detail = await worker_manager.stop_account(int(parts[1]))
    await message.answer(('✅ ' if ok else '⚠️ ') + detail)

@router.message(Command('restartaccount'))
async def restart_account_admin(message: Message, worker_manager: WorkerManager) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(admin_literal('telegram.routers.admin.1c8d94b0eabf'))
        return
    ok, detail = await worker_manager.restart_account(int(parts[1]))
    await message.answer(('✅ ' if ok else '⚠️ ') + detail)

@router.message(Command('extend'))
async def extend_subscription(message: Message) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 3 or not parts[1].isdigit() or (not parts[2].isdigit()):
        await message.answer(admin_literal('telegram.routers.admin.f747270e6189'))
        return
    account_id, days = (int(parts[1]), int(parts[2]))
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        active = await latest_active_subscription(session, account_id) if account else None
        if account is None or active is None:
            await message.answer(admin_literal('telegram.routers.admin.f0e472867266'))
            return
        sub = await activate_subscription(session, account_id=account_id, plan_key=active.plan_key, duration=timedelta(days=max(1, days)))
    await message.answer(f"{admin_literal('telegram.routers.admin.1a84bfa88670')}{sub.expires_at.isoformat()}{admin_literal('telegram.routers.admin.a5ac1b4f54dd')}")

@router.message(Command('changeplan'))
async def change_plan(message: Message, worker_manager: WorkerManager) -> None:
    if not await require_admin_message(message):
        return
    parts = (message.text or '').split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer(admin_literal('telegram.routers.admin.d63067fdcb1e'))
        return
    account_id, plan_key = (int(parts[1]), parts[2])
    async with SessionLocal() as session:
        account = await get_account(session, account_id)
        active = await latest_active_subscription(session, account_id) if account else None
        if account is None or active is None:
            await message.answer(admin_literal('telegram.routers.admin.f0e472867266'))
            return
        plugin = game_registry.get(account.game_id)
        if not any((plan.key == plan_key for plan in plugin.plans())):
            await message.answer(admin_literal('telegram.routers.admin.e33ec6f3b000'))
            return
        active.plan_key = plan_key
        await session.commit()
    await worker_manager.restart_account(account_id)
    await message.answer(f"{admin_literal('telegram.routers.admin.21fea35fbb5d')}{html.escape(plan_key)}{admin_literal('telegram.routers.admin.3701bef2c49f')}")
