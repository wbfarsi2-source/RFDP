"""Backward-compatible shared service store imports."""
from core.runtime.shared_services.store import SharedServiceStore, shared_service_store, utc_iso

__all__ = ["SharedServiceStore", "shared_service_store", "utc_iso"]
