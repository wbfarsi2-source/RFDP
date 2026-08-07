from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from core.registry import GameRegistry
from games.base import GamePlugin


def discover_game_plugins() -> list[GamePlugin]:
    plugins: list[GamePlugin] = []
    games_root = Path("games")
    for directory in sorted(games_root.iterdir() if games_root.exists() else []):
        if not directory.is_dir() or directory.name.startswith("_") or directory.name == "__pycache__":
            continue
        plugin_file = directory / "plugin.py"
        if not plugin_file.exists():
            continue
        module = importlib.import_module(f"games.{directory.name}.plugin")
        candidates = []
        for value in vars(module).values():
            if inspect.isclass(value) and issubclass(value, GamePlugin) and value is not GamePlugin:
                candidates.append(value)
        if len(candidates) != 1:
            raise RuntimeError(f"Game plugin {directory.name} must expose exactly one GamePlugin subclass")
        plugin = candidates[0]()
        if plugin.game_id != directory.name:
            raise RuntimeError(f"Plugin game_id {plugin.game_id!r} must match directory {directory.name!r}")
        plugins.append(plugin)
    return plugins


def register_discovered_games(registry: GameRegistry) -> list[GamePlugin]:
    plugins = discover_game_plugins()
    for plugin in plugins:
        registry.register(plugin)
    return plugins
