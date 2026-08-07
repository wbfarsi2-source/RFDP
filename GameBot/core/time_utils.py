from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.config import settings


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_datetime(value: datetime) -> datetime:
    try:
        zone = ZoneInfo(settings.display_timezone)
    except Exception:
        zone = timezone.utc
    return ensure_utc(value).astimezone(zone)


def display_datetime(value: datetime, lang: str = "fa") -> str:
    local = local_datetime(value)
    if lang == "en":
        return local.strftime("%Y-%m-%d %H:%M")
    return local.strftime("%Y/%m/%d - %H:%M")
