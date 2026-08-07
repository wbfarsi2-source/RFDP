from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_kintara_orders_require_final_admin_approval() -> None:
    source = (ROOT / "core" / "services" / "payments" / "service.py").read_text(encoding="utf-8")
    assert "require_admin = True if order.game_id == 'kintara'" in source
    assert "OrderStatus.AWAITING_ADMIN.value" in source
    assert "admin:order_approve:" in source
    assert "admin:order_reject:" in source


def test_cookie_is_requested_only_after_admin_approval() -> None:
    purchase_source = (ROOT / "games" / "kintara" / "purchases" / "service.py").read_text(encoding="utf-8")
    router_source = (ROOT / "games" / "kintara" / "telegram" / "router.py").read_text(encoding="utf-8")
    assert "OrderStatus.AWAITING_CREDENTIAL.value" in purchase_source
    assert "complete_credential_activation" in router_source
    assert "await message.delete()" in router_source


def test_molten_is_inside_kintara_router() -> None:
    router_source = (ROOT / "games" / "kintara" / "telegram" / "router.py").read_text(encoding="utf-8")
    keyboard_source = (ROOT / "telegram" / "keyboards.py").read_text(encoding="utf-8")
    assert 'F.data == "kintara:molten"' in router_source
    assert 'callback_data="kintara:molten"' in keyboard_source
    main_menu_block = keyboard_source.split('def main_menu', 1)[1].split('def settings_menu', 1)[0]
    assert 'molten' not in main_menu_block.lower()
