from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SpinnerService:
    """Isolated spinner integration boundary.

    The supplied Kintara engine does not expose a verified spinner API call.
    Keeping this service separate prevents unverified requests from affecting
    fishing and cooking. Add the verified endpoint only in this module.
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._reported = False

    def tick(self, emit, payload: dict[str, Any] | None = None) -> None:
        if not self.enabled or self._reported:
            return
        self._reported = True
        emit(
            "status",
            "Spinner module is enabled but waiting for a verified Kintara endpoint",
            service_key="spinner",
            configured=False,
            **(payload or {}),
        )
        logger.warning("Spinner endpoint is not configured; no spinner request was sent")
