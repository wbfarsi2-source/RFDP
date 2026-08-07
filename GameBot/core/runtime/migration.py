from __future__ import annotations

import logging
from pathlib import Path

from core.config import settings
from core.game_layout import PROJECT_ROOT, game_layout, migrate_directory
from core.runtime.shared_services.store import shared_service_store

logger = logging.getLogger(__name__)


def migrate_legacy_runtime_layout() -> None:
    legacy_instances = PROJECT_ROOT / settings.instances_dir
    if legacy_instances.exists():
        for game_dir in legacy_instances.iterdir():
            if not game_dir.is_dir():
                continue
            for account_dir in game_dir.glob("account_*"):
                destination = game_layout(game_dir.name).users_root / account_dir.name
                try:
                    if migrate_directory(account_dir, destination):
                        logger.info("migrated account workspace %s -> %s", account_dir, destination)
                except Exception:
                    logger.exception("could not migrate account workspace %s", account_dir)

    for legacy_name in ("Ember", "kintara_ember"):
        source = PROJECT_ROOT / settings.shared_services_dir / legacy_name
        destination = shared_service_store.workspace("kintara_ember")
        try:
            if migrate_directory(source, destination):
                logger.info("migrated Ember workspace %s -> %s", source, destination)
        except Exception:
            logger.exception("could not migrate Ember workspace %s", source)
