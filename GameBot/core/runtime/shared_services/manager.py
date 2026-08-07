from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from core.game_layout import PROJECT_ROOT
from core.runtime.shared_services.store import shared_service_store
from core.runtime_settings import runtime_settings
from games.kintara.shared_credentials import configured_source, has_shared_cookie, resolve_shared_cookie

logger = logging.getLogger(__name__)

KINTARA_EMBER_SERVICE_KEY = "kintara_ember"


@dataclass
class SharedServiceHandle:
    service_key: str
    process: subprocess.Popen[Any]
    started_at: float


class SharedServiceManager:
    def __init__(self) -> None:
        self.handles: dict[str, SharedServiceHandle] = {}
        self._supervisor_task: asyncio.Task | None = None
        self._stopping = False
        self._restart_counts: dict[str, int] = {}
        self._start_lock = asyncio.Lock()
        self._next_restart_at: dict[str, float] = {}
        self._last_started_at: dict[str, float] = {}

    async def start_supervisor(self) -> None:
        if self._supervisor_task is None:
            self._supervisor_task = asyncio.create_task(self._supervisor_loop())

    async def restore_services(self) -> None:
        self.provision_ember_workspace()
        if runtime_settings.ember_enabled() and runtime_settings.ember_auto_start() and has_shared_cookie():
            ok, detail = await self.start_ember(reset_restart=False)
            logger.info("restore shared ember ok=%s detail=%s", ok, detail)

    def has_ember_cookie(self) -> bool:
        return has_shared_cookie()

    def provision_ember_workspace(self) -> Path:
        configured = has_shared_cookie()
        state = shared_service_store.ensure_state(
            KINTARA_EMBER_SERVICE_KEY,
            service_name="Kintara Ember Shared Monitor",
            status="stopped" if configured else "waiting_for_cookie",
            configured=configured,
            credential_source=configured_source(),
            update_seconds=runtime_settings.ember_update_seconds(),
        )
        workspace = shared_service_store.workspace(KINTARA_EMBER_SERVICE_KEY)
        shared_service_store.patch_state(
            KINTARA_EMBER_SERVICE_KEY,
            workspace=str(workspace),
            configured=configured,
            credential_source=configured_source(),
            enabled=runtime_settings.ember_enabled(),
            visible=runtime_settings.ember_visible(),
            auto_start=runtime_settings.ember_auto_start(),
            update_seconds=runtime_settings.ember_update_seconds(),
            status=(state.get("status") if configured or state.get("status") == "running" else "waiting_for_cookie"),
        )
        self._write_ember_control_files(workspace)
        return workspace

    @staticmethod
    def _write_ember_control_files(workspace: Path) -> None:
        start_file = workspace / "START_MOLTEN.bat"
        stop_file = workspace / "STOP_MOLTEN.bat"
        info_file = workspace / "README.txt"
        start_file.write_text(
            "@echo off\n"
            "setlocal EnableExtensions\n"
            "chcp 65001 >nul\n"
            "title GameBot - Kintara Molten Location Monitor\n"
            f'cd /d "{PROJECT_ROOT.resolve()}"\n'
            "if not exist \".venv\\Scripts\\python.exe\" (\n"
            "  echo [ERROR] The project virtual environment was not found.\n"
            "  pause\n"
            "  exit /b 1\n"
            ")\n"
            '".venv\\Scripts\\python.exe" -m games.kintara.services.ember.runner --service-key kintara_ember\n'
            "exit /b %ERRORLEVEL%\n",
            encoding="utf-8",
        )
        stop_file.write_text(
            "@echo off\n"
            "setlocal EnableExtensions\n"
            "chcp 65001 >nul\n"
            "echo stop>\"%~dp0stop.request\"\n"
            "echo Stop request created. The platform supervisor restarts Ember while auto-start is enabled.\n"
            "timeout /t 2 /nobreak >nul\n",
            encoding="utf-8",
        )
        info_file.write_text(
            "Kintara-owned shared Molten Location service workspace\n\n"
            "The default credential is KINTARA_COOKIE from the project .env file.\n"
            "An encrypted admin override can be selected from Telegram /admin.\n\n"
            "service.json    Current process state\n"
            "snapshot.json   Shared top-three server snapshot\n"
            "service.log     Service log\n"
            "START_MOLTEN.bat Manual emergency start\n"
            "STOP_MOLTEN.bat Temporary stop request\n",
            encoding="utf-8",
        )
        (workspace / "START_EMBER.bat").write_text(start_file.read_text(encoding="utf-8"), encoding="utf-8")
        (workspace / "STOP_EMBER.bat").write_text(stop_file.read_text(encoding="utf-8"), encoding="utf-8")

    @staticmethod
    def _pid_is_ember(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            process = psutil.Process(int(pid))
            if not process.is_running():
                return False
            command = " ".join(process.cmdline()).lower()
            return (
                "games.kintara.services.ember.runner" in command
                or "run_shared_ember.py" in command
                or "games.kintara.ember_service" in command
            )
        except Exception:
            return False

    def ember_status(self) -> dict[str, Any]:
        workspace = self.provision_ember_workspace()
        state = shared_service_store.read_state(KINTARA_EMBER_SERVICE_KEY)
        handle = self.handles.get(KINTARA_EMBER_SERVICE_KEY)
        running = bool(handle and handle.process.poll() is None)
        if not running:
            running = self._pid_is_ember(state.get("pid"))
        state["running"] = running
        state["configured"] = has_shared_cookie()
        state["credential_source"] = configured_source()
        state["enabled"] = runtime_settings.ember_enabled()
        state["visible"] = runtime_settings.ember_visible()
        state["auto_start"] = runtime_settings.ember_auto_start()
        state["update_seconds"] = runtime_settings.ember_update_seconds()
        state["workspace"] = str(workspace)
        state["snapshot"] = shared_service_store.read_snapshot(KINTARA_EMBER_SERVICE_KEY)
        return state

    async def start_ember(self, *, reset_restart: bool = True) -> tuple[bool, str]:
        async with self._start_lock:
            return await self._start_ember_impl(reset_restart=reset_restart)

    async def _start_ember_impl(self, *, reset_restart: bool = True) -> tuple[bool, str]:
        service_key = KINTARA_EMBER_SERVICE_KEY
        workspace = self.provision_ember_workspace()
        if not runtime_settings.ember_enabled():
            shared_service_store.patch_state(service_key, status="disabled", pid=None)
            return False, "The Ember service is disabled in the admin panel."

        current = self.ember_status()
        if current.get("running"):
            return False, "The central Ember process is already running."

        try:
            credential = resolve_shared_cookie()
        except Exception as exc:
            shared_service_store.patch_state(
                service_key,
                status="waiting_for_cookie",
                pid=None,
                workspace=str(workspace),
                configured=False,
                last_error=str(exc),
            )
            return False, str(exc)

        shared_service_store.clear_stop(service_key)
        environment = os.environ.copy()
        environment["KINTARA_EMBER_COOKIE"] = credential.cookie
        environment["KINTARA_EMBER_COOKIE_SOURCE"] = credential.source
        command = [
            sys.executable,
            "-m",
            "games.kintara.services.ember.runner",
            "--service-key",
            service_key,
            "--update-seconds",
            str(runtime_settings.ember_update_seconds()),
        ]
        kwargs: dict[str, Any] = {"cwd": str(PROJECT_ROOT), "env": environment}
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_CONSOLE
            creation_flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            kwargs["creationflags"] = creation_flags
        process = subprocess.Popen(command, **kwargs)
        started_at = time.time()
        self.handles[service_key] = SharedServiceHandle(service_key, process, started_at)
        self._last_started_at[service_key] = started_at
        self._next_restart_at.pop(service_key, None)
        if reset_restart:
            self._restart_counts[service_key] = 0
        shared_service_store.patch_state(
            service_key,
            status="starting",
            pid=process.pid,
            started_by="platform",
            workspace=str(workspace),
            configured=True,
            credential_source=credential.source,
            update_seconds=runtime_settings.ember_update_seconds(),
            last_error=None,
        )
        return True, f"The central Ember process started. PID: {process.pid}"

    async def stop_ember(self, timeout: float = 15.0) -> tuple[bool, str]:
        service_key = KINTARA_EMBER_SERVICE_KEY
        state = shared_service_store.read_state(service_key)
        handle = self.handles.pop(service_key, None)
        pid = int((handle.process.pid if handle else state.get("pid")) or 0)
        handle_alive = bool(handle and handle.process.poll() is None)
        if not pid or (not handle_alive and not self._pid_is_ember(pid)):
            shared_service_store.patch_state(service_key, status="stopped", pid=None)
            shared_service_store.clear_stop(service_key)
            return False, "The central Ember process is not running."

        shared_service_store.request_stop(service_key)
        if handle:
            try:
                await asyncio.to_thread(handle.process.wait, timeout)
            except subprocess.TimeoutExpired:
                handle.process.terminate()
                try:
                    await asyncio.to_thread(handle.process.wait, 5)
                except subprocess.TimeoutExpired:
                    handle.process.kill()
        else:
            try:
                process = psutil.Process(pid)
                process.terminate()
                await asyncio.to_thread(process.wait, timeout)
            except psutil.TimeoutExpired:
                try:
                    psutil.Process(pid).kill()
                except Exception:
                    pass
            except Exception:
                pass
        shared_service_store.patch_state(service_key, status="stopped", pid=None)
        shared_service_store.clear_stop(service_key)
        self._restart_counts.pop(service_key, None)
        self._next_restart_at.pop(service_key, None)
        self._last_started_at.pop(service_key, None)
        return True, "The central Ember process stopped."

    async def restart_ember(self) -> tuple[bool, str]:
        await self.stop_ember()
        return await self.start_ember(reset_restart=True)

    async def shutdown(self) -> None:
        self._stopping = True
        if self._supervisor_task:
            self._supervisor_task.cancel()
        await self.stop_ember()

    def _ember_running_without_side_effects(self) -> bool:
        service_key = KINTARA_EMBER_SERVICE_KEY
        handle = self.handles.get(service_key)
        if handle is not None and handle.process.poll() is None:
            return True
        state = shared_service_store.read_state(service_key)
        return self._pid_is_ember(state.get("pid"))

    async def _supervisor_loop(self) -> None:
        service_key = KINTARA_EMBER_SERVICE_KEY
        while not self._stopping:
            try:
                now = time.time()
                handle = self.handles.get(service_key)

                if handle and handle.process.poll() is not None:
                    exit_code = handle.process.returncode
                    uptime = max(0.0, now - handle.started_at)
                    self.handles.pop(service_key, None)
                    shared_service_store.patch_state(
                        service_key,
                        status="error",
                        pid=None,
                        last_error=f"Shared service exited with code {exit_code}",
                    )

                    if uptime >= 300:
                        self._restart_counts[service_key] = 0

                    if runtime_settings.ember_enabled() and runtime_settings.ember_auto_start() and has_shared_cookie():
                        count = self._restart_counts.get(service_key, 0) + 1
                        self._restart_counts[service_key] = count
                        delay = min(300.0, 15.0 * (2 ** min(max(count - 1, 0), 4)))
                        self._next_restart_at[service_key] = now + delay
                        logger.warning(
                            "Molten monitor exited with code %s after %.1fs; restart scheduled in %.0fs",
                            exit_code,
                            uptime,
                            delay,
                        )

                running = self._ember_running_without_side_effects()
                should_run = (
                    runtime_settings.ember_enabled()
                    and runtime_settings.ember_auto_start()
                    and has_shared_cookie()
                )

                if should_run and not running:
                    next_restart = self._next_restart_at.get(service_key, 0.0)
                    if now >= next_restart:
                        await self.start_ember(reset_restart=False)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Shared service supervisor failed")

            await asyncio.sleep(10)
