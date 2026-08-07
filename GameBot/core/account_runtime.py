"""Compatibility entry point for account processes."""
from core.runtime.account_instances.runner import FileStopEvent, main, run_instance

__all__ = ["FileStopEvent", "run_instance", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
