from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from core.config import settings
from core.runtime_settings import runtime_settings

logger = logging.getLogger(__name__)


class FeatureFlagService:
    """Feature flags with three layers.

    Precedence: local plugin defaults < admin database overrides < remote control server.
    Remote values therefore act as the final authority when configured.
    """

    def __init__(self) -> None:
        self._local: dict[str, Any] = {"games": {}}
        self._remote: dict[str, Any] = {"games": {}}
        self._task: asyncio.Task | None = None
        self.version: int = 0
        self._stopping = False
        self._runtime_version = -1

    def load_local(self) -> None:
        merged: dict[str, Any] = {"games": {}}
        games_dir = Path("games")
        if games_dir.exists():
            for path in games_dir.glob("*/features.json"):
                try:
                    game_id = path.parent.name
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        merged["games"][game_id] = raw
                except Exception:
                    logger.exception("Failed to load feature flags from %s", path)
        if merged != self._local:
            self._local = merged
            self.version += 1

    async def start(self) -> None:
        self.load_local()
        self._runtime_version = runtime_settings.version
        if settings.feature_flags_url and self._task is None:
            self._task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def touch_runtime_overrides(self) -> None:
        if runtime_settings.version != self._runtime_version:
            self._runtime_version = runtime_settings.version
            self.version += 1

    async def _refresh_loop(self) -> None:
        while not self._stopping:
            try:
                await self.refresh_remote()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Remote feature flag refresh failed; keeping last safe snapshot")
            await asyncio.sleep(max(15, settings.feature_flags_refresh_seconds))

    async def refresh_remote(self) -> None:
        headers = {}
        if settings.feature_flags_token:
            headers["Authorization"] = f"Bearer {settings.feature_flags_token}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(settings.feature_flags_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), dict):
            raise ValueError("Invalid feature flag payload")
        if payload != self._remote:
            self._remote = payload
            self.version += 1
            logger.info("Remote feature flags updated version=%s", self.version)

    def _local_game(self, game_id: str) -> dict[str, Any]:
        games = self._local.get("games") if isinstance(self._local, dict) else {}
        game = games.get(game_id) if isinstance(games, dict) else {}
        return game if isinstance(game, dict) else {}

    def _remote_game(self, game_id: str) -> dict[str, Any]:
        games = self._remote.get("games") if isinstance(self._remote, dict) else {}
        game = games.get(game_id) if isinstance(games, dict) else {}
        return game if isinstance(game, dict) else {}

    def game_enabled(self, game_id: str, default: bool = True) -> bool:
        self.touch_runtime_overrides()
        value = runtime_settings.game_enabled(game_id, default)
        remote = self._remote_game(game_id).get("_game")
        if isinstance(remote, dict) and "enabled" in remote:
            value = bool(remote.get("enabled"))
        return bool(value)

    def game_visible(self, game_id: str, default: bool = True) -> bool:
        self.touch_runtime_overrides()
        value = runtime_settings.game_visible(game_id, default)
        remote = self._remote_game(game_id).get("_game")
        if isinstance(remote, dict) and "visible" in remote:
            value = bool(remote.get("visible"))
        return bool(value)

    def feature(self, game_id: str, feature_name: str) -> dict[str, Any]:
        self.touch_runtime_overrides()
        local = self._local_game(game_id).get(feature_name)
        row: dict[str, Any] = dict(local) if isinstance(local, dict) else {}

        enabled_key = f"games.{game_id}.features.{feature_name}.enabled"
        visible_key = f"games.{game_id}.features.{feature_name}.visible"
        if runtime_settings.has(enabled_key):
            row["enabled"] = runtime_settings.get_bool(enabled_key, bool(row.get("enabled", False)))
        if runtime_settings.has(visible_key):
            row["visible"] = runtime_settings.get_bool(visible_key, bool(row.get("visible", False)))

        remote = self._remote_game(game_id).get(feature_name)
        if isinstance(remote, dict):
            row.update(remote)
        return row

    def enabled(self, game_id: str, feature_name: str, default: bool = False) -> bool:
        return bool(self.feature(game_id, feature_name).get("enabled", default))

    def visible(self, game_id: str, feature_name: str, default: bool = False) -> bool:
        return bool(self.feature(game_id, feature_name).get("visible", default))


feature_flags = FeatureFlagService()
