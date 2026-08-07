from __future__ import annotations

import asyncio
import hashlib
import re
from decimal import Decimal
from typing import Any, Callable

from core.config import settings
from core.feature_flags import feature_flags
from core.locale_text import localized_literal
from core.runtime_settings import runtime_settings
from games.base import CredentialValidation, GamePlugin, PlanDefinition, TrialDefinition
from games.kintara.api.client import KintaraClient
from games.kintara.services.paid.runner import run_paid_account


class KintaraPlugin(GamePlugin):
    game_id = "kintara"
    display_name_fa = localized_literal("kintara.game.name")
    display_name_en = "Kintara"

    def all_plans(self) -> list[PlanDefinition]:
        default_days = max(1, int(settings.kintara_plan_duration_days))
        molten_days = max(1, int(settings.kintara_molten_duration_days))
        return [
            PlanDefinition(
                key="fishing",
                label_fa=localized_literal("kintara.plan.fishing"),
                label_en="Fishing",
                price_usdc=runtime_settings.plan_price(
                    self.game_id,
                    "fishing",
                    Decimal(str(settings.kintara_fishing_price_usdc)),
                ),
                duration_days=runtime_settings.plan_duration_days(self.game_id, "fishing", default_days),
                features={"farm": True, "cook": False, "spinner": False, "merchant": False},
            ),
            PlanDefinition(
                key="fishing_cook",
                label_fa=localized_literal("kintara.plan.fishing_cook"),
                label_en="Fishing and Cooking",
                price_usdc=runtime_settings.plan_price(
                    self.game_id,
                    "fishing_cook",
                    Decimal(str(settings.kintara_fishing_cook_price_usdc)),
                ),
                duration_days=runtime_settings.plan_duration_days(self.game_id, "fishing_cook", default_days),
                features={"farm": True, "cook": True, "spinner": False, "merchant": False},
            ),
            PlanDefinition(
                key="fishing_cook_spinner",
                label_fa=localized_literal("kintara.plan.fishing_cook_spinner"),
                label_en="Fishing, Cooking and Spinner",
                price_usdc=runtime_settings.plan_price(
                    self.game_id,
                    "fishing_cook_spinner",
                    Decimal(str(settings.kintara_fishing_cook_spinner_price_usdc)),
                ),
                duration_days=runtime_settings.plan_duration_days(
                    self.game_id,
                    "fishing_cook_spinner",
                    default_days,
                ),
                features={"farm": True, "cook": True, "spinner": True, "merchant": False},
            ),
            PlanDefinition(
                key="molten_access",
                label_fa=localized_literal("kintara.plan.molten"),
                label_en="Come To Molten",
                price_usdc=runtime_settings.plan_price(
                    self.game_id,
                    "molten_access",
                    Decimal(str(settings.kintara_molten_price_usdc)),
                ),
                duration_days=runtime_settings.plan_duration_days(
                    self.game_id,
                    "molten_access",
                    molten_days,
                ),
                features={"molten": True},
                runtime_kind="shared",
                shared_service_key="kintara_ember",
                requires_credential=False,
            ),
        ]

    def plans(self) -> list[PlanDefinition]:
        rows: list[PlanDefinition] = []
        for plan in self.all_plans():
            if not runtime_settings.plan_enabled(self.game_id, plan.key, True):
                continue
            if plan.features.get("spinner") and not feature_flags.enabled(
                self.game_id, "spinner", default=False
            ):
                continue
            rows.append(plan)
        return rows

    def trial(self) -> TrialDefinition:
        return TrialDefinition(
            enabled=runtime_settings.trial_enabled(self.game_id, settings.kintara_trial_enabled),
            duration_minutes=runtime_settings.trial_duration_minutes(
                self.game_id,
                max(1, settings.kintara_trial_duration_minutes),
            ),
            slot_limit=runtime_settings.trial_slot_limit(
                self.game_id,
                max(0, settings.kintara_trial_slot_limit),
            ),
            plan_key="trial",
        )

    def feature_label(self, feature_name: str, lang: str) -> str:
        labels = {
            "fa": {
                "farm": localized_literal("kintara.feature.farm"),
                "cook": localized_literal("kintara.feature.cook"),
                "spinner": localized_literal("kintara.feature.spinner"),
                "molten": localized_literal("kintara.feature.molten"),
                "merchant": localized_literal("kintara.feature.merchant"),
            },
            "en": {
                "farm": "Automatic fishing",
                "cook": "Automatic cooking",
                "spinner": "Automatic spinner",
                "molten": "Come To Molten",
                "merchant": "Merchant",
            },
        }
        return labels.get(lang, labels["fa"]).get(feature_name, feature_name)

    def visible_features(self, plan: PlanDefinition, lang: str) -> list[str]:
        rows: list[str] = []
        for name, allowed in plan.features.items():
            if not allowed:
                continue
            if name == "molten":
                rows.append(self.feature_label(name, lang))
                continue
            if not feature_flags.enabled(self.game_id, name, default=False):
                continue
            if not feature_flags.visible(self.game_id, name, default=False):
                continue
            rows.append(self.feature_label(name, lang))
        return rows

    @staticmethod
    def normalize_cookie(raw: str) -> str:
        value = str(raw or "").strip().strip('"').strip("'")
        if value.lower().startswith("cookie:"):
            value = value.split(":", 1)[1].strip()
        if not value:
            return ""
        if ";" in value or "=" in value:
            return value
        return f"__Host-kintara_session={value}"

    async def validate_credentials(self, raw: str) -> CredentialValidation:
        cookie = self.normalize_cookie(raw)
        if not cookie:
            return CredentialValidation(valid=False, error=localized_literal("kintara.cookie.empty"))
        client = KintaraClient(settings.kintara_base_url, cookie)
        try:
            status, data = await client.auth_me()
        except Exception:
            return CredentialValidation(valid=False, error=localized_literal("kintara.cookie.connection_failed"))
        if status != 200 or data.get("ok") is False:
            return CredentialValidation(valid=False, error=localized_literal("kintara.cookie.invalid"))
        external_id = self._find_identity(data) or hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        display_name = str(data.get("username") or data.get("name") or "Kintara Account")
        return CredentialValidation(
            valid=True,
            external_id=external_id,
            display_name=display_name,
            hint=self._cookie_hint(cookie),
            normalized={"cookie": cookie},
        )

    def build_worker_config(self, *, account: dict[str, Any], subscription: dict[str, Any]) -> dict[str, Any]:
        plan_key = str(subscription.get("plan_key") or "fishing")
        account_plans = [plan for plan in self.plans() if plan.runtime_kind == "account"]
        plan = next((row for row in account_plans if row.key == plan_key), account_plans[0])
        effective_features = {
            name: bool(allowed and feature_flags.enabled(self.game_id, name, default=False))
            for name, allowed in plan.features.items()
            if name != "merchant"
        }
        effective_features["merchant"] = False
        return {
            "account": account,
            "subscription": subscription,
            "features": effective_features,
            "base_url": settings.kintara_base_url,
            "heartbeat_seconds": 20,
        }

    async def run_account(
        self,
        credential: dict[str, Any],
        config: dict[str, Any],
        stop_event,
        emit: Callable[..., None],
    ) -> None:
        await run_paid_account(
            cookie=str(credential.get("cookie") or ""),
            base_url=str(config.get("base_url") or settings.kintara_base_url),
            config=config,
            stop_event=stop_event,
            emit=emit,
        )

    @staticmethod
    async def _sleep_with_stop(stop_event, seconds: int) -> None:
        for _ in range(seconds):
            if stop_event.is_set():
                return
            await asyncio.sleep(1)

    @staticmethod
    def _find_identity(data: Any) -> str:
        wanted = {"pid", "playerid", "userid", "accountid", "wallet", "walletaddress"}
        if isinstance(data, dict):
            for key, value in data.items():
                normalized = re.sub("[^a-z0-9]", "", str(key).lower())
                if normalized in wanted and isinstance(value, (str, int)) and str(value).strip():
                    return str(value).strip()
            for value in data.values():
                found = KintaraPlugin._find_identity(value)
                if found:
                    return found
        elif isinstance(data, list):
            for value in data[:50]:
                found = KintaraPlugin._find_identity(value)
                if found:
                    return found
        return ""

    @staticmethod
    def _cookie_hint(cookie: str) -> str:
        digest = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        return f"cookie:{digest[:8]}"
