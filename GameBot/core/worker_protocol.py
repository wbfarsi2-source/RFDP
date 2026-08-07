from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class WorkerEventType(StrEnum):
    STARTED = "started"
    HEARTBEAT = "heartbeat"
    STATUS = "status"
    METRIC = "metric"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass(slots=True)
class WorkerEvent:
    event_type: WorkerEventType
    account_id: int
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
