from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from core.config import settings
from core.game_layout import PROJECT_ROOT, game_layout, migrate_directory, shared_service_location


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SharedServiceStore:
    """Persistent workspaces for game-owned shared services.

    Canonical path:
        games/<game_id>/runtime/shared/<service_name>/
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._thread_lock = threading.RLock()
        self._project_root_override = Path(project_root) if project_root is not None else None

    @staticmethod
    def normalize_key(service_key: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(service_key or "").strip())
        if not value:
            raise ValueError("service_key is empty")
        return value

    def workspace(self, service_key: str) -> Path:
        normalized = self.normalize_key(service_key)
        if self._project_root_override is not None:
            folder = "Ember" if normalized == "kintara_ember" else normalized
            path = self._project_root_override / folder
            path.mkdir(parents=True, exist_ok=True)
            return path
        game_id, folder = shared_service_location(normalized)
        if game_id == "platform":
            path = PROJECT_ROOT / "data" / "shared_services" / folder
        else:
            path = game_layout(game_id).shared_workspace(folder)
            legacy_candidates = [
                PROJECT_ROOT / settings.shared_services_dir / "Ember" if normalized == "kintara_ember" else PROJECT_ROOT / settings.shared_services_dir / normalized,
                PROJECT_ROOT / "data" / "shared_services" / normalized,
            ]
            for source in legacy_candidates:
                try:
                    migrate_directory(source, path)
                except Exception:
                    continue
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_state(self, service_key: str, **defaults: Any) -> dict[str, Any]:
        current = self.read_state(service_key)
        if current:
            return current
        game_id, service_name = shared_service_location(service_key)
        payload = {
            "service_key": service_key,
            "game_id": game_id,
            "service_name": service_name,
            "status": "stopped",
            "pid": None,
            "workspace": str(self.workspace(service_key)),
            **defaults,
        }
        self.write_state(service_key, payload)
        return payload

    def state_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "service.json"

    def snapshot_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "snapshot.json"

    def log_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "service.log"

    def stop_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "stop.request"

    def refresh_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "refresh.request"

    def lock_path(self, service_key: str) -> Path:
        return self.workspace(service_key) / "service.lock"

    def _read_json(self, path: Path, lock_path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with self._thread_lock, FileLock(str(lock_path), timeout=10):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}

    def _write_json(self, path: Path, lock_path: Path, payload: dict[str, Any]) -> Path:
        data = dict(payload or {})
        data["file_updated_at"] = utc_iso()
        with self._thread_lock, FileLock(str(lock_path), timeout=10):
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        return path

    def read_state(self, service_key: str) -> dict[str, Any]:
        return self._read_json(self.state_path(service_key), self.lock_path(service_key))

    def write_state(self, service_key: str, payload: dict[str, Any]) -> Path:
        return self._write_json(self.state_path(service_key), self.lock_path(service_key), payload)

    def patch_state(self, service_key: str, **values: Any) -> dict[str, Any]:
        current = self.read_state(service_key)
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                merged = dict(current[key])
                merged.update(value)
                current[key] = merged
            else:
                current[key] = value
        self.write_state(service_key, current)
        return current

    def read_snapshot(self, service_key: str) -> dict[str, Any]:
        return self._read_json(self.snapshot_path(service_key), self.lock_path(service_key))

    def write_snapshot(self, service_key: str, payload: dict[str, Any]) -> Path:
        return self._write_json(self.snapshot_path(service_key), self.lock_path(service_key), payload)

    def request_stop(self, service_key: str) -> None:
        self.stop_path(service_key).write_text(utc_iso(), encoding="utf-8")

    def clear_stop(self, service_key: str) -> None:
        self.stop_path(service_key).unlink(missing_ok=True)

    def stop_requested(self, service_key: str) -> bool:
        return self.stop_path(service_key).exists()

    def refresh_requests_path(self, service_key: str) -> Path:
        path = self.workspace(service_key) / "refresh_requests"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def request_refresh(self, service_key: str, request_id: str | None = None) -> str:
        token = self.normalize_key(request_id) if request_id else ""
        if token:
            request_path = self.refresh_requests_path(service_key) / f"{token}.request"
            request_path.write_text(utc_iso(), encoding="utf-8")
            return token
        self.refresh_path(service_key).write_text(utc_iso(), encoding="utf-8")
        return "legacy"

    def consume_refresh_requests(self, service_key: str) -> list[str]:
        tokens: list[str] = []
        folder = self.refresh_requests_path(service_key)
        for path in sorted(folder.glob("*.request")):
            token = path.stem
            path.unlink(missing_ok=True)
            if token:
                tokens.append(token)

        legacy = self.refresh_path(service_key)
        if legacy.exists():
            legacy.unlink(missing_ok=True)
            tokens.append("legacy")
        return tokens

    def consume_refresh_request(self, service_key: str) -> bool:
        return bool(self.consume_refresh_requests(service_key))


shared_service_store = SharedServiceStore()
