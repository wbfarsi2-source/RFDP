from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crypto import CredentialVault
from core.models import CryptoOrder, GameAccount, OrderStatus, User
from core.repositories import (
    activate_subscription,
    create_crypto_order,
    get_account,
    grant_service_entitlement,
    claim_trial,
    stable_external_hash,
    utcnow,
)
from core.runtime_settings import runtime_settings
from games.base import PlanDefinition
from games.kintara.plugin import KintaraPlugin


PENDING_CREDENTIAL = {"pending": True, "type": "kintara_credential"}


@dataclass(slots=True)
class ApprovalResult:
    action: str
    order: CryptoOrder
    expires_at: object | None = None


def find_plan(plan_key: str) -> PlanDefinition | None:
    plugin = KintaraPlugin()
    if plan_key == "trial":
        return PlanDefinition(
            key="trial",
            label_fa="Trial",
            label_en="Trial",
            price_usdc=Decimal("0"),
            duration_days=1,
            features={"farm": True, "cook": True, "spinner": False, "merchant": False},
        )
    return next((plan for plan in plugin.all_plans() if plan.key == plan_key), None)


def plan_access_mode(plan_key: str) -> str:
    default = "free" if plan_key == "molten_access" else "paid"
    return runtime_settings.plan_access_mode("kintara", plan_key, default)


async def create_placeholder_account(
    session: AsyncSession,
    *,
    user: User,
    plan: PlanDefinition,
) -> GameAccount:
    nonce = secrets.token_hex(16)
    account = GameAccount(
        user_id=user.id,
        game_id="kintara",
        label=f"Pending activation — {plan.label_en}",
        external_account_hash=stable_external_hash("kintara", f"pending:{user.telegram_user_id}:{nonce}"),
        credential_ciphertext=CredentialVault().encrypt(PENDING_CREDENTIAL),
        credential_hint="pending",
        status="awaiting_payment" if plan_access_mode(plan.key) == "paid" else "awaiting_credential",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def create_paid_purchase_order(
    session: AsyncSession,
    *,
    user: User,
    plan: PlanDefinition,
    network: str,
    wallet: str,
) -> CryptoOrder:
    account = await create_placeholder_account(session, user=user, plan=plan)
    return await create_crypto_order(
        session,
        telegram_user_id=user.telegram_user_id,
        account_id=account.id,
        game_id="kintara",
        plan_key=plan.key,
        network=network,
        destination_wallet=wallet,
        amount_usdc=plan.price_usdc,
    )


async def create_free_purchase_order(
    session: AsyncSession,
    *,
    user: User,
    plan: PlanDefinition,
) -> CryptoOrder:
    account = await create_placeholder_account(session, user=user, plan=plan)
    order = CryptoOrder(
        order_code="FREE-" + secrets.token_hex(5).upper(),
        telegram_user_id=user.telegram_user_id,
        account_id=account.id,
        game_id="kintara",
        plan_key=plan.key,
        network="free",
        destination_wallet="-",
        amount_usdc="0",
        status=(
            OrderStatus.AWAITING_CREDENTIAL.value
            if plan.requires_credential
            else OrderStatus.VERIFIED.value
        ),
        verification_detail_json=json.dumps({"access_mode": "free"}),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    if not plan.requires_credential:
        await activate_shared_plan(session, order=order, plan=plan, source="free")
    return order


async def create_trial_order(session: AsyncSession, *, user: User) -> CryptoOrder:
    plan = find_plan("trial")
    assert plan is not None
    account = await create_placeholder_account(session, user=user, plan=plan)
    account.status = "awaiting_credential"
    order = CryptoOrder(
        order_code="TRIAL-" + secrets.token_hex(5).upper(),
        telegram_user_id=user.telegram_user_id,
        account_id=account.id,
        game_id="kintara",
        plan_key="trial",
        network="trial",
        destination_wallet="-",
        amount_usdc="0",
        status=OrderStatus.AWAITING_CREDENTIAL.value,
        verification_detail_json=json.dumps({"access_mode": "trial"}),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def approve_order(
    session: AsyncSession,
    *,
    order: CryptoOrder,
    reviewer: int,
) -> ApprovalResult:
    plan = find_plan(order.plan_key)
    if plan is None:
        raise ValueError("plan_not_found")
    try:
        detail = json.loads(order.verification_detail_json or "{}")
    except Exception:
        detail = {}
    detail.update({"manual": True, "manual_action": "approved", "reviewer": int(reviewer)})
    order.reviewed_by = int(reviewer)
    if plan.runtime_kind == "shared":
        order.status = OrderStatus.VERIFIED.value
        order.verification_detail_json = json.dumps(detail, ensure_ascii=False)
        await session.commit()
        subscription = await activate_shared_plan(session, order=order, plan=plan, source="paid")
        return ApprovalResult("shared_activated", order, subscription.expires_at)
    order.status = OrderStatus.AWAITING_CREDENTIAL.value
    order.verification_detail_json = json.dumps(detail, ensure_ascii=False)
    account = await get_account(session, order.account_id)
    if account is not None:
        account.status = "awaiting_credential"
    await session.commit()
    await session.refresh(order)
    return ApprovalResult("credential_required", order)


async def activate_shared_plan(
    session: AsyncSession,
    *,
    order: CryptoOrder,
    plan: PlanDefinition,
    source: str,
):
    account = await get_account(session, order.account_id)
    if account is None:
        raise ValueError("account_not_found")
    account.label = plan.label_en
    account.status = "shared_access"
    await session.commit()
    subscription = await activate_subscription(
        session,
        account_id=account.id,
        plan_key=plan.key,
        duration=timedelta(days=plan.duration_days),
    )
    await grant_service_entitlement(
        session,
        user_id=account.user_id,
        service_key=str(plan.shared_service_key or "kintara_ember"),
        source=source,
        plan_key=plan.key,
        account_id=account.id,
        expires_at=None if source == "free" else subscription.expires_at,
    )
    return subscription


async def complete_credential_activation(
    session: AsyncSession,
    *,
    order: CryptoOrder,
    raw_credential: str,
) -> tuple[GameAccount, object]:
    plan = find_plan(order.plan_key)
    if plan is None or not plan.requires_credential:
        raise ValueError("credential_not_required")
    plugin = KintaraPlugin()
    validation = await plugin.validate_credentials(raw_credential)
    if not validation.valid or not validation.normalized:
        raise ValueError(validation.error or "invalid_credential")

    placeholder = await get_account(session, order.account_id)
    if placeholder is None:
        raise ValueError("account_not_found")
    external_hash = stable_external_hash("kintara", validation.external_id)
    existing = await session.scalar(
        select(GameAccount).where(
            GameAccount.user_id == placeholder.user_id,
            GameAccount.game_id == "kintara",
            GameAccount.external_account_hash == external_hash,
            GameAccount.id != placeholder.id,
        )
    )
    ciphertext = CredentialVault().encrypt(validation.normalized)
    account = existing or placeholder
    account.label = validation.display_name or "Kintara Account"
    account.external_account_hash = external_hash
    account.credential_ciphertext = ciphertext
    account.credential_hint = validation.hint
    account.status = "ready"
    if existing is not None:
        order.account_id = existing.id
        await session.flush()
        await session.execute(delete(GameAccount).where(GameAccount.id == placeholder.id))
    order.status = OrderStatus.VERIFIED.value
    try:
        detail = json.loads(order.verification_detail_json or "{}")
    except Exception:
        detail = {}
    detail["credential_received_at"] = utcnow().isoformat()
    order.verification_detail_json = json.dumps(detail, ensure_ascii=False)
    await session.commit()
    await session.refresh(account)
    await session.refresh(order)
    if order.network == "trial" or order.plan_key == "trial":
        trial = KintaraPlugin().trial()
        subscription = await claim_trial(
            session,
            game_id="kintara",
            telegram_user_id=order.telegram_user_id,
            account=account,
            plan_key=trial.plan_key,
            duration_minutes=trial.duration_minutes,
            slot_limit=trial.slot_limit,
        )
    else:
        subscription = await activate_subscription(
            session,
            account_id=account.id,
            plan_key=plan.key,
            duration=timedelta(days=plan.duration_days),
        )
    return account, subscription


async def cancel_placeholder_for_order(session: AsyncSession, order: CryptoOrder) -> None:
    account = await get_account(session, order.account_id)
    if account is not None and account.status in {"awaiting_payment", "awaiting_credential"}:
        await session.execute(delete(GameAccount).where(GameAccount.id == account.id))
        await session.commit()
