from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.config import settings
from core.crypto import CredentialVault
from core.game_layout import PROJECT_ROOT
from core.runtime_settings import runtime_settings


@dataclass(frozen=True)
class SharedCredential:
    cookie: str
    source: str


def _read_env_value(key: str) -> str:
    environment_value = str(os.environ.get(key) or "").strip()
    if environment_value:
        return environment_value
    env_path = Path(PROJECT_ROOT) / ".env"
    if not env_path.exists():
        return ""
    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip().upper() != key.upper():
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value.strip()
    except Exception:
        return ""
    return ""


def project_cookie() -> str:
    dedicated = _read_env_value("KINTARA_EMBER_COOKIE") or str(settings.kintara_ember_cookie or "").strip()
    if dedicated:
        return dedicated
    return _read_env_value("KINTARA_COOKIE") or str(settings.kintara_cookie or "").strip()


def admin_cookie_available() -> bool:
    return bool(runtime_settings.ember_credential_ciphertext())


def configured_source() -> str:
    value = str(runtime_settings.get("services.kintara_ember.cookie_source", "project") or "project")
    return value if value in {"project", "admin_override"} else "project"


def has_shared_cookie() -> bool:
    if configured_source() == "admin_override" and admin_cookie_available():
        return True
    return bool(project_cookie() or admin_cookie_available())


def resolve_shared_cookie() -> SharedCredential:
    source_mode = configured_source()
    encrypted = runtime_settings.ember_credential_ciphertext()

    if source_mode == "admin_override" and encrypted:
        credential = CredentialVault().decrypt(encrypted)
        cookie = str(credential.get("cookie") or "").strip()
        if cookie:
            return SharedCredential(cookie=cookie, source="admin_override")

    dedicated = _read_env_value("KINTARA_EMBER_COOKIE") or str(settings.kintara_ember_cookie or "").strip()
    if dedicated:
        return SharedCredential(cookie=dedicated, source="KINTARA_EMBER_COOKIE")

    default_cookie = _read_env_value("KINTARA_COOKIE") or str(settings.kintara_cookie or "").strip()
    if default_cookie:
        return SharedCredential(cookie=default_cookie, source="KINTARA_COOKIE")

    if encrypted:
        credential = CredentialVault().decrypt(encrypted)
        cookie = str(credential.get("cookie") or "").strip()
        if cookie:
            return SharedCredential(cookie=cookie, source="admin_fallback")

    raise RuntimeError(
        "No shared Kintara cookie is configured. Set KINTARA_COOKIE in the project .env file "
        "or configure an admin override from the Ember admin panel."
    )
