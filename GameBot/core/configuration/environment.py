from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    admin_user_ids: set[int] = Field(default_factory=set)
    database_url: str = "sqlite+aiosqlite:///./data/gamebot.db"
    master_key: str = ""
    log_level: str = "INFO"
    instances_dir: str = "data/instances"
    shared_services_dir: str = "data/shared_services"

    support_handle: str = "@Wbfarsi"
    support_url: str = "https://t.me/Wbfarsi"
    display_timezone: str = "Asia/Tehran"

    kintara_channel_id: int = 0
    kintara_channel_title: str = "Info Kintara"
    kintara_channel_post_interval_seconds: int = 20
    kintara_channel_invite_expire_seconds: int = 900
    kintara_channel_legacy_invite_link: str = ""

    backup_interval_seconds: int = 86400
    backup_keep_last: int = 14
    backup_include_env: bool = False
    expiry_check_seconds: int = 60
    expiry_warning_hours: int = 6

    worker_heartbeat_timeout: int = 90
    worker_restart_limit: int = 5

    payment_check_seconds: int = 30
    payment_min_confirmations: int = 1
    payment_amount_tolerance_usdc: float = 0.000001
    payment_unique_amount_enabled: bool = True
    payment_unique_amount_max_units: int = 999
    payment_max_preorder_age_seconds: int = 300
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_usdc_wallet: str = ""
    solana_usdc_mint: str = ""
    base_rpc_url: str = "https://mainnet.base.org"
    base_usdc_wallet: str = ""
    base_usdc_contract: str = ""
    usdc_decimals: int = 6

    feature_flags_url: str = ""
    feature_flags_token: str = ""
    feature_flags_refresh_seconds: int = 60

    kintara_base_url: str = "https://kintara.gg"
    # Shared defaults for Kintara-owned public services such as Ember.
    # Paid user accounts never use these values; their credentials are stored separately.
    kintara_cookie: str = ""
    kintara_ember_cookie: str = ""
    kintara_fishing_price_usdc: float = 1.00
    kintara_fishing_cook_price_usdc: float = 1.99
    kintara_fishing_cook_spinner_price_usdc: float = 2.99
    kintara_molten_price_usdc: float = 1.00
    kintara_plan_duration_days: int = 7
    kintara_molten_duration_days: int = 30
    kintara_trial_enabled: bool = True
    kintara_trial_duration_minutes: int = 120
    kintara_trial_slot_limit: int = 0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if value is None or value == "":
            return set()
        if isinstance(value, (set, list, tuple)):
            return {int(x) for x in value}
        return {int(x.strip()) for x in str(value).replace(";", ",").split(",") if x.strip()}

    def ensure_directories(self) -> None:
        for directory in (Path("data"), Path("logs")):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    value = Settings()
    value.ensure_directories()
    return value


settings = get_settings()
