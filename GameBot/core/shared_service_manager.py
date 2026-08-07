"""Backward-compatible shared service manager imports."""
from core.runtime.shared_services.manager import (
    KINTARA_EMBER_SERVICE_KEY,
    SharedServiceHandle,
    SharedServiceManager,
)

__all__ = ["KINTARA_EMBER_SERVICE_KEY", "SharedServiceHandle", "SharedServiceManager"]
