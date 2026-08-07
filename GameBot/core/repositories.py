from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.time_utils import ensure_utc
from core.models import (
    CryptoOrder,
    GameAccount,
    OrderStatus,
    Subscription,
    TrialClaim,
    User,
    UserPreference,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    username: str | None,
    first_name: str | None,
    language: str | None = None,
    is_admin: bool = False,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            language=language or "fa",
            is_admin=is_admin,
        )
        session.add(user)
        await session.flush()
        session.add(UserPreference(user_id=user.id, notifications_enabled=True))
    else:
        user.username = username
        user.first_name = first_name
        if language:
            user.language = language
        user.is_admin = is_admin or user.is_admin
        preference = await session.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
        if preference is None:
            session.add(UserPreference(user_id=user.id, notifications_enabled=True))
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_telegram(session: AsyncSession, telegram_user_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))


async def set_user_language(session: AsyncSession, telegram_user_id: int, language: str) -> User | None:
    user = await get_user_by_telegram(session, telegram_user_id)
    if user is None:
        return None
    user.language = "en" if language == "en" else "fa"
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_preference(session: AsyncSession, user_id: int) -> UserPreference:
    preference = await session.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if preference is None:
        preference = UserPreference(user_id=user_id, notifications_enabled=True)
        session.add(preference)
        await session.commit()
        await session.refresh(preference)
    return preference


async def toggle_notifications(session: AsyncSession, user_id: int) -> bool:
    preference = await get_user_preference(session, user_id)
    preference.notifications_enabled = not preference.notifications_enabled
    await session.commit()
    return preference.notifications_enabled


async def list_accounts(
    session: AsyncSession,
    user_id: int,
    game_id: str | None = None,
    *,
    include_pending: bool = False,
) -> list[GameAccount]:
    query = select(GameAccount).where(GameAccount.user_id == user_id)
    if game_id:
        query = query.where(GameAccount.game_id == game_id)
    if not include_pending:
        query = query.where(
            GameAccount.status.notin_(["awaiting_payment", "awaiting_credential", "shared_access"])
        )
    result = await session.scalars(query.order_by(desc(GameAccount.created_at)))
    return list(result)


async def get_account(session: AsyncSession, account_id: int) -> GameAccount | None:
    return await session.scalar(select(GameAccount).where(GameAccount.id == account_id))


async def latest_active_subscription(session: AsyncSession, account_id: int) -> Subscription | None:
    now = utcnow()
    return await session.scalar(
        select(Subscription)
        .where(
            Subscription.account_id == account_id,
            Subscription.status == "active",
            Subscription.expires_at > now,
        )
        .order_by(desc(Subscription.expires_at))
    )


async def list_user_active_subscriptions(session: AsyncSession, user_id: int) -> list[tuple[GameAccount, Subscription]]:
    now = utcnow()
    rows = await session.execute(
        select(GameAccount, Subscription)
        .join(Subscription, Subscription.account_id == GameAccount.id)
        .where(
            GameAccount.user_id == user_id,
            Subscription.status == "active",
            Subscription.expires_at > now,
        )
        .order_by(desc(Subscription.expires_at))
    )
    return list(rows.all())


async def activate_subscription(
    session: AsyncSession,
    *,
    account_id: int,
    plan_key: str,
    duration: timedelta,
) -> Subscription:
    now = utcnow()
    active = await latest_active_subscription(session, account_id)
    starts_at = now
    base = now
    if active:
        active.status = "cancelled"
        base = ensure_utc(active.expires_at)
    subscription = Subscription(
        account_id=account_id,
        plan_key=plan_key,
        status="active",
        starts_at=starts_at,
        expires_at=base + duration,
        auto_renew=False,
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def claim_trial(
    session: AsyncSession,
    *,
    game_id: str,
    telegram_user_id: int,
    account: GameAccount,
    plan_key: str,
    duration_minutes: int,
    slot_limit: int = 0,
) -> Subscription:
    if await latest_active_subscription(session, account.id) is not None:
        raise ValueError("active_subscription")
    if slot_limit > 0:
        used = await session.scalar(select(func.count(TrialClaim.id)).where(TrialClaim.game_id == game_id))
        if int(used or 0) >= slot_limit:
            raise ValueError("trial_capacity_full")

    claim = TrialClaim(
        game_id=game_id,
        telegram_user_id=telegram_user_id,
        account_id=account.id,
        external_account_hash=account.external_account_hash,
        plan_key=plan_key,
    )
    session.add(claim)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError("trial_already_used") from exc

    subscription = Subscription(
        account_id=account.id,
        plan_key=plan_key,
        status="active",
        starts_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=max(1, duration_minutes)),
        auto_renew=False,
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def create_crypto_order(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    account_id: int,
    game_id: str,
    plan_key: str,
    network: str,
    destination_wallet: str,
    amount_usdc: Decimal,
) -> CryptoOrder:
    from core.config import settings

    exact_amount = amount_usdc
    if settings.payment_unique_amount_enabled:
        max_units = max(1, min(settings.payment_unique_amount_max_units, (10 ** settings.usdc_decimals) - 1))
        suffix_units = secrets.randbelow(max_units) + 1
        exact_amount += Decimal(suffix_units) / (Decimal(10) ** settings.usdc_decimals)
    exact_amount = exact_amount.quantize(Decimal(1) / (Decimal(10) ** settings.usdc_decimals))

    order = CryptoOrder(
        order_code="ORD-" + secrets.token_hex(5).upper(),
        telegram_user_id=telegram_user_id,
        account_id=account_id,
        game_id=game_id,
        plan_key=plan_key,
        network=network,
        destination_wallet=destination_wallet,
        amount_usdc=format(exact_amount, "f"),
        status=OrderStatus.AWAITING_TX.value,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_crypto_order(session: AsyncSession, order_code: str) -> CryptoOrder | None:
    return await session.scalar(select(CryptoOrder).where(CryptoOrder.order_code == order_code))


async def attach_transaction(session: AsyncSession, order: CryptoOrder, tx_hash: str) -> CryptoOrder:
    order.tx_hash = tx_hash
    order.status = OrderStatus.PENDING.value
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError("duplicate_transaction") from exc
    await session.refresh(order)
    return order


async def set_order_verification(
    session: AsyncSession,
    order: CryptoOrder,
    *,
    status: str,
    detail: dict,
    reviewed_by: int | None = None,
) -> CryptoOrder:
    order.status = status
    order.verification_detail_json = json.dumps(detail, ensure_ascii=False, default=str)
    if reviewed_by is not None:
        order.reviewed_by = reviewed_by
    await session.commit()
    await session.refresh(order)
    return order


async def pending_crypto_orders(session: AsyncSession, limit: int = 100) -> list[CryptoOrder]:
    result = await session.scalars(
        select(CryptoOrder)
        .where(CryptoOrder.status == OrderStatus.PENDING.value, CryptoOrder.tx_hash.is_not(None))
        .order_by(CryptoOrder.created_at)
        .limit(limit)
    )
    return list(result)


async def list_user_orders(session: AsyncSession, telegram_user_id: int, limit: int = 10) -> list[CryptoOrder]:
    result = await session.scalars(
        select(CryptoOrder)
        .where(CryptoOrder.telegram_user_id == telegram_user_id)
        .order_by(desc(CryptoOrder.created_at))
        .limit(limit)
    )
    return list(result)


def stable_external_hash(game_id: str, external_id: str) -> str:
    return hashlib.sha256(f"{game_id}:{external_id}".encode("utf-8")).hexdigest()


# -------------------- shared/free services --------------------
async def get_shared_service_access(
    session: AsyncSession,
    *,
    user_id: int,
    service_key: str,
):
    from core.models import SharedServiceAccess

    return await session.scalar(
        select(SharedServiceAccess).where(
            SharedServiceAccess.user_id == int(user_id),
            SharedServiceAccess.service_key == str(service_key),
        )
    )


async def enable_shared_service_access(
    session: AsyncSession,
    *,
    user_id: int,
    service_key: str,
    chat_id: int | None = None,
    message_id: int | None = None,
):
    from core.models import SharedServiceAccess

    row = await get_shared_service_access(session, user_id=user_id, service_key=service_key)
    if row is None:
        row = SharedServiceAccess(
            user_id=int(user_id),
            service_key=str(service_key),
            enabled=True,
            chat_id=chat_id,
            message_id=message_id,
        )
        session.add(row)
    else:
        row.enabled = True
        if chat_id is not None:
            row.chat_id = int(chat_id)
        if message_id is not None:
            row.message_id = int(message_id)
    await session.commit()
    await session.refresh(row)
    return row


async def update_shared_service_message(
    session: AsyncSession,
    *,
    access_id: int,
    chat_id: int,
    message_id: int,
    snapshot_version: str | None = None,
):
    from core.models import SharedServiceAccess

    row = await session.scalar(select(SharedServiceAccess).where(SharedServiceAccess.id == int(access_id)))
    if row is None:
        return None
    row.chat_id = int(chat_id)
    row.message_id = int(message_id)
    if snapshot_version is not None:
        row.last_snapshot_version = str(snapshot_version)
    await session.commit()
    await session.refresh(row)
    return row


async def disable_shared_service_access(
    session: AsyncSession,
    *,
    user_id: int,
    service_key: str,
) -> bool:
    row = await get_shared_service_access(session, user_id=user_id, service_key=service_key)
    if row is None:
        return False
    row.enabled = False
    await session.commit()
    return True


async def list_enabled_shared_service_access(
    session: AsyncSession,
    *,
    service_key: str,
):
    from core.models import SharedServiceAccess

    rows = await session.scalars(
        select(SharedServiceAccess)
        .where(
            SharedServiceAccess.service_key == str(service_key),
            SharedServiceAccess.enabled.is_(True),
        )
        .order_by(SharedServiceAccess.id)
    )
    return list(rows)


async def shared_service_access_count(session: AsyncSession, service_key: str) -> int:
    from core.models import SharedServiceAccess

    value = await session.scalar(
        select(func.count())
        .select_from(SharedServiceAccess)
        .where(
            SharedServiceAccess.service_key == str(service_key),
            SharedServiceAccess.enabled.is_(True),
        )
    )
    return int(value or 0)

# -------------------- managed shared-service entitlements --------------------
async def get_service_entitlement(session: AsyncSession, *, user_id: int, service_key: str):
    from core.models import ServiceEntitlement

    return await session.scalar(
        select(ServiceEntitlement).where(
            ServiceEntitlement.user_id == int(user_id),
            ServiceEntitlement.service_key == str(service_key),
        )
    )


async def grant_service_entitlement(
    session: AsyncSession,
    *,
    user_id: int,
    service_key: str,
    source: str,
    plan_key: str | None = None,
    account_id: int | None = None,
    expires_at: datetime | None = None,
):
    from core.models import ServiceEntitlement

    row = await get_service_entitlement(session, user_id=user_id, service_key=service_key)
    if row is None:
        row = ServiceEntitlement(
            user_id=int(user_id),
            service_key=str(service_key),
            source=str(source),
            status="active",
            plan_key=plan_key,
            account_id=account_id,
            starts_at=utcnow(),
            expires_at=expires_at,
        )
        session.add(row)
    else:
        row.source = str(source)
        row.status = "active"
        row.plan_key = plan_key
        row.account_id = account_id
        row.starts_at = utcnow()
        row.expires_at = expires_at
    await session.commit()
    await session.refresh(row)
    return row


async def set_service_channel_state(
    session: AsyncSession,
    *,
    entitlement_id: int,
    active: bool,
    invite_link: str | None = None,
):
    from core.models import ServiceEntitlement

    row = await session.get(ServiceEntitlement, int(entitlement_id))
    if row is None:
        return None
    row.channel_access_active = bool(active)
    if invite_link is not None:
        row.channel_invite_link = str(invite_link)
    await session.commit()
    await session.refresh(row)
    return row


async def active_service_entitlement(session: AsyncSession, *, user_id: int, service_key: str):
    row = await get_service_entitlement(session, user_id=user_id, service_key=service_key)
    if row is None or row.status != "active":
        return None
    if row.expires_at is not None and ensure_utc(row.expires_at) <= utcnow():
        row.status = "expired"
        row.channel_access_active = False
        await session.commit()
        return None
    return row


async def list_service_entitlements(session: AsyncSession, *, service_key: str):
    from core.models import ServiceEntitlement

    rows = await session.scalars(
        select(ServiceEntitlement)
        .where(ServiceEntitlement.service_key == str(service_key))
        .order_by(desc(ServiceEntitlement.updated_at))
    )
    return list(rows)


async def revoke_free_service_entitlements(session: AsyncSession, *, service_key: str):
    from core.models import ServiceEntitlement

    rows = list(
        await session.scalars(
            select(ServiceEntitlement).where(
                ServiceEntitlement.service_key == str(service_key),
                ServiceEntitlement.source == "free",
                ServiceEntitlement.status == "active",
            )
        )
    )
    for row in rows:
        row.status = "revoked"
    await session.commit()
    return rows


async def latest_user_order_with_status(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    status: str,
    game_id: str | None = None,
):
    query = select(CryptoOrder).where(
        CryptoOrder.telegram_user_id == int(telegram_user_id),
        CryptoOrder.status == str(status),
    )
    if game_id:
        query = query.where(CryptoOrder.game_id == str(game_id))
    return await session.scalar(query.order_by(desc(CryptoOrder.updated_at)))
