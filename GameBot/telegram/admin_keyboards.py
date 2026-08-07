from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.feature_flags import feature_flags
from core.registry import game_registry
from core.runtime_settings import runtime_settings


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🎮 Games", "admin:games"), _btn("💳 Payments and Wallets", "admin:payments")],
            [_btn("💎 Plans", "admin:plans"), _btn("🎁 Free Trials", "admin:trials")],
            [_btn("🧩 Features", "admin:features"), _btn("🛠 Workers", "admin:workers")],
            [_btn("🧾 Orders", "admin:orders"), _btn("👥 Users", "admin:users")],
            [_btn("🆘 Support", "admin:support"), _btn("🚧 Maintenance", "admin:maintenance")],
            [_btn("⚙️ System Settings", "admin:system"), _btn("💾 Create Backup", "admin:backup")],
            [_btn("🔄 Reload Settings", "admin:reload")],
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("⬅️ Admin Panel", "admin:home")]])


def games_admin_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plugin in game_registry.all():
        enabled = feature_flags.game_enabled(plugin.game_id)
        visible = feature_flags.game_visible(plugin.game_id)
        status = "🟢" if enabled else "🔴"
        eye = "👁" if visible else "🙈"
        rows.append([_btn(f"{status}{eye} {plugin.display_name_en}", f"admin:game:{plugin.game_id}")])
    rows.append([_btn("⬅️ Admin Panel", "admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def game_admin_keyboard(game_id: str) -> InlineKeyboardMarkup:
    enabled = feature_flags.game_enabled(game_id)
    visible = feature_flags.game_visible(game_id)
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("⛔ Disable Game" if enabled else "✅ Enable Game", f"admin:game_toggle:{game_id}:enabled")],
        [_btn("🙈 Hide from Users" if visible else "👁 Show to Users", f"admin:game_toggle:{game_id}:visible")],
        [_btn("♻️ Restart Game Workers", f"admin:game_restart:{game_id}")],
        [_btn("⏹ Stop Game Workers", f"admin:game_stop:{game_id}")],
        [_btn("💎 Plans", f"admin:plans_game:{game_id}"), _btn("🎁 Free Trial", f"admin:trial:{game_id}")],
        [_btn("🧩 Features", f"admin:features_game:{game_id}")],
    ]
    if game_id == "kintara":
        rows.insert(2, [_btn("🔥 Come To Molten", "admin:kintara:come_to_molten")])
    rows.append([_btn("⬅️ Games", "admin:games")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payments_admin_keyboard() -> InlineKeyboardMarkup:
    sol = runtime_settings.payment_network("solana_usdc")
    base = runtime_settings.payment_network("base_usdc")
    manual_approval = runtime_settings.require_admin_payment_approval("kintara", True)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(("🟢" if sol["enabled"] else "🔴") + " Solana USDC", "admin:network:sol")],
            [_btn(("🟢" if base["enabled"] else "🔴") + " Base USDC", "admin:network:base")],
            [
                _btn(
                    ("🟢 " if manual_approval else "🔴 ") + "Require Final Admin Approval for Kintara",
                    "admin:payment_approval_toggle:kintara",
                )
            ],
            [_btn("⬅️ Admin Panel", "admin:home")],
        ]
    )


def network_admin_keyboard(short: str, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⛔ Disable Network" if enabled else "✅ Enable Network", f"admin:network_toggle:{short}")],
            [_btn("🏦 Change Wallet Address", f"admin:network_set:{short}:wallet")],
            [_btn("🪙 Change Mint or Contract", f"admin:network_set:{short}:token")],
            [_btn("🌐 Change RPC URL", f"admin:network_set:{short}:rpc")],
            [_btn("🧹 Remove Database Override", f"admin:network_reset:{short}")],
            [_btn("⬅️ Payments", "admin:payments")],
        ]
    )


def plans_games_keyboard() -> InlineKeyboardMarkup:
    rows = [[_btn(plugin.display_name_en, f"admin:plans_game:{plugin.game_id}")] for plugin in game_registry.all()]
    rows.append([_btn("⬅️ Admin Panel", "admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_admin_keyboard(game_id: str) -> InlineKeyboardMarkup:
    plugin = game_registry.get(game_id)
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plugin.all_plans():
        enabled = runtime_settings.plan_enabled(game_id, plan.key, True)
        label = "Come To Molten" if game_id == "kintara" and plan.key == "molten_access" else (plan.label_en or plan.key)
        rows.append([_btn(("🟢 " if enabled else "🔴 ") + label, f"admin:plan:{game_id}:{plan.key}")])
    back_target = f"admin:game:{game_id}" if game_id == "kintara" else "admin:plans"
    back_label = "⬅️ Kintara" if game_id == "kintara" else "⬅️ Select Game"
    rows.append([_btn(back_label, back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plan_admin_keyboard(game_id: str, plan_key: str, enabled: bool) -> InlineKeyboardMarkup:
    mode = runtime_settings.plan_access_mode(
        game_id,
        plan_key,
        "free" if game_id == "kintara" and plan_key == "molten_access" else "paid",
    )
    mode_text = "Switch to Paid Access" if mode == "free" else "Switch to Free Access"
    back_target = "admin:kintara:come_to_molten" if game_id == "kintara" and plan_key == "molten_access" else f"admin:plans_game:{game_id}"
    back_label = "⬅️ Come To Molten" if game_id == "kintara" and plan_key == "molten_access" else "⬅️ Game Plans"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⛔ Disable Plan" if enabled else "✅ Enable Plan", f"admin:plan_toggle:{game_id}:{plan_key}")],
            [_btn(mode_text, f"admin:plan_mode:{game_id}:{plan_key}")],
            [_btn("💵 Change USDC Price", f"admin:plan_set:{game_id}:{plan_key}:price")],
            [_btn("📅 Change Duration in Days", f"admin:plan_set:{game_id}:{plan_key}:duration")],
            [_btn(back_label, back_target)],
        ]
    )


def trials_games_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plugin in game_registry.all():
        trial = plugin.trial()
        rows.append([_btn(("🟢 " if trial.enabled else "🔴 ") + plugin.display_name_en, f"admin:trial:{plugin.game_id}")])
    rows.append([_btn("⬅️ Admin Panel", "admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trial_admin_keyboard(game_id: str, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⛔ Disable Trial" if enabled else "✅ Enable Trial", f"admin:trial_toggle:{game_id}")],
            [_btn("⏱ Change Trial Duration", f"admin:trial_set:{game_id}:duration")],
            [_btn("🔢 Change Total Capacity", f"admin:trial_set:{game_id}:capacity")],
            [_btn("👥 Trial Claims", f"admin:trial_claims:{game_id}")],
            [_btn("⬅️ Game Trials", "admin:trials")],
        ]
    )


def features_games_keyboard() -> InlineKeyboardMarkup:
    rows = [[_btn(plugin.display_name_en, f"admin:features_game:{plugin.game_id}")] for plugin in game_registry.all()]
    rows.append([_btn("⬅️ Admin Panel", "admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def features_admin_keyboard(game_id: str, feature_names: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    plugin = game_registry.get(game_id)
    for name in feature_names:
        enabled = feature_flags.enabled(game_id, name, False)
        visible = feature_flags.visible(game_id, name, False)
        label = plugin.feature_label(name, "en")
        if name == "molten":
            label = "Come To Molten"
        rows.append(
            [
                _btn(
                    f"{('🟢' if enabled else '🔴')}{('👁' if visible else '🙈')} {label}",
                    f"admin:feature:{game_id}:{name}",
                )
            ]
        )
    back_target = f"admin:game:{game_id}" if game_id == "kintara" else "admin:features"
    back_label = "⬅️ Kintara" if game_id == "kintara" else "⬅️ Features"
    rows.append([_btn(back_label, back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def feature_admin_keyboard(game_id: str, name: str, enabled: bool, visible: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⛔ Disable" if enabled else "✅ Enable", f"admin:feature_toggle:{game_id}:{name}:enabled")],
            [_btn("🙈 Hide" if visible else "👁 Show", f"admin:feature_toggle:{game_id}:{name}:visible")],
            [_btn("🧹 Restore Default", f"admin:feature_reset:{game_id}:{name}")],
            [_btn("⬅️ Features", f"admin:features_game:{game_id}")],
        ]
    )


def support_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("👤 Change Support Handle", "admin:support_set:handle")],
            [_btn("🔗 Change Support URL", "admin:support_set:url")],
            [_btn("⬅️ Admin Panel", "admin:home")],
        ]
    )


def maintenance_admin_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Disable Maintenance" if enabled else "🚧 Enable Maintenance", "admin:maintenance_toggle")],
            [_btn("🇮🇷 Change Persian Message", "admin:maintenance_set:fa")],
            [_btn("🇬🇧 Change English Message", "admin:maintenance_set:en")],
            [_btn("⬅️ Admin Panel", "admin:home")],
        ]
    )


def workers_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("♻️ Restart Active Subscriptions", "admin:workers_restart_all")],
            [_btn("⏹ Stop All Workers", "admin:workers_stop_all")],
            [_btn("⬅️ Admin Panel", "admin:home")],
        ]
    )


def orders_admin_keyboard(orders) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders[:10]:
        rows.append(
            [
                _btn(f"✅ {order.order_code}", f"admin:order_approve:{order.order_code}"),
                _btn("❌ Reject", f"admin:order_reject:{order.order_code}"),
            ]
        )
    rows.append([_btn("⬅️ Admin Panel", "admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def system_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⏱ Payment Check Interval", "admin:system_set:payment_check")],
            [_btn("✅ Network Confirmations", "admin:system_set:confirmations")],
            [_btn("♻️ Worker Restart Limit", "admin:system_set:restart_limit")],
            [_btn("❤️ Heartbeat Timeout", "admin:system_set:heartbeat")],
            [_btn("⏳ Subscription Expiry Warning", "admin:system_set:expiry_warning")],
            [_btn("💾 Automatic Backup Interval", "admin:system_set:backup_interval")],
            [_btn("🗃 Backup Retention Count", "admin:system_set:backup_keep")],
            [_btn("⬅️ Admin Panel", "admin:home")],
        ]
    )


def feature_server_locked_keyboard(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔒 Controlled by Central Server", "admin:server_locked")],
            [_btn("⬅️ Features", f"admin:features_game:{game_id}")],
        ]
    )


def come_to_molten_admin_keyboard(
    *,
    running: bool,
    enabled: bool,
    visible: bool,
    auto_start: bool,
    plan_enabled: bool,
    access_mode: str,
) -> InlineKeyboardMarkup:
    mode_action = "Switch to Paid Access" if access_mode == "free" else "Switch to Free Access"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("⏹ Stop CMD" if running else "▶️ Start CMD", "admin:ember_stop" if running else "admin:ember_start"),
                _btn("♻️ Restart CMD", "admin:ember_restart"),
            ],
            [_btn("⛔ Disable Service" if enabled else "✅ Enable Service", "admin:ember_toggle:enabled")],
            [_btn("🙈 Hide from Users" if visible else "👁 Show to Users", "admin:ember_toggle:visible")],
            [_btn("⏸ Disable Auto-start" if auto_start else "▶️ Enable Auto-start", "admin:ember_toggle:auto_start")],
            [_btn("⛔ Disable Access Plan" if plan_enabled else "✅ Enable Access Plan", "admin:plan_toggle:kintara:molten_access")],
            [_btn(mode_action, "admin:plan_mode:kintara:molten_access")],
            [_btn("💵 Change USDC Price", "admin:plan_set:kintara:molten_access:price")],
            [_btn("📅 Change Access Duration", "admin:plan_set:kintara:molten_access:duration")],
            [_btn("🔐 Set Central Cookie", "admin:ember_set:credential"), _btn("📁 Use .env Cookie", "admin:ember_use_project_cookie")],
            [_btn("⏱ Change Monitor Interval", "admin:ember_set:interval")],
            [_btn("📢 Set Channel", "admin:ember_set:channel"), _btn("📤 Publish Now", "admin:ember_publish")],
            [_btn("👥 Users with Access", "admin:ember_users")],
            [_btn("⬅️ Kintara", "admin:game:kintara")],
        ]
    )


def ember_admin_keyboard(*, running: bool, enabled: bool, visible: bool, auto_start: bool) -> InlineKeyboardMarkup:
    """Backward-compatible wrapper for older imports and callbacks."""
    return come_to_molten_admin_keyboard(
        running=running,
        enabled=enabled,
        visible=visible,
        auto_start=auto_start,
        plan_enabled=runtime_settings.plan_enabled("kintara", "molten_access", True),
        access_mode=runtime_settings.plan_access_mode("kintara", "molten_access", "free"),
    )
