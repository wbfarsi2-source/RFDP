from __future__ import annotations

import logging

from core.config import settings
from core.runtime_settings import runtime_settings
from games.kintara.plugin import KintaraPlugin
from games.kintara.shared_credentials import configured_source, has_shared_cookie

logger = logging.getLogger(__name__)


def log_startup_checks() -> None:
    if not settings.master_key:
        logger.warning("MASTER_KEY is empty; encrypted account activation will fail")

    solana_ready = "sol" in runtime_settings.configured_payment_networks()
    base_ready = "base" in runtime_settings.configured_payment_networks()
    if not solana_ready and not base_ready:
        logger.warning("No complete USDC payment network is configured")
    else:
        logger.info("Payment networks ready: solana=%s base=%s", solana_ready, base_ready)

    plugin = KintaraPlugin()
    for plan in plugin.all_plans():
        default_mode = "free" if plan.key == "molten_access" else "paid"
        logger.info(
            "Kintara plan key=%s enabled=%s mode=%s price=%s duration_days=%s",
            plan.key,
            runtime_settings.plan_enabled("kintara", plan.key, True),
            runtime_settings.plan_access_mode("kintara", plan.key, default_mode),
            plan.price_usdc,
            plan.duration_days,
        )

    logger.info(
        "Kintara trial enabled=%s duration_minutes=%s slot_limit=%s",
        runtime_settings.trial_enabled("kintara", settings.kintara_trial_enabled),
        runtime_settings.trial_duration_minutes("kintara", settings.kintara_trial_duration_minutes),
        runtime_settings.trial_slot_limit("kintara", settings.kintara_trial_slot_limit),
    )
    logger.info("Kintara final payment approval is required")
    logger.info(
        "Molten shared cookie configured=%s source=%s update_seconds=%s channel_id=%s",
        has_shared_cookie(),
        configured_source(),
        runtime_settings.ember_update_seconds(),
        settings.kintara_channel_id or 0,
    )
