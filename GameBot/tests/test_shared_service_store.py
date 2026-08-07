from pathlib import Path

from core.shared_service_store import SharedServiceStore


def test_ember_workspace_uses_stable_folder_name(tmp_path: Path) -> None:
    store = SharedServiceStore(tmp_path)
    workspace = store.workspace("kintara_ember")

    assert workspace.name == "Ember"
    state = store.ensure_state(
        "kintara_ember",
        service_name="Kintara Ember Shared Monitor",
        status="waiting_for_cookie",
    )
    assert state["status"] == "waiting_for_cookie"
    assert (workspace / "service.json").exists()
