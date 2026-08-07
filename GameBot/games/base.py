from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    key: str
    label_fa: str
    label_en: str
    price_usdc: Decimal
    duration_days: int
    features: dict[str, Any]
    runtime_kind: str = "account"
    shared_service_key: str | None = None
    requires_credential: bool = True


@dataclass(frozen=True, slots=True)
class TrialDefinition:
    enabled: bool
    duration_minutes: int
    slot_limit: int = 0
    plan_key: str = "trial"


@dataclass(frozen=True, slots=True)
class CredentialValidation:
    valid: bool
    external_id: str = ""
    display_name: str = ""
    hint: str = ""
    normalized: dict[str, Any] | None = None
    error: str = ""


class GamePlugin(ABC):
    game_id: str
    display_name_fa: str
    display_name_en: str

    @abstractmethod
    def plans(self) -> list[PlanDefinition]:
        raise NotImplementedError

    def all_plans(self) -> list[PlanDefinition]:
        return self.plans()

    def trial(self) -> TrialDefinition:
        return TrialDefinition(enabled=False, duration_minutes=0)

    def feature_label(self, feature_name: str, lang: str) -> str:
        return feature_name

    def visible_features(self, plan: PlanDefinition, lang: str) -> list[str]:
        return [self.feature_label(name, lang) for name, enabled in plan.features.items() if enabled]

    @abstractmethod
    async def validate_credentials(self, raw: str) -> CredentialValidation:
        raise NotImplementedError

    @abstractmethod
    def build_worker_config(self, *, account: dict[str, Any], subscription: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def run_account(
        self,
        credential: dict[str, Any],
        config: dict[str, Any],
        stop_event,
        emit: Callable[..., None],
    ) -> None:
        raise NotImplementedError
