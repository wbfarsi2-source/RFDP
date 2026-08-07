from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from core.crypto import CredentialVault
from core.runtime.account_instances.store import instance_store, utc_iso
from core.worker_protocol import WorkerEventType
from games.base import GamePlugin


class FileStopEvent:
    def __init__(self, game_id: str, account_id: int) -> None:
        self.game_id = game_id
        self.account_id = account_id
        self._local = False

    def is_set(self) -> bool:
        return self._local or instance_store.is_stop_requested(self.game_id, self.account_id)

    def set(self) -> None:
        self._local = True
        instance_store.request_stop(self.game_id, self.account_id)

    def wait(self, seconds: float) -> bool:
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end:
            if self.is_set():
                return True
            time.sleep(min(0.25, max(0.01, end - time.time())))
        return self.is_set()


def _plugin_for(game_id: str) -> GamePlugin:
    module = importlib.import_module(f"games.{game_id}.plugin")
    candidates = [
        value for value in vars(module).values()
        if inspect.isclass(value) and issubclass(value, GamePlugin) and value is not GamePlugin
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Worker plugin {game_id} is missing or ambiguous")
    plugin = candidates[0]()
    if plugin.game_id != game_id:
        raise RuntimeError(f"Worker plugin mismatch: {plugin.game_id} != {game_id}")
    return plugin


def _set_console_title(title: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(str(title))
    except Exception:
        pass


def _configure_logging(game_id: str, account_id: int, label: str) -> None:
    log_path = instance_store.log_path(game_id, account_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        f"%(asctime)s | %(levelname)s | account:{account_id} | %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)
    _set_console_title(f"GameBot | {game_id} | #{account_id} | {label}")


def run_instance(game_id: str, account_id: int) -> int:
    instance = instance_store.read(game_id, account_id)
    if not instance:
        raise RuntimeError("instance.json was not found")
    account = instance.get("account") if isinstance(instance.get("account"), dict) else {}
    label = str(account.get("label") or f"Account {account_id}")
    _configure_logging(game_id, account_id, label)
    logger = logging.getLogger(__name__)

    stop_event = FileStopEvent(game_id, account_id)
    instance_store.clear_stop(game_id, account_id)

    def handle_stop(*_args) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, handle_stop)

    runtime = instance.get("runtime") if isinstance(instance.get("runtime"), dict) else {}
    runtime.update({
        "status": "running",
        "pid": os.getpid(),
        "started_at": utc_iso(),
        "last_heartbeat_at": utc_iso(),
        "last_error": None,
    })
    instance_store.patch(game_id, account_id, runtime=runtime)

    def emit(event_type: WorkerEventType | str, message: str = "", **payload: Any) -> None:
        event_value = getattr(event_type, "value", str(event_type))
        current = instance_store.read(game_id, account_id)
        rt = current.get("runtime") if isinstance(current.get("runtime"), dict) else {}
        rt["last_event"] = {
            "type": event_value,
            "message": message,
            "payload": payload,
            "created_at": utc_iso(),
        }
        if event_value in {WorkerEventType.HEARTBEAT.value, WorkerEventType.STARTED.value}:
            rt["last_heartbeat_at"] = utc_iso()
        if event_value == WorkerEventType.ERROR.value:
            rt["last_error"] = message
            rt["status"] = "error"
        if event_value == WorkerEventType.STATUS.value:
            rt["status_message"] = message
        service_key = str(payload.get("service_key") or "")
        if service_key:
            service_state = rt.get("service_state") if isinstance(rt.get("service_state"), dict) else {}
            service_state[service_key] = {
                "event_type": event_value,
                "message": message,
                "payload": payload,
                "updated_at": utc_iso(),
            }
            rt["service_state"] = service_state
        instance_store.patch(game_id, account_id, runtime=rt)
        logging.getLogger("worker").info("%s | %s | %s", event_value, message, payload or "")

    try:
        credential = CredentialVault().decrypt(str(instance.get("credential_ciphertext") or ""))
        config = instance.get("config") if isinstance(instance.get("config"), dict) else {}
        plugin = _plugin_for(game_id)
        emit(WorkerEventType.STARTED, "Account instance started", pid=os.getpid())
        asyncio.run(plugin.run_account(credential, config, stop_event, emit))
        return 0
    except Exception as exc:
        logger.exception("Account instance crashed")
        emit(WorkerEventType.ERROR, str(exc), exception_type=type(exc).__name__)
        return 1
    finally:
        current = instance_store.read(game_id, account_id)
        rt = current.get("runtime") if isinstance(current.get("runtime"), dict) else {}
        if rt.get("status") != "error":
            rt["status"] = "stopped"
        rt["pid"] = None
        rt["stopped_at"] = utc_iso()
        instance_store.patch(game_id, account_id, runtime=rt)
        instance_store.clear_stop(game_id, account_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--account-id", required=True, type=int)
    args = parser.parse_args()
    return run_instance(args.game_id, args.account_id)


if __name__ == "__main__":
    raise SystemExit(main())
