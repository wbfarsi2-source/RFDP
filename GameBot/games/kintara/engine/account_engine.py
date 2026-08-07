from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from games.kintara.engine import legacy_engine


def _load_features(raw: str) -> dict[str, bool]:
    try:
        value = json.loads(raw or "{}")
    except Exception:
        value = {}
    return {str(key): bool(enabled) for key, enabled in value.items()} if isinstance(value, dict) else {}


def _location_state(workspace: Path):
    settings_path = workspace / "location_settings.json"
    legacy_engine.LOCATION_SETTINGS_FILE = settings_path
    saved = legacy_engine._read_location_settings()
    location_key = str(saved.get("fish_location_key") or "")
    location = next(
        (row for row in legacy_engine.FISH_LOCATIONS if str(row.get("key") or "") == location_key),
        legacy_engine.FISH_LOCATIONS[0],
    )
    try:
        switch_every = max(1, int(saved.get("fish_switch_every", legacy_engine.FISH_HOOK_SWITCH_EVERY)))
    except Exception:
        switch_every = legacy_engine.FISH_HOOK_SWITCH_EVERY
    return legacy_engine.build_location_state("managed", [location], switch_every=switch_every)



def _configure_network_route() -> None:
    proxy_url = str(
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    if proxy_url and proxy_url.lower().startswith(("http://", "https://")):
        legacy_engine.direct_urlopen = lambda request, timeout: legacy_engine.proxy_urlopen(
            request, timeout, proxy_url
        )
    if proxy_url:
        legacy_engine.open_ws = lambda url, timeout=10: legacy_engine.create_ws_connection(
            url,
            timeout=max(float(timeout or 0), 20.0),
            proxy_url=proxy_url,
            force_direct=False,
        )


def run(workspace: Path, features: dict[str, bool]) -> int:
    workspace.mkdir(parents=True, exist_ok=True)
    legacy_engine.ENV_FILE = workspace / "engine.env"
    legacy_engine.ERROR_LOG = workspace / "engine_errors.log"
    legacy_engine.LOCATION_SETTINGS_FILE = workspace / "location_settings.json"
    legacy_engine.clear_screen = lambda: None
    legacy_engine.pause = lambda *_args, **_kwargs: None
    legacy_engine.choose_farm_target = lambda: None
    legacy_engine.CONNECTION_MODE = "system"
    _configure_network_route()

    cookie = str(os.environ.get("KINTARA_COOKIE") or "").strip()
    if not cookie:
        raise RuntimeError("KINTARA_COOKIE is missing for the account engine")
    os.environ["KINTARA_COOKIE"] = cookie

    if not features.get("farm"):
        raise RuntimeError("Fishing is not enabled for this account")
    mode = "farm_cook" if features.get("cook") else "farm_only"
    legacy_engine.farm_loop("free", _location_state(workspace), forced_mode=mode)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--features", default="{}")
    args = parser.parse_args()
    return run(Path(args.workspace).resolve(), _load_features(args.features))


if __name__ == "__main__":
    raise SystemExit(main())
