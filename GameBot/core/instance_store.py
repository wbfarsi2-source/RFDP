"""Backward-compatible account instance store imports."""
from core.runtime.account_instances.store import AccountInstanceStore, instance_store, utc_iso

InstanceStore = AccountInstanceStore

__all__ = ["AccountInstanceStore", "InstanceStore", "instance_store", "utc_iso"]
