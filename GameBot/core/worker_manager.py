"""Backward-compatible account process manager imports."""
from core.runtime.account_instances.manager import AccountProcessManager, WorkerHandle

WorkerManager = AccountProcessManager

__all__ = ["AccountProcessManager", "WorkerManager", "WorkerHandle"]
