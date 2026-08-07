from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GAMES_ROOT = PROJECT_ROOT / "games"


@dataclass(frozen=True)
class GameLayout:
    game_id: str
    game_root: Path
    runtime_root: Path
    users_root: Path
    shared_root: Path
    manifest: dict[str, Any]

    def ensure(self) -> "GameLayout":
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.users_root.mkdir(parents=True, exist_ok=True)
        self.shared_root.mkdir(parents=True, exist_ok=True)
        return self

    def account_workspace(self, account_id: int) -> Path:
        path = self.users_root / f"account_{int(account_id)}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def shared_workspace(self, service_name: str) -> Path:
        path = self.shared_root / str(service_name).strip().lower()
        path.mkdir(parents=True, exist_ok=True)
        return path


def _read_manifest(game_root: Path, game_id: str) -> dict[str, Any]:
    path = game_root / "manifest.json"
    if not path.exists():
        return {"game_id": game_id}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"game_id": game_id}
    except Exception:
        return {"game_id": game_id}


@lru_cache(maxsize=64)
def game_layout(game_id: str) -> GameLayout:
    normalized = str(game_id or "").strip().lower()
    if not normalized:
        raise ValueError("game_id is empty")
    game_root = GAMES_ROOT / normalized
    manifest = _read_manifest(game_root, normalized)
    runtime_config = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
    runtime_root = game_root / str(runtime_config.get("root") or "runtime")
    users_root = runtime_root / str(runtime_config.get("users") or "users")
    shared_root = runtime_root / str(runtime_config.get("shared") or "shared")
    return GameLayout(
        game_id=normalized,
        game_root=game_root,
        runtime_root=runtime_root,
        users_root=users_root,
        shared_root=shared_root,
        manifest=manifest,
    ).ensure()


def shared_service_location(service_key: str) -> tuple[str, str]:
    key = str(service_key or "").strip()
    if not key:
        raise ValueError("service_key is empty")
    for game_dir in sorted(GAMES_ROOT.iterdir() if GAMES_ROOT.exists() else []):
        if not game_dir.is_dir() or game_dir.name.startswith("_"):
            continue
        manifest = _read_manifest(game_dir, game_dir.name)
        services = manifest.get("shared_services") if isinstance(manifest.get("shared_services"), dict) else {}
        descriptor = services.get(key)
        if isinstance(descriptor, dict):
            return game_dir.name, str(descriptor.get("folder") or key)
    if "_" in key:
        game_id, name = key.split("_", 1)
        if (GAMES_ROOT / game_id).exists():
            return game_id, name
    return "platform", key


def migrate_directory(source: Path, destination: Path) -> bool:
    source = Path(source)
    destination = Path(destination)
    if not source.exists() or source.resolve() == destination.resolve():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.move(str(source), str(destination))
        return True
    for child in source.iterdir():
        target = destination / child.name
        if target.exists():
            continue
        shutil.move(str(child), str(target))
    try:
        source.rmdir()
    except OSError:
        pass
    return True
