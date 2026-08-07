from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from core.config import settings
from core.game_layout import PROJECT_ROOT, game_layout, migrate_directory


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountInstanceStore:
    """Persistent account workspaces owned by each game plugin.

    Canonical path:
        games/<game_id>/runtime/users/account_<account_id>/

    The database remains the source of truth. The instance file is the process-facing
    snapshot used for launch, supervision, diagnostics, and crash recovery.
    """

    def __init__(self) -> None:
        self._thread_lock = threading.RLock()

    def _migrate_legacy_workspace(self, game_id: str, account_id: int, destination: Path) -> None:
        legacy_roots = [
            PROJECT_ROOT / settings.instances_dir / str(game_id) / f"account_{int(account_id)}",
            PROJECT_ROOT / "data" / "instances" / str(game_id) / f"account_{int(account_id)}",
        ]
        for source in legacy_roots:
            try:
                migrate_directory(source, destination)
            except Exception:
                continue

    def workspace(self, game_id: str, account_id: int) -> Path:
        path = game_layout(game_id).account_workspace(account_id)
        self._migrate_legacy_workspace(game_id, account_id, path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def instance_path(self, game_id: str, account_id: int) -> Path:
        return self.workspace(game_id, account_id) / "instance.json"

    def owner_path(self, game_id: str, account_id: int) -> Path:
        return self.workspace(game_id, account_id) / "owner.json"

    def log_path(self, game_id: str, account_id: int) -> Path:
        return self.workspace(game_id, account_id) / "worker.log"

    def stop_path(self, game_id: str, account_id: int) -> Path:
        return self.workspace(game_id, account_id) / "stop.request"

    def lock_path(self, game_id: str, account_id: int) -> Path:
        return self.workspace(game_id, account_id) / "instance.lock"

    def read(self, game_id: str, account_id: int) -> dict[str, Any]:
        path = self.instance_path(game_id, account_id)
        if not path.exists():
            return {}
        with self._thread_lock, FileLock(str(self.lock_path(game_id, account_id)), timeout=10):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    def write(self, game_id: str, account_id: int, payload: dict[str, Any]) -> Path:
        path = self.instance_path(game_id, account_id)
        payload = dict(payload or {})
        payload["updated_at"] = utc_iso()
        with self._thread_lock, FileLock(str(self.lock_path(game_id, account_id)), timeout=10):
            temp = path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        return path

    def patch(self, game_id: str, account_id: int, **values: Any) -> dict[str, Any]:
        current = self.read(game_id, account_id)
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                merged = dict(current[key])
                merged.update(value)
                current[key] = merged
            else:
                current[key] = value
        self.write(game_id, account_id, current)
        return current

    def desired_state(self, game_id: str, account_id: int) -> str:
        instance = self.read(game_id, account_id)
        runtime = instance.get("runtime") if isinstance(instance.get("runtime"), dict) else {}
        value = str(runtime.get("desired_state") or "running").strip().lower()
        return value if value in {"running", "stopped"} else "running"

    def set_desired_state(self, game_id: str, account_id: int, state: str) -> None:
        instance = self.read(game_id, account_id)
        runtime = instance.get("runtime") if isinstance(instance.get("runtime"), dict) else {}
        runtime["desired_state"] = "stopped" if str(state).lower() == "stopped" else "running"
        self.patch(game_id, account_id, runtime=runtime)

    def prepare(
        self,
        *,
        account: dict[str, Any],
        credential_ciphertext: str,
        subscription: dict[str, Any] | None,
        services: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> Path:
        game_id = str(account["game_id"])
        account_id = int(account["id"])
        workspace = self.workspace(game_id, account_id)
        prior = self.read(game_id, account_id)
        prior_runtime = prior.get("runtime") if isinstance(prior.get("runtime"), dict) else {}
        payload = {
            "schema_version": 2,
            "layout": {
                "game_root": str(game_layout(game_id).game_root),
                "workspace": str(workspace),
                "ownership": "game_plugin",
            },
            "account": {
                "id": account_id,
                "user_id": int(account["user_id"]),
                "telegram_user_id": int(account.get("telegram_user_id") or 0),
                "game_id": game_id,
                "label": str(account.get("label") or f"Account {account_id}"),
                "external_account_hash": str(account.get("external_account_hash") or ""),
                "credential_hint": str(account.get("credential_hint") or ""),
            },
            "credential_ciphertext": credential_ciphertext,
            "subscription": subscription,
            "services": services,
            "config": config,
            "runtime": {
                "desired_state": str(prior_runtime.get("desired_state") or "running"),
                "status": str(prior_runtime.get("status") or "ready"),
                "pid": prior_runtime.get("pid"),
                "started_at": prior_runtime.get("started_at"),
                "last_heartbeat_at": prior_runtime.get("last_heartbeat_at"),
                "last_error": prior_runtime.get("last_error"),
                "service_state": prior_runtime.get("service_state") or {},
                "restart_count": int(prior_runtime.get("restart_count") or 0),
            },
        }
        self.write(game_id, account_id, payload)
        self.owner_path(game_id, account_id).write_text(
            json.dumps(payload["account"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_control_files(game_id, account_id, workspace)
        self.clear_stop(game_id, account_id)
        return self.instance_path(game_id, account_id)

    @staticmethod
    def _write_control_files(game_id: str, account_id: int, workspace: Path) -> None:
        start_path = workspace / "START_ACCOUNT.bat"
        stop_path = workspace / "STOP_ACCOUNT.bat"
        readme_path = workspace / "README.txt"
        project_root = PROJECT_ROOT.resolve()
        start_path.write_text(
            "@echo off\n"
            "setlocal EnableExtensions\n"
            "chcp 65001 >nul\n"
            f"title GameBot - {game_id} - Account {account_id}\n"
            f'cd /d "{project_root}"\n'
            "if not exist \".venv\\Scripts\\python.exe\" (\n"
            "  echo [ERROR] The project virtual environment was not found.\n"
            "  pause\n"
            "  exit /b 1\n"
            ")\n"
            f'".venv\\Scripts\\python.exe" -m core.runtime.account_instances.runner --game-id {game_id} --account-id {account_id}\n'
            "exit /b %ERRORLEVEL%\n",
            encoding="utf-8",
        )
        stop_path.write_text(
            "@echo off\n"
            "setlocal EnableExtensions\n"
            "chcp 65001 >nul\n"
            "echo stop>\"%~dp0stop.request\"\n"
            "echo Stop request created. The platform supervisor may restart this account unless it was stopped from Telegram.\n"
            "timeout /t 2 /nobreak >nul\n",
            encoding="utf-8",
        )
        readme_path.write_text(
            "Managed game account workspace\n\n"
            "instance.json      Encrypted process configuration and runtime state\n"
            "owner.json         Non-secret account ownership summary\n"
            "worker.log         Account process log\n"
            "START_ACCOUNT.bat  Manual emergency start\n"
            "STOP_ACCOUNT.bat   Temporary process stop request\n\n"
            "Closing the CMD window is treated as a crash and the platform restarts it.\n"
            "Use the Telegram bot to stop the account permanently.\n",
            encoding="utf-8",
        )

    def request_stop(self, game_id: str, account_id: int) -> None:
        self.stop_path(game_id, account_id).write_text(utc_iso(), encoding="utf-8")

    def clear_stop(self, game_id: str, account_id: int) -> None:
        self.stop_path(game_id, account_id).unlink(missing_ok=True)

    def is_stop_requested(self, game_id: str, account_id: int) -> bool:
        return self.stop_path(game_id, account_id).exists()

    def delete(self, game_id: str, account_id: int) -> None:
        path = game_layout(game_id).users_root / f"account_{int(account_id)}"
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def list_instances(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        games_root = PROJECT_ROOT / "games"
        for path in games_root.glob("*/runtime/users/account_*/instance.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                data["instance_path"] = str(path)
                rows.append(data)
        rows.sort(key=lambda row: int(((row.get("account") or {}).get("id")) or 0))
        return rows


instance_store = AccountInstanceStore()
