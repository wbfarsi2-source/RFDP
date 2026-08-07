from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.game_layout import game_layout
from core.worker_protocol import WorkerEventType
from games.kintara.api.client import KintaraClient
from games.kintara.services.paid.spinner import SpinnerService


async def run_paid_account(
    *,
    cookie: str,
    base_url: str,
    config: dict[str, Any],
    stop_event,
    emit: Callable[..., None],
) -> None:
    if not cookie:
        raise RuntimeError("Kintara cookie is missing")

    account = config.get("account") if isinstance(config.get("account"), dict) else {}
    account_id = int(account.get("id") or 0)
    if account_id <= 0:
        raise RuntimeError("Kintara account id is missing")
    workspace = game_layout("kintara").account_workspace(account_id)
    workspace.mkdir(parents=True, exist_ok=True)

    client = KintaraClient(base_url, cookie)
    status, data = await client.auth_me()
    if status != 200 or data.get("ok") is False:
        raise RuntimeError("Kintara session expired or validation failed")

    features = config.get("features") if isinstance(config.get("features"), dict) else {}
    spinner = SpinnerService(bool(features.get("spinner")))
    spinner.tick(emit, {"account_id": account_id})

    env = os.environ.copy()
    env["KINTARA_COOKIE"] = cookie
    command = [
        sys.executable,
        "-m",
        "games.kintara.engine.account_engine",
        "--workspace",
        str(workspace),
        "--features",
        json.dumps(features, separators=(",", ":")),
    ]
    process = subprocess.Popen(command, cwd=str(Path.cwd()), env=env)
    emit(
        WorkerEventType.STATUS,
        "Kintara automation engine started",
        service_key="automation",
        child_pid=process.pid,
        features=features,
    )

    try:
        while not stop_event.is_set():
            return_code = process.poll()
            if return_code is not None:
                raise RuntimeError(f"Kintara automation engine exited with code {return_code}")
            emit(
                WorkerEventType.HEARTBEAT,
                "Kintara account heartbeat",
                checked_at=datetime.now(timezone.utc).isoformat(),
                child_pid=process.pid,
            )
            for _ in range(10):
                if stop_event.is_set() or process.poll() is not None:
                    break
                await asyncio.sleep(1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
