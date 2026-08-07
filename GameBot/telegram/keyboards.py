from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from core.locale_text import localized_literal
from core.runtime_settings import runtime_settings


BUTTONS = {
    "fa": {
        "games": localized_literal("ui.main.games"),
        "accounts": localized_literal("ui.main.account"),
        "plans": localized_literal("ui.main.plans"),
        "subscription": localized_literal("ui.main.subscription"),
        "guide": localized_literal("ui.main.guide"),
        "support": localized_literal("ui.main.support"),
        "settings": localized_literal("ui.main.settings"),
        "change_language": localized_literal("ui.settings.language"),
        "notifications": localized_literal("ui.settings.notifications"),
        "back": localized_literal("ui.common.back"),
        "menu": localized_literal("ui.common.main_menu"),
    },
    "en": {
        "games": "🎮 Games",
        "accounts": "👤 My Account",
        "plans": "💎 Services",
        "subscription": "📊 My Subscription",
        "guide": "ℹ️ Service Guide",
        "support": "🆘 Support",
        "settings": "⚙️ Settings",
        "change_language": "🌐 Change Language",
        "notifications": "🔔 Notifications",
        "back": "⬅️ Back",
        "menu": "🏠 Main Menu",
    },
}


def b(lang: str, key: str) -> str:
    return BUTTONS.get(lang, BUTTONS["fa"])[key]


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=localized_literal("ui.language.persian"), callback_data="lang:fa"),
                InlineKeyboardButton(text="English", callback_data="lang:en"),
            ]
        ]
    )


def main_menu(lang: str = "fa") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=b(lang, "games")), KeyboardButton(text=b(lang, "accounts"))],
            [KeyboardButton(text=b(lang, "guide")), KeyboardButton(text=b(lang, "support"))],
            [KeyboardButton(text=b(lang, "settings"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=(localized_literal("ui.main.placeholder") if lang == "fa" else "Choose an option"),
    )


def settings_menu(lang: str = "fa") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=b(lang, "change_language")), KeyboardButton(text=b(lang, "notifications"))],
            [KeyboardButton(text=b(lang, "menu"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def support_menu(lang: str = "fa") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b(lang, "menu"))]],
        resize_keyboard=True,
        is_persistent=True,
    )


def games_keyboard(games, lang: str = "fa") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=game.display_name_en if lang == "en" else game.display_name_fa,
                callback_data=f"game:{game.game_id}",
            )
        ]
        for game in games
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def game_actions(game_id: str, *, lang: str = "fa", trial_enabled: bool = False) -> InlineKeyboardMarkup:
    if game_id == "kintara":
        rows = [
            [
                InlineKeyboardButton(
                    text=("💎 Kintara services" if lang == "en" else localized_literal("kintara.ui.services")),
                    callback_data="kintara:plans",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔥 Come To Molten",
                    callback_data="kintara:molten",
                )
            ],
        ]
        if trial_enabled:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=("🎁 Free trial" if lang == "en" else localized_literal("kintara.ui.trial")),
                        callback_data="kintara:trial",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows = [
        [
            InlineKeyboardButton(
                text="➕ Add Account" if lang == "en" else localized_literal("ui.account.add"),
                callback_data=f"account:add:{game_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="💳 View Plans" if lang == "en" else localized_literal("ui.plan.view"),
                callback_data=f"plans:{game_id}",
            )
        ],
    ]
    if trial_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎁 Free Trial" if lang == "en" else localized_literal("ui.trial.free"),
                    callback_data=f"trial:{game_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_keyboard(game_id: str, plans, lang: str, trial_enabled: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for plan in plans:
        label = plan.label_en if lang == "en" else plan.label_fa
        mode = runtime_settings.plan_access_mode(game_id, plan.key, "paid")
        price = "Free" if mode == "free" and lang == "en" else localized_literal("ui.plan.free") if mode == "free" else f"{plan.price_usdc} USDC"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{label} — {price}",
                    callback_data=f"buy:{game_id}:{plan.key}",
                )
            ]
        )
    if trial_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎁 Free Trial" if lang == "en" else localized_literal("ui.trial.free"),
                    callback_data=f"trial:{game_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kintara_plans_keyboard(plans, lang: str) -> InlineKeyboardMarkup:
    rows = []
    for plan in plans:
        if plan.key == "molten_access":
            continue
        mode = runtime_settings.plan_access_mode("kintara", plan.key, "paid")
        label = plan.label_en if lang == "en" else plan.label_fa
        button_text = label if mode == "free" else f"{label} — {plan.price_usdc} USDC"
        rows.append([InlineKeyboardButton(text=button_text, callback_data=f"kintara:plan:{plan.key}")])
    rows.append([InlineKeyboardButton(text=b(lang, "back"), callback_data="game:kintara")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kintara_network_keyboard(plan_key: str, lang: str) -> InlineKeyboardMarkup:
    rows = []
    if "sol" in configured_payment_networks():
        rows.append([InlineKeyboardButton(text="◎ USDC Solana", callback_data=f"kintara:network:{plan_key}:sol")])
    if "base" in configured_payment_networks():
        rows.append([InlineKeyboardButton(text="🔵 USDC Base", callback_data=f"kintara:network:{plan_key}:base")])
    rows.append([InlineKeyboardButton(text=b(lang, "back"), callback_data="kintara:plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credential_prompt_keyboard(order_code: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("🔐 Continue account connection" if lang == "en" else localized_literal("kintara.purchase.continue_connection")),
                    callback_data=f"kintara:credential:{order_code}",
                )
            ]
        ]
    )


def credential_wait_keyboard(order_code: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("Do this later" if lang == "en" else localized_literal("kintara.purchase.do_later")),
                    callback_data=f"kintara:credential_later:{order_code}",
                )
            ]
        ]
    )


def pending_connection_keyboard(order_code: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("🔐 Continue game connection" if lang == "en" else localized_literal("kintara.purchase.continue_connection")),
                    callback_data=f"kintara:credential:{order_code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("🎮 Back to Kintara" if lang == "en" else localized_literal("kintara.purchase.back_to_kintara")),
                    callback_data="game:kintara",
                )
            ],
        ]
    )


def molten_keyboard(lang: str, *, channel_available: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🔄 Refresh" if lang == "en" else localized_literal("kintara.molten.refresh_button"),
                callback_data="kintara:molten_refresh",
            )
        ]
    ]
    if channel_available:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📢 Channel access" if lang == "en" else localized_literal("kintara.molten.channel_button"),
                    callback_data="kintara:molten_channel",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=b(lang, "back"), callback_data="game:kintara")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def molten_purchase_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Buy access" if lang == "en" else localized_literal("kintara.molten.buy_button"),
                    callback_data="kintara:plan:molten_access",
                )
            ],
            [InlineKeyboardButton(text=b(lang, "back"), callback_data="game:kintara")],
        ]
    )


def channel_invite_keyboard(link: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Join private channel" if lang == "en" else localized_literal("kintara.molten.join_channel"),
                    url=link,
                )
            ]
        ]
    )


def account_select_keyboard(accounts, prefix: str, suffix: str = "") -> InlineKeyboardMarkup:
    rows = []
    for account in accounts:
        data = f"{prefix}:{account.id}" + (f":{suffix}" if suffix else "")
        rows.append([InlineKeyboardButton(text=account.label[:45], callback_data=data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def configured_payment_networks() -> list[str]:
    return runtime_settings.configured_payment_networks()


def network_keyboard(account_id: int, plan_key: str, lang: str) -> InlineKeyboardMarkup:
    rows = []
    if "sol" in configured_payment_networks():
        rows.append([InlineKeyboardButton(text="◎ USDC Solana", callback_data=f"paynet:{account_id}:{plan_key}:sol")])
    if "base" in configured_payment_networks():
        rows.append([InlineKeyboardButton(text="🔵 USDC Base", callback_data=f"paynet:{account_id}:{plan_key}:base")])
    rows.append([InlineKeyboardButton(text=b(lang, "back"), callback_data="payments:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_actions(account_id: int, running: bool, lang: str = "fa", *, game_id: str = "kintara") -> InlineKeyboardMarkup:
    action = (
        InlineKeyboardButton(
            text="⏹ Stop Service" if lang == "en" else localized_literal("ui.account.stop"),
            callback_data=f"account:stop:{account_id}",
        )
        if running
        else InlineKeyboardButton(
            text="▶️ Start Service" if lang == "en" else localized_literal("ui.account.start"),
            callback_data=f"account:start:{account_id}",
        )
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [action],
            [
                InlineKeyboardButton(
                    text="🔄 Renew or Change Service" if lang == "en" else localized_literal("ui.account.renew"),
                    callback_data=f"game:{game_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Delete Account" if lang == "en" else localized_literal("ui.account.delete"),
                    callback_data=f"account:delete:{account_id}",
                )
            ],
        ]
    )


def support_link(url: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Open Support" if lang == "en" else localized_literal("ui.support.open"),
                    url=url,
                )
            ]
        ]
    )
