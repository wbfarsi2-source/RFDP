from __future__ import annotations

from games.base import GamePlugin


class GameRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, GamePlugin] = {}

    def register(self, plugin: GamePlugin) -> None:
        if plugin.game_id in self._plugins:
            raise ValueError(f"Game plugin already registered: {plugin.game_id}")
        self._plugins[plugin.game_id] = plugin

    def get(self, game_id: str) -> GamePlugin:
        try:
            return self._plugins[game_id]
        except KeyError as exc:
            raise KeyError(f"Unknown game plugin: {game_id}") from exc

    def all(self) -> list[GamePlugin]:
        return list(self._plugins.values())


game_registry = GameRegistry()
