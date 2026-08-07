from __future__ import annotations

import importlib.util
import math
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V24_FILE = SCRIPT_DIR / "eldoria_bot_v2_4_base.py"
V232_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_base.py"
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_5_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_5_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (
    V24_FILE,
    V232_FILE,
    V22_FILE,
    V21_FILE,
    V161_FILE,
    V15_FILE,
    ENGINE_FILE,
):
    if not required.exists():
        raise RuntimeError(f"Required file is missing: {required}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v24_base",
    V24_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.4 base could not be loaded.")

v24 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v24
spec.loader.exec_module(v24)

v232 = v24.v232
v22 = v24.v22
v21 = v24.v21
v161 = v24.v161
base = v24.base
engine = v24.engine

for module in (v24, v232, v22, v21, v161, base, engine):
    module.SCRIPT_DIR = SCRIPT_DIR
    module.DESKTOP = DESKTOP
    module.ELDORIA_ROOT = ELDORIA_ROOT
    module.PRIVATE_DIR = PRIVATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.PROJECT_DIR = PROJECT_DIR
    module.STATE_DIR = STATE_DIR
    module.LOG_DIR = LOG_DIR
    module.COOKIE_FILE = PRIVATE_DIR / "cookie.txt"
    module.TOKEN_FILE = PRIVATE_DIR / "token.txt"
    module.CONFIG_FILE = CONFIG_FILE
    module.COMBAT_HISTORY_FILE = STATE_DIR / "combat_history.json"
    module.RUNTIME_STATE_FILE = STATE_DIR / "runtime_state.json"
    module.LAST_REPORT_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_5_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_5_final.log"
    )

for module in (v24, v232, v22, v21, v161, base):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(
        character
        for character in text
        if character.isalnum()
    )


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_5_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_5_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_5_final.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


@dataclass
class ProfessionalQuestObjective:
    quest_id: int | None
    quest_code: str
    quest_name: str
    quest_type: str
    objective_type: str
    target: str
    remaining: int
    reward_gold: int
    reward_xp: int
    zone_id: int | None = None
    zone_code: str = ""
    expires_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def seconds_to_expiry(self) -> float | None:
        expires = parse_datetime(self.expires_at)
        if expires is None:
            return None
        return (
            expires - datetime.now(timezone.utc)
        ).total_seconds()


class ProfessionalQuestEngine(v24.AdaptiveTierTrainer):
    VERSION = "2.5-final-professional-quest-engine-windows"

    FREE_SUPPORTED_OBJECTIVES = {
        "kill",
        "craft",
        "loot",
    }

    PAID_OBJECTIVES = {
        "deposit",
        "withdraw",
        "vip",
        "battle_pass",
        "purchase",
        "bazaar_buy",
        "market_buy",
        "p2p_buy",
    }

    QUEST_TYPE_RANK = {
        "daily": 0,
        "weekly": 1,
        "main": 2,
        "side": 3,
    }

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.quest_engine_file = (
            STATE_DIR / "professional_quest_engine_state.json"
        )
        self.quest_engine = engine.load_json(
            self.quest_engine_file,
            {
                "schema_version": 1,
                "quest_cache": {
                    "mine": [],
                    "available": [],
                    "fetched_at": 0.0,
                },
                "combat_samples": {},
                "last_cache_warning": "",
                "last_board_signature": "",
                "last_board_log_at": 0.0,
                "deferred_codes": [],
                "emergency_craft_times": [],
                "quest_starts": 0,
                "quest_claims": 0,
                "generic_crafts": 0,
            },
        )

        if not isinstance(
            self.quest_engine.get("quest_cache"),
            dict,
        ):
            self.quest_engine["quest_cache"] = {
                "mine": [],
                "available": [],
                "fetched_at": 0.0,
            }

        if not isinstance(
            self.quest_engine.get("combat_samples"),
            dict,
        ):
            self.quest_engine["combat_samples"] = {}

        self.save_quest_engine()

    def save_quest_engine(self) -> None:
        engine.save_json(
            self.quest_engine_file,
            self.quest_engine,
        )

    # ----------------------------------------------------------
    # One shared Quest snapshot prevents mine/available from being
    # downloaded repeatedly by claim, start, craft and combat planning.
    # ----------------------------------------------------------

    def invalidate_quest_cache(self) -> None:
        cache = self.quest_engine.setdefault(
            "quest_cache",
            {},
        )
        cache["fetched_at"] = 0.0
        self.save_quest_engine()

    def get_quests(
        self,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        now = time.time()
        cache = self.quest_engine.setdefault(
            "quest_cache",
            {
                "mine": [],
                "available": [],
                "fetched_at": 0.0,
            },
        )

        mine_cached = cache.get("mine", [])
        available_cached = cache.get("available", [])
        fetched_at = as_float(cache.get("fetched_at"), 0.0)
        age = max(0.0, now - fetched_at)

        fresh_seconds = float(
            self.config["professional_quests"][
                "quest_cache_fresh_seconds"
            ]
        )
        stale_seconds = float(
            self.config["professional_quests"][
                "quest_cache_stale_seconds"
            ]
        )

        if (
            not force
            and fetched_at > 0
            and age <= fresh_seconds
            and isinstance(mine_cached, list)
            and isinstance(available_cached, list)
        ):
            return (
                deepcopy(mine_cached),
                deepcopy(available_cached),
            )

        try:
            mine_data = self.require(
                self.client.get("quests/mine"),
                "Read active quests",
            )
            available_data = self.require(
                self.client.get("quests/available"),
                "Read available quests",
            )

            mine = (
                mine_data.get("quests", [])
                if isinstance(mine_data, dict)
                else []
            )
            available = (
                available_data.get("quests", [])
                if isinstance(available_data, dict)
                else []
            )

            mine = mine if isinstance(mine, list) else []
            available = (
                available
                if isinstance(available, list)
                else []
            )

            cache.update(
                {
                    "mine": deepcopy(mine),
                    "available": deepcopy(available),
                    "fetched_at": now,
                }
            )
            self.quest_engine["last_cache_warning"] = ""
            self.save_quest_engine()

            return mine, available

        except Exception as exc:
            cache_usable = bool(
                fetched_at > 0
                and age <= stale_seconds
                and isinstance(mine_cached, list)
                and isinstance(available_cached, list)
            )

            if cache_usable:
                warning = (
                    f"{type(exc).__name__}:{exc}:"
                    f"{int(age // 60)}"
                )
                if (
                    self.quest_engine.get(
                        "last_cache_warning"
                    )
                    != warning
                ):
                    self.quest_engine[
                        "last_cache_warning"
                    ] = warning
                    self.save_quest_engine()
                    self.logger.info(
                        "[QUEST CACHE] Network unavailable; "
                        "using the last Quest board (%s minutes old).",
                        int(age // 60),
                    )

                return (
                    deepcopy(mine_cached),
                    deepcopy(available_cached),
                )

            raise

    # ----------------------------------------------------------
    # Rich objective parser: Daily/Weekly, deadline and zone survive
    # into the combat planner.
    # ----------------------------------------------------------

    @staticmethod
    def objective_zone_id(
        quest: dict[str, Any],
        objective: dict[str, Any],
    ) -> int | None:
        for key in (
            "zone_id",
            "target_zone_id",
            "location_id",
            "area_id",
        ):
            value = objective.get(key)
            if value is None:
                continue
            parsed = as_int(value, 0)
            if parsed > 0:
                return parsed

        parsed = as_int(quest.get("zone_id"), 0)
        return parsed if parsed > 0 else None

    @staticmethod
    def objective_zone_code(
        objective: dict[str, Any],
    ) -> str:
        for key in (
            "zone_code",
            "target_zone",
            "location",
            "area",
        ):
            value = str(objective.get(key) or "").strip()
            if value:
                return value
        return ""

    def objective_rows(
        self,
    ) -> list[ProfessionalQuestObjective]:
        mine, _ = self.get_quests()
        rows: list[ProfessionalQuestObjective] = []

        for quest in mine:
            if str(
                quest.get("status", "")
            ).lower() != "active":
                continue

            quest_type = str(
                quest.get("type") or "side"
            ).lower()
            expires_at = str(
                quest.get("expires_at") or ""
            )

            for objective in self.quest_objectives(
                quest,
                use_progress=True,
            ):
                if not isinstance(objective, dict):
                    continue

                objective_type = str(
                    objective.get("type", "")
                ).lower()
                total = as_int(
                    objective.get("count"),
                    0,
                )
                current = as_int(
                    objective.get("current"),
                    0,
                )
                remaining = max(0, total - current)

                if remaining <= 0:
                    continue

                rows.append(
                    ProfessionalQuestObjective(
                        quest_id=quest.get("id"),
                        quest_code=str(
                            quest.get("code", "")
                        ),
                        quest_name=str(
                            quest.get("name_en")
                            or quest.get("name")
                            or quest.get("code")
                        ),
                        quest_type=quest_type,
                        objective_type=objective_type,
                        target=str(
                            objective.get("target", "any")
                        ),
                        remaining=remaining,
                        reward_gold=as_int(
                            quest.get("gold_reward"),
                            0,
                        ),
                        reward_xp=as_int(
                            quest.get("xp_reward"),
                            0,
                        ),
                        zone_id=self.objective_zone_id(
                            quest,
                            objective,
                        ),
                        zone_code=self.objective_zone_code(
                            objective
                        ),
                        expires_at=expires_at,
                        raw=deepcopy(objective),
                    )
                )

        return rows

    # ----------------------------------------------------------
    # Daily and expiring Quests are started/claimed first.
    # Paid objectives remain blocked.
    # ----------------------------------------------------------

    def quest_sort_key(
        self,
        quest: dict[str, Any],
    ):
        quest_type = str(
            quest.get("type") or "side"
        ).lower()
        expires = parse_datetime(
            quest.get("expires_at")
        )
        expiry_key = (
            expires.timestamp()
            if expires is not None
            else float("inf")
        )

        return (
            self.QUEST_TYPE_RANK.get(
                quest_type,
                9,
            ),
            expiry_key,
            -as_int(quest.get("gold_reward"), 0),
            -as_int(quest.get("xp_reward"), 0),
        )

    def start_all_free_quests(self) -> None:
        _, available = self.get_quests()

        changed = False
        deferred = set(
            self.quest_engine.get(
                "deferred_codes",
                [],
            )
        )

        for quest in sorted(
            available,
            key=self.quest_sort_key,
        ):
            code = str(quest.get("code", ""))
            objectives = self.quest_objectives(
                quest,
                use_progress=False,
            )
            objective_types = {
                str(item.get("type", "")).lower()
                for item in objectives
                if isinstance(item, dict)
            }

            if not objective_types:
                continue

            if objective_types.intersection(
                self.PAID_OBJECTIVES
            ):
                if code not in deferred:
                    self.logger.info(
                        "[QUEST BLOCKED] %s requires a paid "
                        "or market action.",
                        quest.get("name_en")
                        or quest.get("name")
                        or code,
                    )
                    deferred.add(code)
                continue

            unsupported = (
                objective_types
                - self.FREE_SUPPORTED_OBJECTIVES
            )
            if unsupported:
                if code not in deferred:
                    self.logger.info(
                        "[QUEST DEFERRED] %s | unsupported free "
                        "objective: %s.",
                        quest.get("name_en")
                        or quest.get("name")
                        or code,
                        ", ".join(sorted(unsupported)),
                    )
                    deferred.add(code)
                continue

            quest_id = quest.get("id")
            if quest_id is None:
                continue

            result = self.client.post(
                f"quests/start/{quest_id}"
            )

            self.record(
                "start_quest",
                result.ok,
                {
                    "quest_id": quest_id,
                    "quest": (
                        quest.get("name_en")
                        or quest.get("name")
                    ),
                    "types": sorted(objective_types),
                    "status": result.status,
                    "error": result.error,
                },
            )

            if result.ok:
                quest_type = str(
                    quest.get("type") or "side"
                ).upper()
                self.logger.info(
                    "[%s QUEST] Started: %s",
                    quest_type,
                    quest.get("name_en")
                    or quest.get("name"),
                )
                self.quest_engine["quest_starts"] = (
                    as_int(
                        self.quest_engine.get(
                            "quest_starts"
                        ),
                        0,
                    )
                    + 1
                )
                changed = True

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

        self.quest_engine["deferred_codes"] = sorted(
            deferred
        )
        self.save_quest_engine()

        if changed:
            self.invalidate_quest_cache()

    def claim_free_rewards(self) -> None:
        payload = self.get_character_payload()
        claim = payload.get("claim")

        if (
            isinstance(claim, dict)
            and claim.get("can_claim")
        ):
            result = self.client.post(
                "character/claim-daily"
            )
            self.record(
                "claim_daily_gold",
                result.ok,
                {
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                gained = as_int(
                    engine.deep_find_number(
                        result.data,
                        {
                            "gold",
                            "gold_gained",
                            "amount",
                        },
                    ),
                    0,
                )
                self.total_gold_gained += gained
                self.logger.info(
                    "[DAILY REWARD] Free Gold claimed%s.",
                    f": +{gained}" if gained else "",
                )

        mine, _ = self.get_quests()
        completed = [
            quest
            for quest in mine
            if str(
                quest.get("status", "")
            ).lower() == "completed"
        ]

        changed = False

        for quest in sorted(
            completed,
            key=self.quest_sort_key,
        ):
            quest_instance_id = quest.get("id")
            if quest_instance_id is None:
                continue

            result = self.client.post(
                f"quests/claim/{quest_instance_id}"
            )
            self.record(
                "claim_quest",
                result.ok,
                {
                    "quest_id": quest_instance_id,
                    "quest": (
                        quest.get("name_en")
                        or quest.get("name")
                    ),
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                gained = as_int(
                    engine.deep_find_number(
                        result.data,
                        {
                            "gold",
                            "gold_gained",
                        },
                    ),
                    0,
                )
                self.total_gold_gained += gained
                quest_type = str(
                    quest.get("type") or "side"
                ).upper()
                self.logger.info(
                    "[%s QUEST] Claimed: %s%s",
                    quest_type,
                    quest.get("name_en")
                    or quest.get("name"),
                    (
                        f" | +{gained} Gold"
                        if gained
                        else ""
                    ),
                )
                self.quest_engine["quest_claims"] = (
                    as_int(
                        self.quest_engine.get(
                            "quest_claims"
                        ),
                        0,
                    )
                    + 1
                )
                changed = True

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

        self.save_quest_engine()

        if changed:
            self.invalidate_quest_cache()

    # ----------------------------------------------------------
    # Zone-aware matching and multi-Quest stacking.
    # One Fight can progress Daily + target Quest + weekly any-kill
    # + loot at the same time.
    # ----------------------------------------------------------

    def zone_identity(
        self,
        zone_id: int,
        zone_name: str,
    ) -> set[str]:
        values = {
            normalize_text(zone_id),
            normalize_text(zone_name),
        }

        try:
            for zone in self.get_zone_catalog():
                if as_int(zone.get("id"), 0) != zone_id:
                    continue
                for key in (
                    "code",
                    "name",
                    "name_en",
                    "slug",
                ):
                    values.add(
                        normalize_text(zone.get(key))
                    )
                break
        except Exception:
            pass

        return {
            value
            for value in values
            if value
        }

    def objective_matches_candidate(
        self,
        objective: ProfessionalQuestObjective,
        candidate,
    ) -> bool:
        if objective.objective_type not in {
            "kill",
            "loot",
        }:
            return False

        if (
            objective.zone_id is not None
            and candidate.zone_id
            != objective.zone_id
        ):
            return False

        zone_values = self.zone_identity(
            candidate.zone_id,
            candidate.zone_name,
        )
        zone_code = normalize_text(
            objective.zone_code
        )

        if zone_code and zone_code not in zone_values:
            return False

        target = normalize_text(objective.target)
        monster_code = normalize_text(
            candidate.monster.get("code")
        )
        monster_name = normalize_text(
            candidate.monster.get("name_en")
            or candidate.monster.get("name")
        )

        if objective.objective_type == "loot":
            if target in {"", "any"}:
                return True
            return target in {
                monster_code,
                monster_name,
            }

        if target in {"", "any"}:
            return True

        if target in {
            monster_code,
            monster_name,
        }:
            return True

        # Some zone-specific Daily objectives encode the zone as target.
        if target in zone_values:
            return True

        return False

    def deadline_weight(
        self,
        objective: ProfessionalQuestObjective,
    ) -> float:
        seconds = objective.seconds_to_expiry()

        if seconds is None:
            return 0.0
        if seconds <= 0:
            return 0.0
        if seconds <= 2 * 3600:
            return 800.0
        if seconds <= 6 * 3600:
            return 500.0
        if seconds <= 24 * 3600:
            return 260.0
        if seconds <= 72 * 3600:
            return 100.0
        return 20.0

    def quest_hit_score(
        self,
        objective: ProfessionalQuestObjective,
    ) -> float:
        type_weight = {
            "daily": 700.0,
            "weekly": 320.0,
            "main": 260.0,
            "side": 150.0,
        }.get(objective.quest_type, 100.0)

        exact_weight = (
            180.0
            if normalize_text(objective.target)
            not in {"", "any"}
            else 80.0
        )
        reward_weight = (
            objective.reward_gold * 0.20
            + objective.reward_xp * 0.14
        ) / max(1, objective.remaining)

        return (
            type_weight
            + exact_weight
            + self.deadline_weight(objective)
            + reward_weight
        )

    def build_farm_candidates(
        self,
        character,
        objectives,
        material_needs,
    ):
        candidates = super().build_farm_candidates(
            character,
            objectives,
            material_needs,
        )

        for candidate in candidates:
            hits = [
                objective
                for objective in objectives
                if isinstance(
                    objective,
                    ProfessionalQuestObjective,
                )
                and self.objective_matches_candidate(
                    objective,
                    candidate,
                )
            ]

            candidate.quest_hits = hits
            candidate.quest_score = sum(
                self.quest_hit_score(row)
                for row in hits
            )
            candidate.quest_overlap = len(hits)
            candidate.daily_hits = sum(
                1
                for row in hits
                if row.quest_type == "daily"
            )
            candidate.urgent_hits = sum(
                1
                for row in hits
                if (
                    row.seconds_to_expiry()
                    is not None
                    and 0
                    < row.seconds_to_expiry()
                    <= 24 * 3600
                )
            )
            candidate.quest_reward_value = sum(
                row.reward_gold
                + row.reward_xp * 0.5
                for row in hits
            )

            if hits:
                best = max(
                    hits,
                    key=self.quest_hit_score,
                )
                candidate.priority = (
                    0
                    if (
                        candidate.daily_hits > 0
                        or candidate.urgent_hits > 0
                    )
                    else 1
                    if any(
                        row.quest_type
                        in {"main", "weekly"}
                        for row in hits
                    )
                    else 2
                )

                extra = len(hits) - 1
                candidate.reason = (
                    f"{best.quest_name} "
                    f"({best.remaining} remaining)"
                    + (
                        f" + {extra} overlapping Quest"
                        if extra == 1
                        else f" + {extra} overlapping Quests"
                        if extra > 1
                        else ""
                    )
                )
            elif candidate.material_score > 0:
                candidate.priority = 3
                candidate.reason = (
                    "Craft material farming"
                )
            else:
                candidate.priority = 4
                candidate.reason = (
                    "Continuous Gold farming"
                )

        candidates.sort(
            key=lambda row: (
                row.priority,
                -as_float(
                    getattr(row, "quest_score", 0.0)
                ),
                -as_int(
                    getattr(row, "quest_overlap", 0)
                ),
                row.predicted_damage,
                -row.xp_per_stamina,
                -row.gold_per_stamina,
            )
        )
        return candidates

    def choose_action(
        self,
        character: dict[str, Any],
        objectives,
        material_needs,
    ):
        selected, states = super().choose_action(
            character,
            objectives,
            material_needs,
        )

        ready_quests = [
            row
            for row in states
            if row.get("state") == "ready"
            and as_int(
                getattr(
                    row["candidate"],
                    "quest_overlap",
                    0,
                ),
                0,
            )
            > 0
        ]

        if ready_quests:
            ready_quests.sort(
                key=lambda row: (
                    -as_float(
                        getattr(
                            row["candidate"],
                            "quest_score",
                            0.0,
                        )
                    ),
                    -as_int(
                        getattr(
                            row["candidate"],
                            "quest_overlap",
                            0,
                        )
                    ),
                    row.get("risk_ratio", 999.0),
                    -row["candidate"].xp_per_stamina,
                    -row["candidate"].gold_per_stamina,
                )
            )
            return ready_quests[0], states

        return selected, states

    # ----------------------------------------------------------
    # Contextual damage model.
    # Old all-time maximums no longer force 2-3 hours of healing.
    # Recent victories and the current Power are used instead.
    # ----------------------------------------------------------

    def combat_sample_rows(
        self,
        monster_id: int,
    ) -> list[dict[str, Any]]:
        rows = self.quest_engine.setdefault(
            "combat_samples",
            {},
        ).get(str(monster_id), [])

        return rows if isinstance(rows, list) else []

    def record_contextual_damage(
        self,
        monster_id: int,
        damage: int,
        character: dict[str, Any],
        predicted: int,
    ) -> None:
        if monster_id <= 0 or damage < 0:
            return

        rows = self.quest_engine.setdefault(
            "combat_samples",
            {},
        ).setdefault(str(monster_id), [])

        if not isinstance(rows, list):
            rows = []
            self.quest_engine["combat_samples"][
                str(monster_id)
            ] = rows

        rows.append(
            {
                "damage": damage,
                "level": as_int(
                    character.get("level"),
                    1,
                ),
                "power": max(
                    1.0,
                    self.current_power(character),
                ),
                "hp_max": as_int(
                    character.get("hp_max"),
                    1,
                ),
                "predicted": max(0, predicted),
                "at": utc_now(),
            }
        )

        maximum_samples = int(
            self.config["professional_quests"][
                "combat_sample_window"
            ]
        )
        del rows[:-maximum_samples]
        self.save_quest_engine()

    def contextual_damage_estimate(
        self,
        monster_id: int,
        character: dict[str, Any],
    ) -> tuple[float | None, str]:
        current_power = max(
            1.0,
            self.current_power(character),
        )
        samples = self.combat_sample_rows(
            monster_id
        )

        scaled = []

        for sample in samples[-5:]:
            damage = max(
                0.0,
                as_float(sample.get("damage"), 0.0),
            )
            sample_power = max(
                1.0,
                as_float(
                    sample.get("power"),
                    current_power,
                ),
            )
            # More current Power reduces the relevance of an older,
            # weaker-character sample, but never aggressively.
            power_scale = math.sqrt(
                min(
                    1.35,
                    sample_power / current_power,
                )
            )
            scaled.append(damage * power_scale)

        if scaled:
            recent = scaled[-3:]
            estimate = max(
                max(recent),
                sum(recent) / len(recent) * 1.08,
            )
            return estimate, "recent"

        aggregate = self.smart_state.get(
            "successful_damage",
            {},
        ).get(str(monster_id))

        if (
            isinstance(aggregate, dict)
            and as_int(aggregate.get("count"), 0) > 0
        ):
            # Deliberately ignore the all-time maximum.
            average = max(
                0.0,
                as_float(
                    aggregate.get("average"),
                    0.0,
                ),
            )
            if average > 0:
                return average, "legacy-average"

        return None, "prediction"

    def combat_assessment(
        self,
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        row = super().combat_assessment(
            candidate,
            character,
        )

        monster = candidate.monster
        monster_id = as_int(monster.get("id"), 0)

        if monster_id <= 0 or self.is_boss(monster):
            return row

        if self.death_lock_active(
            monster,
            character,
        ):
            return row

        estimate, confidence = (
            self.contextual_damage_estimate(
                monster_id,
                character,
            )
        )
        if estimate is None:
            return row

        hp = max(
            0,
            as_int(character.get("hp"), 0),
        )
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        stamina = max(
            0,
            as_int(character.get("stamina"), 0),
        )
        stamina_cost = max(
            1,
            as_int(
                monster.get("stamina_cost"),
                1,
            ),
        )

        sample_count = len(
            self.combat_sample_rows(monster_id)
        )
        if sample_count >= 2:
            margin = float(
                self.config["professional_quests"][
                    "recent_damage_margin"
                ]
            )
            buffer = int(
                self.config["professional_quests"][
                    "recent_hp_buffer"
                ]
            )
        else:
            margin = float(
                self.config["professional_quests"][
                    "legacy_average_margin"
                ]
            )
            buffer = int(
                self.config["professional_quests"][
                    "legacy_average_hp_buffer"
                ]
            )

        required_hp = math.ceil(
            estimate * margin + buffer
        )

        if required_hp > hp_max:
            state = "strengthen"
        elif hp < required_hp:
            state = "heal"
        elif stamina < stamina_cost:
            state = "resource"
        else:
            state = "ready"

        updated = dict(row)
        updated.update(
            {
                "state": state,
                "reason": (
                    f"contextual damage model: "
                    f"{confidence}"
                ),
                "required_hp": required_hp,
                "stamina_target": stamina_cost,
                "mp_target": 0,
                "estimate": estimate,
                "risk_ratio": estimate / hp_max,
                "quest_exact": (
                    candidate.priority == 0
                ),
                "quest_related": (
                    candidate.priority <= 2
                ),
                "hp_short": max(
                    0,
                    required_hp - hp,
                ),
                "stamina_short": max(
                    0,
                    stamina_cost - stamina,
                ),
                "mp_short": 0,
                "actionable": state == "ready",
                "confidence": confidence,
            }
        )
        return updated

    def latest_fight_damage(
        self,
        monster_id: int,
    ) -> int:
        for action in reversed(self.actions):
            if not isinstance(action, dict):
                continue
            if action.get("action") != "fight":
                continue

            details = action.get("details", {})
            if not isinstance(details, dict):
                continue
            if as_int(
                details.get("monster_id"),
                0,
            ) != monster_id:
                continue

            response = details.get("response")
            return max(
                0,
                as_int(
                    engine.deep_find_number(
                        response,
                        {
                            "damage_taken",
                            "total_damage_taken",
                        },
                    ),
                    0,
                ),
            )

        return 0

    def execute_fight(self, candidate) -> bool:
        before = deepcopy(
            self._scheduler_character
            if isinstance(
                self._scheduler_character,
                dict,
            )
            else self.get_character()
        )
        monster_id = as_int(
            candidate.monster.get("id"),
            0,
        )

        result = super().execute_fight(candidate)

        if result:
            damage = self.latest_fight_damage(
                monster_id
            )
            if damage > 0:
                self.record_contextual_damage(
                    monster_id,
                    damage,
                    before,
                    as_int(
                        candidate.predicted_damage,
                        0,
                    ),
                )
            self.invalidate_quest_cache()

        return result

    def after_fight_housekeeping(self) -> None:
        self.invalidate_quest_cache()
        super().after_fight_housekeeping()

    # ----------------------------------------------------------
    # Craft "any potion" objectives and emergency Minor HP potions.
    # ----------------------------------------------------------

    def craft_capacity(
        self,
        recipe: dict[str, Any],
        gold: int,
        reserve: int,
    ) -> int:
        capacity = 10**9
        ingredients = recipe.get("ingredients", [])
        if not isinstance(ingredients, list):
            return 0

        for ingredient in ingredients:
            qty = max(
                0,
                as_int(ingredient.get("qty"), 0),
            )
            have = max(
                0,
                as_int(ingredient.get("have"), 0),
            )
            if qty <= 0:
                continue
            capacity = min(
                capacity,
                have // qty,
            )

        cost = max(
            0,
            as_int(recipe.get("gold_cost"), 0),
        )
        if cost > 0:
            capacity = min(
                capacity,
                max(0, (gold - reserve) // cost),
            )

        if capacity == 10**9:
            return 0

        return max(0, capacity)

    def common_potion_recipes(
        self,
    ) -> list[dict[str, Any]]:
        recipes = self.recipe_rows()
        result = []

        for recipe in recipes:
            category = str(
                recipe.get("category") or ""
            ).lower()
            if category not in {
                "potion_hp",
                "potion_mp",
            }:
                continue

            output = recipe.get("output")
            if not isinstance(output, dict):
                continue

            rarity = str(
                output.get("rarity") or "common"
            ).lower()
            if rarity not in {
                "common",
                "uncommon",
            }:
                continue

            result.append(recipe)

        result.sort(
            key=lambda recipe: (
                str(
                    recipe.get("category")
                ).lower() != "potion_hp",
                as_int(
                    recipe.get("gold_cost"),
                    0,
                ),
                as_int(
                    recipe.get("level_req"),
                    0,
                ),
            )
        )
        return result

    def complete_generic_craft_quests(
        self,
    ) -> int:
        objectives = [
            row
            for row in self.objective_rows()
            if row.objective_type == "craft"
            and normalize_text(row.target)
            in {
                "",
                "any",
                "anypotion",
                "potionany",
            }
        ]

        if not objectives:
            return 0

        character = self.get_character()
        gold = as_int(character.get("gold"), 0)
        reserve = max(
            as_int(
                self.config["economy"][
                    "absolute_minimum_gold"
                ],
                0,
            ),
            int(gold * 0.10),
        )
        remaining = min(
            row.remaining
            for row in objectives
        )
        maximum = int(
            self.config["professional_quests"][
                "generic_crafts_per_cycle"
            ]
        )

        for recipe in self.common_potion_recipes():
            capacity = self.craft_capacity(
                recipe,
                gold,
                reserve,
            )
            count = min(
                remaining,
                maximum,
                capacity,
            )
            if count <= 0:
                continue

            crafted = 0

            for _ in range(count):
                result = self.client.post(
                    f"crafting/table/craft/{recipe['id']}"
                )
                if not result.ok:
                    break
                crafted += 1
                time.sleep(
                    float(
                        self.config["automation"][
                            "action_delay_seconds"
                        ]
                    )
                )

            if crafted > 0:
                output = recipe.get("output", {})
                self.logger.info(
                    "[QUEST CRAFT] Crafted %s x%s for "
                    "generic potion objectives.",
                    output.get("name")
                    or output.get("code")
                    or recipe.get("name"),
                    crafted,
                )
                self.quest_engine["generic_crafts"] = (
                    as_int(
                        self.quest_engine.get(
                            "generic_crafts"
                        ),
                        0,
                    )
                    + crafted
                )
                self.save_quest_engine()
                self.invalidate_quest_cache()
                return crafted

        return 0

    def complete_craft_quests(
        self,
    ) -> dict[str, int]:
        materials = super().complete_craft_quests()
        self.invalidate_quest_cache()

        try:
            self.complete_generic_craft_quests()
        except Exception as exc:
            self.logger.info(
                "[RECOVER] Generic potion crafting skipped: %s",
                exc,
            )

        return materials

    def emergency_craft_allowed(self) -> bool:
        now = time.time()
        window = 3600.0
        maximum = int(
            self.config["professional_quests"][
                "max_emergency_hp_crafts_per_hour"
            ]
        )

        times = self.quest_engine.get(
            "emergency_craft_times",
            [],
        )
        if not isinstance(times, list):
            times = []

        times = [
            as_float(value)
            for value in times
            if now - as_float(value) <= window
        ]
        self.quest_engine[
            "emergency_craft_times"
        ] = times
        self.save_quest_engine()

        return len(times) < maximum

    def craft_emergency_hp_potions(
        self,
        requested: int,
    ) -> int:
        if requested <= 0:
            return 0
        if not self.emergency_craft_allowed():
            return 0

        character = self.get_character()
        gold = as_int(character.get("gold"), 0)
        reserve = max(
            as_int(
                self.config["economy"][
                    "absolute_minimum_gold"
                ],
                0,
            ),
            int(gold * 0.15),
        )

        recipes = [
            recipe
            for recipe in self.common_potion_recipes()
            if str(
                recipe.get("category") or ""
            ).lower() == "potion_hp"
        ]

        for recipe in recipes:
            capacity = self.craft_capacity(
                recipe,
                gold,
                reserve,
            )
            count = min(
                requested,
                capacity,
                int(
                    self.config[
                        "professional_quests"
                    ][
                        "emergency_hp_crafts_per_attempt"
                    ]
                ),
            )
            if count <= 0:
                continue

            crafted = 0

            for _ in range(count):
                result = self.client.post(
                    f"crafting/table/craft/{recipe['id']}"
                )
                if not result.ok:
                    break
                crafted += 1
                self.quest_engine.setdefault(
                    "emergency_craft_times",
                    [],
                ).append(time.time())
                time.sleep(
                    float(
                        self.config["automation"][
                            "action_delay_seconds"
                        ]
                    )
                )

            if crafted > 0:
                self.save_quest_engine()
                self.invalidate_quest_cache()
                self.logger.info(
                    "[QUEST SPEED] Crafted %s emergency HP "
                    "Potion(s) to avoid a long Quest wait.",
                    crafted,
                )
                return crafted

        return 0

    def natural_hp_wait_seconds(
        self,
        character: dict[str, Any],
        required_hp: int,
    ) -> float:
        hp = as_int(character.get("hp"), 0)
        missing = max(0, required_hp - hp)
        regen = as_float(
            character.get("hp_regen_per_hour"),
            0.0,
        )
        if missing <= 0:
            return 0.0
        if regen <= 0:
            return float("inf")
        return missing / regen * 3600.0

    def try_quest_resources(
        self,
        pending,
        character: dict[str, Any],
    ) -> bool:
        used = super().try_quest_resources(
            pending,
            character,
        )
        if used or not isinstance(pending, dict):
            return bool(used)

        required_hp = as_int(
            pending.get(
                "required_hp",
                pending.get("hp_target"),
            ),
            0,
        )
        hp_short = as_int(
            pending.get("hp_short"),
            0,
        )

        if required_hp <= 0 or hp_short <= 0:
            return False

        candidate = pending.get("candidate")
        quest_score = as_float(
            getattr(
                candidate,
                "quest_score",
                0.0,
            )
            if candidate is not None
            else 0.0
        )
        overlap = as_int(
            getattr(
                candidate,
                "quest_overlap",
                0,
            )
            if candidate is not None
            else 0
        )
        wait_seconds = self.natural_hp_wait_seconds(
            character,
            required_hp,
        )

        minimum_wait = float(
            self.config["professional_quests"][
                "emergency_potion_wait_seconds"
            ]
        )
        minimum_score = float(
            self.config["professional_quests"][
                "emergency_potion_minimum_quest_score"
            ]
        )

        if (
            wait_seconds < minimum_wait
            or (
                quest_score < minimum_score
                and overlap < 2
            )
        ):
            return False

        crafted = self.safe_step(
            "Emergency Quest HP crafting",
            lambda: self.craft_emergency_hp_potions(
                requested=3
            ),
            0,
        )

        if not crafted:
            return False

        return bool(
            self.safe_step(
                "Emergency Quest HP Potion",
                lambda: self.use_hp_potions_until_safe(
                    required_hp,
                    high_priority=True,
                ),
                False,
            )
        )

    # ----------------------------------------------------------
    # Quest board visibility.
    # ----------------------------------------------------------

    def log_quest_board(self) -> None:
        mine, available = self.get_quests()
        active = [
            quest
            for quest in mine
            if str(
                quest.get("status", "")
            ).lower() == "active"
        ]
        completed = [
            quest
            for quest in mine
            if str(
                quest.get("status", "")
            ).lower() == "completed"
        ]

        daily = sum(
            1
            for quest in active
            if str(
                quest.get("type") or ""
            ).lower() == "daily"
        )
        weekly = sum(
            1
            for quest in active
            if str(
                quest.get("type") or ""
            ).lower() == "weekly"
        )
        urgent = 0
        supported = 0
        deferred = 0
        paid = 0

        for quest in active:
            expires = parse_datetime(
                quest.get("expires_at")
            )
            if (
                expires is not None
                and 0
                < (
                    expires
                    - datetime.now(timezone.utc)
                ).total_seconds()
                <= 24 * 3600
            ):
                urgent += 1

            types = {
                str(row.get("type") or "").lower()
                for row in self.quest_objectives(
                    quest,
                    use_progress=True,
                )
                if isinstance(row, dict)
            }

            if types.intersection(
                self.PAID_OBJECTIVES
            ):
                paid += 1
            elif types.issubset(
                self.FREE_SUPPORTED_OBJECTIVES
            ):
                supported += 1
            else:
                deferred += 1

        signature = (
            f"{len(active)}:{len(completed)}:"
            f"{len(available)}:{daily}:{weekly}:"
            f"{urgent}:{supported}:{deferred}:{paid}"
        )
        now = time.time()
        interval = float(
            self.config["professional_quests"][
                "quest_board_log_seconds"
            ]
        )

        if (
            signature
            == self.quest_engine.get(
                "last_board_signature"
            )
            and now
            - as_float(
                self.quest_engine.get(
                    "last_board_log_at"
                ),
                0.0,
            )
            < interval
        ):
            return

        self.quest_engine[
            "last_board_signature"
        ] = signature
        self.quest_engine[
            "last_board_log_at"
        ] = now
        self.save_quest_engine()

        self.logger.info(
            "[QUEST BOARD] Active %s | Daily %s | Weekly %s | "
            "Urgent %s | Ready to claim %s | Available %s | "
            "automated %s | deferred free %s | paid blocked %s.",
            len(active),
            daily,
            weekly,
            urgent,
            len(completed),
            len(available),
            supported,
            deferred,
            paid,
        )

    def run_housekeeping(
        self,
        now: float,
        startup: bool = False,
    ) -> None:
        super().run_housekeeping(
            now,
            startup=startup,
        )
        self.safe_step(
            "Quest Board",
            self.log_quest_board,
        )

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "professional_quest_engine_state": (
                    self.quest_engine
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_5_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_5_final_"
                + datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
                + ".json"
            ),
            report,
        )
        return report


def main() -> int:
    for directory in (
        ELDORIA_ROOT,
        PRIVATE_DIR,
        OUTPUT_DIR,
        PROJECT_DIR,
        STATE_DIR,
        LOG_DIR,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    if not CONFIG_FILE.exists():
        print(
            f"Configuration file is missing: "
            f"{CONFIG_FILE}"
        )
        return 2

    config = engine.load_json(
        CONFIG_FILE,
        {},
    )
    logger = configure_logging()

    try:
        client = engine.APIClient(
            config,
            logger,
        )
        bot = ProfessionalQuestEngine(
            client,
            config,
            logger,
        )
        bot.run()
        return 0

    except KeyboardInterrupt:
        logger.info(
            "[STOP] Interrupted by user."
        )
        return 130

    except Exception as exc:
        logger.exception(
            "[FATAL] %s",
            exc,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
