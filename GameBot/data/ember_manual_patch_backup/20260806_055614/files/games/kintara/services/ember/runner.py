from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any


from core.config import settings
from core.database import init_database
from core.runtime.shared_services.store import shared_service_store
from core.runtime_settings import runtime_settings
from core.worker_protocol import WorkerEventType
from games.kintara.services.ember.monitor import KintaraEmberMonitor
from games.kintara.shared_credentials import resolve_shared_cookie

SERVICE_KEY = "kintara_ember"


class FileStopEvent:
    def __init__(self, service_key: str) -> None:
        self.service_key = service_key
        self._local = threading.Event()
        self._last_file_check = 0.0
        self._file_requested = False

    def _refresh_file_state(self) -> None:
        now = time.monotonic()
        if now - self._last_file_check < 1.0:
            return
        self._last_file_check = now
        self._file_requested = shared_service_store.stop_requested(self.service_key)

    def is_set(self) -> bool:
        self._refresh_file_state()
        return self._local.is_set() or self._file_requested

    def set(self) -> None:
        self._local.set()
        self._file_requested = True
        shared_service_store.request_stop(self.service_key)

    def wait(self, seconds: float) -> bool:
        if self._local.wait(timeout=max(0.0, float(seconds))):
            return True
        return self.is_set()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def configure_logging(service_key: str) -> None:
    log_path = shared_service_store.log_path(service_key)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW("GameBot | Come To Molten")
        except Exception:
            pass


def _load_runtime_settings() -> None:
    async def load_runtime() -> None:
        await init_database()
        await runtime_settings.load()

    asyncio.run(load_runtime())


def _latest_cookie() -> str:
    try:
        return resolve_shared_cookie().cookie
    except Exception:
        return str(os.environ.get("KINTARA_EMBER_COOKIE") or "").strip()


def run_service(service_key: str, update_seconds: int) -> int:
    configure_logging(service_key)
    logger = logging.getLogger(__name__)

    try:
        _load_runtime_settings()
    except Exception:
        logging.getLogger(__name__).exception("Runtime settings could not be loaded; project environment values will be used")
    credential = resolve_shared_cookie()
    cookie = credential.cookie
    credential_source = credential.source

    update_seconds = max(20, int(update_seconds or 20))
    stop_event = FileStopEvent(service_key)
    shared_service_store.clear_stop(service_key)

    def stop_handler(*_args: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, stop_handler)

    shared_service_store.write_state(
        service_key,
        {
            "service_key": service_key,
            "status": "running",
            "pid": os.getpid(),
            "started_at": utc_iso(),
            "last_heartbeat_at": utc_iso(),
            "last_error": None,
            "update_seconds": update_seconds,
            "credential_source": credential_source,
        },
    )

    last_snapshot_signature: tuple[Any, ...] | None = None

    def emit(event_type: WorkerEventType | str, message: str = "", **payload: Any) -> None:
        nonlocal last_snapshot_signature
        event_value = getattr(event_type, "value", str(event_type))
        status = "running"
        if event_value == WorkerEventType.ERROR.value:
            status = "recovering" if payload.get("recoverable") else "error"
        elif event_value == WorkerEventType.STATUS.value:
            status = "running"

        shared_service_store.patch_state(
            service_key,
            status=status,
            pid=os.getpid(),
            last_heartbeat_at=utc_iso(),
            last_error=(message if event_value == WorkerEventType.ERROR.value else None),
            last_event={
                "type": event_value,
                "message": message,
                "payload": payload,
                "created_at": utc_iso(),
            },
        )

        if event_value != WorkerEventType.METRIC.value:
            return

        top3 = payload.get("top3") if isinstance(payload.get("top3"), list) else []
        snapshot = {
            "service_key": service_key,
            "updated_at": utc_iso(),
            "version": utc_iso(),
            "monitored": int(payload.get("monitored") or 0),
            "live": int(payload.get("live") or 0),
            "total_players": int(payload.get("total_players") or 0),
            "top3": [
                {
                    "server": str(row.get("server") or "?"),
                    "count": int(row.get("count") or 0),
                }
                for row in top3[:3]
                if isinstance(row, dict)
            ],
            "next_update_seconds": update_seconds,
            "coverage": float(payload.get("coverage") or 0.0),
            "accurate": bool(payload.get("accurate")),
            "source": str(payload.get("source") or "scheduled"),
            "request_ids": [str(item) for item in (payload.get("request_ids") or []) if str(item)],
            "missing_servers": [str(item) for item in (payload.get("missing_servers") or []) if str(item)],
        }
        shared_service_store.write_snapshot(service_key, snapshot)

        signature = (
            snapshot["source"],
            snapshot["accurate"],
            tuple((row["server"], row["count"]) for row in snapshot["top3"]),
        )
        if signature != last_snapshot_signature:
            if snapshot["accurate"]:
                summary = ", ".join(
                    f"{row['server']}:{row['count']}" for row in snapshot["top3"]
                ) or "no human players"
                logger.info("Verified Come To Molten snapshot: %s", summary)
            else:
                logger.warning(
                    "Come To Molten snapshot was not published as verified; missing=%s",
                    ",".join(snapshot["missing_servers"]) or "server list unavailable",
                )
            last_snapshot_signature = signature

    retry_seconds = 5.0
    try:
        emit(WorkerEventType.STARTED, "Molten monitor started", update_seconds=update_seconds)
        while not stop_event.is_set():
            monitor = KintaraEmberMonitor(
                base_url=settings.kintara_base_url,
                cookie=cookie,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
                ),
                cookie_provider=_latest_cookie,
            )
            try:
                monitor.run(
                    stop_event,
                    emit,
                    summary_seconds=update_seconds,
                    refresh_requested=lambda: shared_service_store.consume_refresh_requests(service_key),
                )
                if stop_event.is_set():
                    break
                raise RuntimeError("Molten monitor stopped unexpectedly")
            except Exception as exc:
                logger.exception("Molten monitor recovered from an unexpected internal error")
                shared_service_store.patch_state(
                    service_key,
                    status="recovering",
                    pid=os.getpid(),
                    last_error=str(exc),
                    last_heartbeat_at=utc_iso(),
                )
                if stop_event.wait(retry_seconds):
                    break
                retry_seconds = min(120.0, retry_seconds * 1.8)
            finally:
                monitor.stop()
        return 0
    finally:
        state = shared_service_store.read_state(service_key)
        if state.get("status") != "error":
            shared_service_store.patch_state(
                service_key,
                status="stopped",
                pid=None,
                stopped_at=utc_iso(),
            )
        shared_service_store.clear_stop(service_key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-key", default=SERVICE_KEY)
    parser.add_argument("--update-seconds", type=int, default=20)
    args = parser.parse_args()
    return run_service(args.service_key, args.update_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
