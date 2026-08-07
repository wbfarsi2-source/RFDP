from __future__ import annotations
from core.locale_text import localized_literal
import json
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from core.config import settings
from core.database import SessionLocal
from core.models import PlatformSetting

class RuntimeSettings:
    """Database-backed runtime configuration with .env fallbacks.

    Values are cached in memory for synchronous access from plugins and keyboards.
    Admin changes are persisted immediately and survive restarts.
    """

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._secrets: set[str] = set()
        self.version = 0

    async def load(self) -> None:
        async with SessionLocal() as session:
            rows = list(await session.scalars(select(PlatformSetting)))
        self._values = {}
        self._secrets = set()
        for row in rows:
            try:
                self._values[row.key] = json.loads(row.value_json)
            except Exception:
                self._values[row.key] = row.value_json
            if row.is_secret:
                self._secrets.add(row.key)
        self.version += 1

        migration_key = "migrations.molten_20_second_updates"
        if not self.get_bool(migration_key, False):
            await self.set("services.kintara_ember.update_seconds", 20)
            await self.set("services.kintara_ember.channel_post_interval_seconds", 20)
            await self.set(migration_key, True)

    async def set(self, key: str, value: Any, *, updated_by: int | None=None, is_secret: bool=False) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        async with SessionLocal() as session:
            row = await session.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
            if row is None:
                row = PlatformSetting(key=key, value_json=payload, is_secret=is_secret, updated_by=updated_by)
                session.add(row)
            else:
                row.value_json = payload
                row.is_secret = is_secret
                row.updated_by = updated_by
            await session.commit()
        self._values[key] = value
        if is_secret:
            self._secrets.add(key)
        else:
            self._secrets.discard(key)
        self.version += 1

    async def delete(self, key: str) -> None:
        async with SessionLocal() as session:
            row = await session.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
            if row is not None:
                await session.delete(row)
                await session.commit()
        self._values.pop(key, None)
        self._secrets.discard(key)
        self.version += 1

    def get(self, key: str, default: Any=None) -> Any:
        return self._values.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._values

    def keys(self) -> list[str]:
        return list(self._values.keys())

    def get_bool(self, key: str, default: bool=False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'enabled'}

    def get_int(self, key: str, default: int=0) -> int:
        try:
            return int(self.get(key, default))
        except Exception:
            return int(default)

    def get_decimal(self, key: str, default: Decimal | str | float=Decimal('0')) -> Decimal:
        try:
            return Decimal(str(self.get(key, default)))
        except Exception:
            return Decimal(str(default))

    def masked(self, key: str, default: str='') -> str:
        value = str(self.get(key, default) or '')
        if not value:
            return '-'
        if len(value) <= 12:
            return value
        return f'{value[:6]}…{value[-6:]}'

    def support_handle(self) -> str:
        return str(self.get('platform.support_handle', settings.support_handle) or settings.support_handle)

    def support_url(self) -> str:
        return str(self.get('platform.support_url', settings.support_url) or settings.support_url)

    def maintenance_enabled(self) -> bool:
        return self.get_bool('platform.maintenance.enabled', False)

    def maintenance_message(self, lang: str='fa') -> str:
        fallback = localized_literal('core.runtime_settings.598c958fa966') if lang == 'fa' else 'The service is temporarily under maintenance.'
        return str(self.get(f'platform.maintenance.message.{lang}', fallback) or fallback)

    def game_enabled(self, game_id: str, default: bool=True) -> bool:
        return self.get_bool(f'games.{game_id}.enabled', default)

    def game_visible(self, game_id: str, default: bool=True) -> bool:
        return self.get_bool(f'games.{game_id}.visible', default)

    def plan_enabled(self, game_id: str, plan_key: str, default: bool=True) -> bool:
        return self.get_bool(f'games.{game_id}.plans.{plan_key}.enabled', default)

    def plan_price(self, game_id: str, plan_key: str, default: Decimal) -> Decimal:
        return self.get_decimal(f'games.{game_id}.plans.{plan_key}.price_usdc', default)

    def plan_duration_days(self, game_id: str, plan_key: str, default: int) -> int:
        return max(1, self.get_int(f'games.{game_id}.plans.{plan_key}.duration_days', default))

    def plan_access_mode(self, game_id: str, plan_key: str, default: str = 'paid') -> str:
        value = str(self.get(f'games.{game_id}.plans.{plan_key}.access_mode', default) or default).strip().lower()
        return 'free' if value == 'free' else 'paid'

    def trial_enabled(self, game_id: str, default: bool) -> bool:
        return self.get_bool(f'games.{game_id}.trial.enabled', default)

    def trial_duration_minutes(self, game_id: str, default: int) -> int:
        return max(1, self.get_int(f'games.{game_id}.trial.duration_minutes', default))

    def trial_slot_limit(self, game_id: str, default: int) -> int:
        return max(0, self.get_int(f'games.{game_id}.trial.slot_limit', default))

    def require_admin_payment_approval(self, game_id: str, default: bool=False) -> bool:
        return self.get_bool(f'games.{game_id}.payments.require_admin_approval', default)

    def ember_enabled(self) -> bool:
        return self.get_bool('services.kintara_ember.enabled', True)

    def ember_visible(self) -> bool:
        return self.get_bool('services.kintara_ember.visible', True)

    def ember_auto_start(self) -> bool:
        return self.get_bool('services.kintara_ember.auto_start', True)

    def ember_update_seconds(self) -> int:
        return max(20, self.get_int('services.kintara_ember.update_seconds', 20))

    def ember_credential_ciphertext(self) -> str:
        return str(self.get('services.kintara_ember.credential_ciphertext', '') or '')

    def payment_network(self, network: str) -> dict[str, Any]:
        if network == 'solana_usdc':
            wallet = str(self.get('payments.solana.wallet', settings.solana_usdc_wallet) or '')
            token = str(self.get('payments.solana.mint', settings.solana_usdc_mint) or '')
            rpc = str(self.get('payments.solana.rpc_url', settings.solana_rpc_url) or settings.solana_rpc_url)
            enabled_default = bool(wallet and token)
            enabled = self.get_bool('payments.solana.enabled', enabled_default)
            return {'network': network, 'enabled': enabled, 'wallet': wallet, 'token': token, 'rpc_url': rpc}
        if network == 'base_usdc':
            wallet = str(self.get('payments.base.wallet', settings.base_usdc_wallet) or '')
            token = str(self.get('payments.base.contract', settings.base_usdc_contract) or '')
            rpc = str(self.get('payments.base.rpc_url', settings.base_rpc_url) or settings.base_rpc_url)
            enabled_default = bool(wallet and token)
            enabled = self.get_bool('payments.base.enabled', enabled_default)
            return {'network': network, 'enabled': enabled, 'wallet': wallet, 'token': token, 'rpc_url': rpc}
        raise KeyError(network)

    def configured_payment_networks(self) -> list[str]:
        rows: list[str] = []
        sol = self.payment_network('solana_usdc')
        base = self.payment_network('base_usdc')
        if sol['enabled'] and sol['wallet'] and sol['token']:
            rows.append('sol')
        if base['enabled'] and base['wallet'] and base['token']:
            rows.append('base')
        return rows

    def payment_check_seconds(self) -> int:
        return max(15, self.get_int('system.payment_check_seconds', settings.payment_check_seconds))

    def payment_min_confirmations(self) -> int:
        return max(1, self.get_int('system.payment_min_confirmations', settings.payment_min_confirmations))

    def payment_tolerance_usdc(self) -> Decimal:
        return self.get_decimal('system.payment_tolerance_usdc', settings.payment_amount_tolerance_usdc)

    def payment_max_preorder_age_seconds(self) -> int:
        return max(0, self.get_int('system.payment_max_preorder_age_seconds', settings.payment_max_preorder_age_seconds))

    def worker_restart_limit(self) -> int:
        return max(0, self.get_int('system.worker_restart_limit', settings.worker_restart_limit))

    def worker_heartbeat_timeout(self) -> int:
        return max(30, self.get_int('system.worker_heartbeat_timeout', settings.worker_heartbeat_timeout))

    def expiry_warning_hours(self) -> int:
        return max(1, self.get_int('system.expiry_warning_hours', settings.expiry_warning_hours))

    def expiry_check_seconds(self) -> int:
        return max(30, self.get_int('system.expiry_check_seconds', settings.expiry_check_seconds))

    def backup_interval_seconds(self) -> int:
        return max(3600, self.get_int('system.backup_interval_seconds', settings.backup_interval_seconds))

    def backup_keep_last(self) -> int:
        return max(1, self.get_int('system.backup_keep_last', settings.backup_keep_last))
runtime_settings = RuntimeSettings()
