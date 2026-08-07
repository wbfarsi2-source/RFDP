from __future__ import annotations

from core.database import SessionLocal
from core.models import User
from core.repositories import (
    active_service_entitlement,
    get_service_entitlement,
    grant_service_entitlement,
)
from core.runtime_settings import runtime_settings

SERVICE_KEY = "kintara_ember"
PLAN_KEY = "molten_access"


def access_mode() -> str:
    return runtime_settings.plan_access_mode("kintara", PLAN_KEY, "free")


async def ensure_free_access(user: User):
    if access_mode() != "free":
        return None
    async with SessionLocal() as session:
        return await grant_service_entitlement(
            session,
            user_id=user.id,
            service_key=SERVICE_KEY,
            source="free",
            plan_key=PLAN_KEY,
            account_id=None,
            expires_at=None,
        )


async def get_active_access(user_id: int):
    async with SessionLocal() as session:
        return await active_service_entitlement(
            session,
            user_id=user_id,
            service_key=SERVICE_KEY,
        )


async def get_access_record(user_id: int):
    async with SessionLocal() as session:
        return await get_service_entitlement(session, user_id=user_id, service_key=SERVICE_KEY)
