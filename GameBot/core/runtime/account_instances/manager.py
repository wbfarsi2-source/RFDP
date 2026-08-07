from __future__ import annotations
from core.locale_text import localized_literal
import asyncio
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psutil
from sqlalchemy import select
from core.database import SessionLocal
from core.feature_flags import feature_flags
from core.runtime.account_instances.store import instance_store
from core.models import GameAccount, User
from core.registry import GameRegistry
from core.repositories import get_account, latest_active_subscription
from core.runtime_settings import runtime_settings
logger = logging.getLogger(__name__)

@dataclass
class WorkerHandle:
    account_id: int
    game_id: str
    pid: int
    process: subprocess.Popen[Any] | None
    started_at: float
    last_heartbeat: float

class AccountProcessManager:
    """One managed workspace, one instance.json, and one CMD/process per paid game account."""

    def __init__(self, registry: GameRegistry) -> None:
        self.registry = registry
        self.handles: dict[int, WorkerHandle] = {}
        self.restart_counts: dict[int, int] = {}
        self._restart_tasks: dict[int, asyncio.Task] = {}
        self._supervisor_task: asyncio.Task | None = None
        self._stopping = False
        self._feature_flags_version = feature_flags.version

    async def start_supervisor(self) -> None:
        if self._supervisor_task is None:
            self._supervisor_task = asyncio.create_task(self._supervisor_loop())

    @staticmethod
    def _process_matches(pid: int, account_id: int) -> bool:
        try:
            process = psutil.Process(int(pid))
            if not process.is_running():
                return False
            cmdline = ' '.join(process.cmdline()).lower()
            return (('core.runtime.account_instances.runner' in cmdline or 'core.account_runtime' in cmdline) and '--account-id' in cmdline and str(int(account_id)) in cmdline)
        except Exception:
            return False

    @staticmethod
    def _handle_alive(handle: WorkerHandle) -> bool:
        if handle.process is not None:
            return handle.process.poll() is None
        return AccountProcessManager._process_matches(handle.pid, handle.account_id)

    async def restore_workers(self) -> None:
        async with SessionLocal() as session:
            rows = list(await session.scalars(select(GameAccount)))
        for account in rows:
            async with SessionLocal() as session:
                if await latest_active_subscription(session, account.id) is None:
                    continue
            instance = instance_store.read(account.game_id, account.id)
            runtime = instance.get('runtime') if isinstance(instance.get('runtime'), dict) else {}
            desired_state = str(runtime.get('desired_state') or ('running' if account.status == 'running' else 'stopped'))
            if desired_state != 'running':
                continue
            pid = int(runtime.get('pid') or account.worker_pid or 0)
            if pid and self._process_matches(pid, account.id):
                self.handles[account.id] = WorkerHandle(account_id=account.id, game_id=account.game_id, pid=pid, process=None, started_at=time.time(), last_heartbeat=self._heartbeat_epoch(runtime) or time.time())
                logger.info('attached to existing account CMD account=%s pid=%s', account.id, pid)
                continue
            ok, detail = await self.start_account(account.id, reset_restart=False)
            logger.info('restore worker account=%s ok=%s detail=%s', account.id, ok, detail)

    async def start_account(self, account_id: int, *, reset_restart: bool=True) -> tuple[bool, str]:
        existing = self.handles.get(account_id)
        if existing and self._handle_alive(existing):
            return (False, localized_literal('core.worker_manager.c2d18cc7c18f'))
        async with SessionLocal() as session:
            account = await get_account(session, account_id)
            if account is None:
                return (False, localized_literal('core.worker_manager.38e459510c4d'))
            subscription = await latest_active_subscription(session, account_id)
            if subscription is None:
                return (False, localized_literal('core.worker_manager.b5fbff893293'))
            if not feature_flags.game_enabled(account.game_id):
                account.status = 'disabled'
                account.worker_pid = None
                await session.commit()
                return (False, localized_literal('core.worker_manager.4faa854337fe'))
            user = await session.get(User, account.user_id)
            plugin = self.registry.get(account.game_id)
            subscription_data = {'id': subscription.id, 'plan_key': subscription.plan_key, 'starts_at': subscription.starts_at.isoformat(), 'expires_at': subscription.expires_at.isoformat(), 'status': subscription.status}
            account_data = {'id': account.id, 'user_id': account.user_id, 'telegram_user_id': int(user.telegram_user_id if user else 0), 'game_id': account.game_id, 'label': account.label, 'external_account_hash': account.external_account_hash, 'credential_hint': account.credential_hint or ''}
            config = plugin.build_worker_config(account=account_data, subscription=subscription_data)
            features = config.get('features') if isinstance(config.get('features'), dict) else {}
            services = [{'key': str(name), 'enabled': bool(enabled)} for name, enabled in features.items() if bool(enabled)]
            instance_store.prepare(account=account_data, credential_ciphertext=account.credential_ciphertext, subscription=subscription_data, services=services, config=config)
            instance_store.set_desired_state(account.game_id, account.id, 'running')
            command = [sys.executable, '-m', 'core.runtime.account_instances.runner', '--game-id', account.game_id, '--account-id', str(account.id)]
            kwargs: dict[str, Any] = {'cwd': str(Path.cwd()), 'env': os.environ.copy()}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NEW_CONSOLE
            process = subprocess.Popen(command, **kwargs)
            self.handles[account.id] = WorkerHandle(account_id=account.id, game_id=account.game_id, pid=int(process.pid), process=process, started_at=time.time(), last_heartbeat=time.time())
            if reset_restart:
                self.restart_counts[account.id] = 0
            account.status = 'running'
            account.worker_pid = process.pid
            account.last_error = None
            await session.commit()
        return (True, f"{localized_literal('core.worker_manager.482d7f42113f')}{process.pid}")

    async def stop_account(self, account_id: int, timeout: float=15.0) -> tuple[bool, str]:
        restart_task = self._restart_tasks.pop(account_id, None)
        if restart_task:
            restart_task.cancel()
        handle = self.handles.pop(account_id, None)
        if handle is None:
            async with SessionLocal() as session:
                account = await get_account(session, account_id)
            if account:
                instance = instance_store.read(account.game_id, account.id)
                runtime = instance.get('runtime') if isinstance(instance.get('runtime'), dict) else {}
                pid = int(runtime.get('pid') or account.worker_pid or 0)
                if pid and self._process_matches(pid, account_id):
                    handle = WorkerHandle(account_id, account.game_id, pid, None, time.time(), time.time())
        if handle is None or not self._handle_alive(handle):
            async with SessionLocal() as session:
                account = await get_account(session, account_id)
            if account:
                instance_store.set_desired_state(account.game_id, account_id, 'stopped')
            await self._mark_stopped(account_id)
            return (False, localized_literal('core.worker_manager.be608e123049'))
        instance_store.set_desired_state(handle.game_id, account_id, 'stopped')
        instance_store.request_stop(handle.game_id, account_id)
        if handle.process is not None:
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
                process = psutil.Process(handle.pid)
                process.terminate()
                await asyncio.to_thread(process.wait, timeout)
            except psutil.TimeoutExpired:
                try:
                    psutil.Process(handle.pid).kill()
                except Exception:
                    pass
            except Exception:
                pass
        instance_store.clear_stop(handle.game_id, account_id)
        self.restart_counts.pop(account_id, None)
        await self._mark_stopped(account_id)
        return (True, localized_literal('core.worker_manager.6a9fd3057cc0'))

    async def restart_account(self, account_id: int) -> tuple[bool, str]:
        await self._terminate_without_manual_stop(account_id)
        return await self.start_account(account_id, reset_restart=True)

    async def stop_game(self, game_id: str) -> int:
        account_ids = [account_id for account_id, handle in self.handles.items() if handle.game_id == game_id]
        stopped = 0
        for account_id in account_ids:
            ok, _ = await self.stop_account(account_id)
            if ok:
                stopped += 1
        return stopped

    async def restart_game(self, game_id: str) -> tuple[int, int]:
        async with SessionLocal() as session:
            account_ids = [int(value) for value in await session.scalars(select(GameAccount.id).where(GameAccount.game_id == game_id))]
        started = failed = 0
        for account_id in account_ids:
            async with SessionLocal() as session:
                if await latest_active_subscription(session, account_id) is None:
                    continue
            ok, _ = await self.restart_account(account_id)
            started += int(ok)
            failed += int(not ok)
        return (started, failed)

    async def stop_all(self) -> int:
        stopped = 0
        for account_id in list(self.handles):
            ok, _ = await self.stop_account(account_id)
            stopped += int(ok)
        return stopped

    async def restart_all_active(self) -> tuple[int, int]:
        async with SessionLocal() as session:
            account_ids = [int(value) for value in await session.scalars(select(GameAccount.id))]
        started = failed = 0
        for account_id in account_ids:
            async with SessionLocal() as session:
                if await latest_active_subscription(session, account_id) is None:
                    continue
            ok, _ = await self.restart_account(account_id)
            started += int(ok)
            failed += int(not ok)
        return (started, failed)

    async def shutdown(self) -> None:
        self._stopping = True
        if self._supervisor_task:
            self._supervisor_task.cancel()
        for task in self._restart_tasks.values():
            task.cancel()
        for account_id in list(self.handles):
            await self._terminate_without_manual_stop(account_id)
            await self._mark_paused(account_id)

    async def _terminate_without_manual_stop(self, account_id: int, timeout: float=8.0) -> None:
        handle = self.handles.pop(account_id, None)
        if not handle:
            return
        instance_store.request_stop(handle.game_id, account_id)
        if handle.process is not None:
            try:
                await asyncio.to_thread(handle.process.wait, timeout)
            except subprocess.TimeoutExpired:
                handle.process.terminate()
        else:
            try:
                process = psutil.Process(handle.pid)
                process.terminate()
                await asyncio.to_thread(process.wait, timeout)
            except Exception:
                pass
        instance_store.clear_stop(handle.game_id, account_id)

    async def _mark_stopped(self, account_id: int) -> None:
        async with SessionLocal() as session:
            account = await get_account(session, account_id)
            if account:
                account.status = 'stopped'
                account.worker_pid = None
                await session.commit()

    async def _mark_paused(self, account_id: int) -> None:
        async with SessionLocal() as session:
            account = await get_account(session, account_id)
            if account:
                account.status = 'paused'
                account.worker_pid = None
                await session.commit()

    async def _mark_error(self, account_id: int, error: str) -> None:
        async with SessionLocal() as session:
            account = await get_account(session, account_id)
            if account:
                account.status = 'error'
                account.worker_pid = None
                account.last_error = str(error)[:2000]
                await session.commit()

    @staticmethod
    def _heartbeat_epoch(runtime: dict[str, Any]) -> float:
        value = runtime.get('last_heartbeat_at')
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
        except Exception:
            return 0.0

    async def _sync_instance_state(self, handle: WorkerHandle) -> None:
        instance = instance_store.read(handle.game_id, handle.account_id)
        runtime = instance.get('runtime') if isinstance(instance.get('runtime'), dict) else {}
        heartbeat = self._heartbeat_epoch(runtime)
        if heartbeat > 0:
            handle.last_heartbeat = heartbeat
            if time.time() - handle.started_at > 300:
                self.restart_counts[handle.account_id] = 0
        async with SessionLocal() as session:
            account = await get_account(session, handle.account_id)
            if account:
                account.worker_pid = handle.pid if self._handle_alive(handle) else None
                if heartbeat > 0:
                    account.last_heartbeat_at = datetime.fromtimestamp(heartbeat, timezone.utc)
                error = runtime.get('last_error')
                if error:
                    account.last_error = str(error)[:2000]
                await session.commit()

    async def _expire_accounts(self) -> None:
        for account_id in list(self.handles):
            async with SessionLocal() as session:
                if await latest_active_subscription(session, account_id) is None:
                    await self.stop_account(account_id)

    async def _schedule_restart(self, account_id: int, reason: str) -> None:
        if self._stopping or account_id in self._restart_tasks:
            return
        count = self.restart_counts.get(account_id, 0) + 1
        self.restart_counts[account_id] = count
        if count > runtime_settings.worker_restart_limit():
            await self._mark_error(account_id, f'Restart limit reached: {reason}')
            return
        delay = min(60, 2 ** min(count, 5))

        async def restart_later() -> None:
            try:
                await asyncio.sleep(delay)
                async with SessionLocal() as session:
                    account = await get_account(session, account_id)
                    if account is None or await latest_active_subscription(session, account_id) is None:
                        return
                if instance_store.desired_state(account.game_id, account_id) != 'running':
                    return
                ok, detail = await self.start_account(account_id, reset_restart=False)
                logger.warning('automatic CMD restart account=%s attempt=%s ok=%s detail=%s', account_id, count, ok, detail)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception('automatic account restart failed account=%s', account_id)
            finally:
                self._restart_tasks.pop(account_id, None)
        self._restart_tasks[account_id] = asyncio.create_task(restart_later())

    async def _enforce_game_availability(self) -> None:
        for account_id, handle in list(self.handles.items()):
            if not feature_flags.game_enabled(handle.game_id):
                await self._terminate_without_manual_stop(account_id)
                await self._mark_error(account_id, 'Game disabled by administrator or control server')

    async def _reload_workers_for_feature_flags(self) -> None:
        if feature_flags.version == self._feature_flags_version:
            return
        self._feature_flags_version = feature_flags.version
        for account_id in list(self.handles):
            await self._terminate_without_manual_stop(account_id)
            ok, detail = await self.start_account(account_id, reset_restart=False)
            if not ok:
                await self._mark_error(account_id, f'Feature flag reload failed: {detail}')

    async def _supervisor_loop(self) -> None:
        while not self._stopping:
            try:
                await self._expire_accounts()
                await self._enforce_game_availability()
                await self._reload_workers_for_feature_flags()
                now = time.time()
                for account_id, handle in list(self.handles.items()):
                    if not self._handle_alive(handle):
                        exit_code = handle.process.returncode if handle.process is not None else 'unknown'
                        self.handles.pop(account_id, None)
                        reason = f'Account CMD exited with code {exit_code}'
                        await self._mark_error(account_id, reason)
                        if instance_store.desired_state(handle.game_id, account_id) == 'running':
                            await self._schedule_restart(account_id, reason)
                        continue
                    await self._sync_instance_state(handle)
                    if now - handle.last_heartbeat > runtime_settings.worker_heartbeat_timeout():
                        logger.warning('account CMD heartbeat timeout account=%s', account_id)
                        await self._terminate_without_manual_stop(account_id)
                        await self._mark_error(account_id, 'Heartbeat timeout')
                        if instance_store.desired_state(handle.game_id, account_id) == 'running':
                            await self._schedule_restart(account_id, 'Heartbeat timeout')
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception('Account supervisor iteration failed')
            await asyncio.sleep(3)
