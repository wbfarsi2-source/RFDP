from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings
from core.database import init_database
from core.feature_flags import feature_flags
from core.game_layout import game_layout
from core.plugin_loader import discover_game_plugins
from core.runtime.shared_services.store import shared_service_store
from core.runtime_settings import runtime_settings
from games.kintara.shared_credentials import configured_source, has_shared_cookie


def status(value: bool) -> str:
    return "OK" if value else "MISSING"


def plan_line(plugin, plan) -> str:
    default_mode = "free" if plan.key == "molten_access" else "paid"
    mode = runtime_settings.plan_access_mode(plugin.game_id, plan.key, default_mode)
    enabled = runtime_settings.plan_enabled(plugin.game_id, plan.key, True)
    return (
        f"  - {plan.key}: enabled={enabled} mode={mode} "
        f"price={plan.price_usdc} USDC duration={plan.duration_days} days"
    )


async def main() -> None:
    await init_database()
    await runtime_settings.load()
    feature_flags.load_local()
    feature_flags.touch_runtime_overrides()
    plugins = discover_game_plugins()
    kintara = next((plugin for plugin in plugins if plugin.game_id == "kintara"), None)

    print("GameBot v0.7.0 setup validation")
    print("- Telegram token:", status(bool(settings.telegram_bot_token)))
    print("- Admin IDs:", status(bool(settings.admin_user_ids)))
    print("- Master key:", status(bool(settings.master_key)))
    print("- Support URL:", status(bool(runtime_settings.support_url())))
    print("- Solana USDC:", status("sol" in runtime_settings.configured_payment_networks()))
    print("- Base USDC:", status("base" in runtime_settings.configured_payment_networks()))
    print("- Plugins:", ", ".join(plugin.game_id for plugin in plugins) or "NONE")
    print("- Kintara game:", "ENABLED" if feature_flags.game_enabled("kintara") else "DISABLED")
    print("- Kintara account runtime:", game_layout("kintara").users_root)
    print("- Kintara shared runtime:", game_layout("kintara").shared_root)
    print(
        "- Kintara Merchant:",
        "DISABLED/HIDDEN"
        if not feature_flags.enabled("kintara", "merchant")
        and not feature_flags.visible("kintara", "merchant")
        else "REMOTE/ENABLED",
    )
    print("- Kintara final payment approval: REQUIRED")

    if kintara is not None:
        print("- Kintara plans:")
        for plan in kintara.all_plans():
            print(plan_line(kintara, plan))
        trial = kintara.trial()
        print(
            "- Kintara trial:",
            f"enabled={trial.enabled} duration={trial.duration_minutes} minutes capacity={trial.slot_limit}",
        )

    print("- Molten service:", "ENABLED" if runtime_settings.ember_enabled() else "DISABLED")
    print("- Molten menu visibility:", "VISIBLE" if runtime_settings.ember_visible() else "HIDDEN")
    print("- Molten workspace:", shared_service_store.workspace("kintara_ember"))
    print("- Molten shared cookie:", status(has_shared_cookie()), f"source={configured_source()}")
    print("- Molten monitor interval:", f"{runtime_settings.ember_update_seconds()} seconds")
    print("- Kintara channel ID:", settings.kintara_channel_id or "MISSING")
    print("- Kintara channel post interval:", f"{settings.kintara_channel_post_interval_seconds} seconds")
    print("- Maintenance:", "ENABLED" if runtime_settings.maintenance_enabled() else "DISABLED")

    required_ok = bool(settings.telegram_bot_token and settings.admin_user_ids and settings.master_key)
    if not required_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
