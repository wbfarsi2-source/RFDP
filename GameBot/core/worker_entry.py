from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import multiprocessing as mp
import signal
from typing import Any

from core.worker_protocol import WorkerEvent, WorkerEventType
from games.base import GamePlugin


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


def worker_process_main(
    *,
    game_id: str,
    account_id: int,
    credential: dict[str, Any],
    config: dict[str, Any],
    stop_event: mp.synchronize.Event,
    event_queue: mp.Queue,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s | %(levelname)s | worker:{account_id} | %(message)s",
    )

    def emit(event_type: WorkerEventType, message: str = "", **payload: Any) -> None:
        event_queue.put(WorkerEvent(event_type, account_id, message, payload).__dict__)

    def handle_stop(*_args) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, handle_stop)

    plugin = _plugin_for(game_id)
    emit(WorkerEventType.STARTED, "Worker started")

    try:
        asyncio.run(plugin.run_account(credential, config, stop_event, emit))
    except Exception as exc:
        emit(WorkerEventType.ERROR, str(exc), exception_type=type(exc).__name__)
        raise
    finally:
        emit(WorkerEventType.STOPPED, "Worker stopped")
