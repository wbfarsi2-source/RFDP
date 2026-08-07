from decimal import Decimal

from core.feature_flags import feature_flags
from core.plugin_loader import discover_game_plugins
from core.registry import GameRegistry
from games.kintara.plugin import KintaraPlugin


def test_register_and_get_plugin() -> None:
    registry = GameRegistry()
    registry.register(KintaraPlugin())
    assert registry.get("kintara").game_id == "kintara"


def test_plugins_are_discovered_without_core_mapping() -> None:
    plugins = discover_game_plugins()
    assert [plugin.game_id for plugin in plugins] == ["kintara"]


def test_kintara_plan_catalog() -> None:
    plugin = KintaraPlugin()
    plans = {plan.key: plan for plan in plugin.all_plans()}
    assert set(plans) == {
        "fishing",
        "fishing_cook",
        "fishing_cook_spinner",
        "molten_access",
    }
    assert plans["fishing"].price_usdc == Decimal("1.0")
    assert plans["fishing_cook"].price_usdc == Decimal("1.99")
    assert plans["fishing_cook_spinner"].price_usdc == Decimal("2.99")
    assert plans["molten_access"].runtime_kind == "shared"
    assert plans["molten_access"].requires_credential is False


def test_kintara_merchant_is_hidden_and_disabled() -> None:
    feature_flags.load_local()
    plugin = KintaraPlugin()
    plan = next(plan for plan in plugin.all_plans() if plan.key == "fishing_cook_spinner")
    visible = plugin.visible_features(plan, "en")
    assert "Merchant" not in visible
    assert feature_flags.enabled("kintara", "merchant") is False
    assert feature_flags.visible("kintara", "merchant") is False
