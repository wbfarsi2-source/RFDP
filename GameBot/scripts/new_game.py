from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_TEMPLATE = '''from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from games.base import CredentialValidation, GamePlugin, PlanDefinition, TrialDefinition


class {class_name}Plugin(GamePlugin):
    game_id = "{game_id}"
    display_name_fa = "{display_name}"
    display_name_en = "{display_name}"

    def plans(self) -> list[PlanDefinition]:
        return [
            PlanDefinition(
                key="basic",
                label_fa="{display_name} Basic",
                label_en="{display_name} Basic",
                price_usdc=Decimal("1.00"),
                duration_days=7,
                features={{"main": True}},
            )
        ]

    def trial(self) -> TrialDefinition:
        return TrialDefinition(enabled=False, duration_minutes=60, slot_limit=0, plan_key="trial")

    async def validate_credentials(self, raw: str) -> CredentialValidation:
        value = str(raw or "").strip()
        if not value:
            return CredentialValidation(valid=False, error="Credential is empty")
        return CredentialValidation(valid=True, external_id=value, display_name="{display_name} Account", normalized={{"credential": value}})

    def build_worker_config(self, *, account: dict[str, Any], subscription: dict[str, Any]) -> dict[str, Any]:
        return {{"account": account, "subscription": subscription, "features": {{"main": True}}}}

    async def run_account(self, credential: dict[str, Any], config: dict[str, Any], stop_event, emit: Callable[..., None]) -> None:
        raise NotImplementedError("Implement the game-specific account runner")
'''


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit('Usage: python scripts/new_game.py game_id "Display Name"')
    game_id = re.sub(r"[^a-z0-9_]+", "_", sys.argv[1].strip().lower()).strip("_")
    display_name = sys.argv[2].strip()
    class_name = "".join(part.capitalize() for part in game_id.split("_"))
    target = Path("games") / game_id
    target.mkdir(parents=True, exist_ok=False)
    for path in (
        target / "api",
        target / "services" / "paid",
        target / "services" / "free",
        target / "runtime" / "users",
        target / "runtime" / "shared",
    ):
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("", encoding="utf-8") if path.name not in {"users", "shared"} else None
    (target / "__init__.py").write_text(
        f"from games.{game_id}.plugin import {class_name}Plugin\n\n__all__ = ['{class_name}Plugin']\n",
        encoding="utf-8",
    )
    (target / "plugin.py").write_text(
        PLUGIN_TEMPLATE.format(game_id=game_id, display_name=display_name, class_name=class_name),
        encoding="utf-8",
    )
    (target / "features.json").write_text('{\n  "main": {"enabled": true, "visible": true}\n}\n', encoding="utf-8")
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "game_id": game_id,
                "display_name": display_name,
                "runtime": {"root": "runtime", "users": "users", "shared": "shared"},
                "shared_services": {},
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"Created modular game plugin: {target}")


if __name__ == "__main__":
    main()
