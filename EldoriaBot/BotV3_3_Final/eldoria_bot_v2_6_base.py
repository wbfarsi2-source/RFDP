from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V25_FILE = SCRIPT_DIR / "eldoria_bot_v2_5_base.py"
V24_FILE = SCRIPT_DIR / "eldoria_bot_v2_4_base.py"
V232_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_base.py"
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_6_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_6_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (
    V25_FILE,
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
    "eldoria_v25_base",
    V25_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.5 base could not be loaded.")

v25 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v25
spec.loader.exec_module(v25)

v24 = v25.v24
v232 = v25.v232
v22 = v25.v22
v21 = v25.v21
v161 = v25.v161
base = v25.base
engine = v25.engine

for module in (
    v25,
    v24,
    v232,
    v22,
    v21,
    v161,
    base,
    engine,
):
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
        OUTPUT_DIR / "eldoria_bot_v2_6_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_6_final.log"
    )

for module in (
    v25,
    v24,
    v232,
    v22,
    v21,
    v161,
    base,
):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE


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


def normalize(value: Any) -> str:
    return v25.normalize_text(value)


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_6_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_6_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_6_final.log",
    ):
        handler = logging.FileHandler(
            target,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class QuestCampaignEngine(v25.ProfessionalQuestEngine):
    VERSION = "2.6-final-quest-campaign-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.campaign_file = (
            STATE_DIR / "quest_campaign_state.json"
        )
        self.campaign = engine.load_json(
            self.campaign_file,
            {
                "schema_version": 1,
                "active_key": "",
                "active_quest_id": None,
                "active_quest_code": "",
                "active_quest_name": "",
                "active_quest_type": "",
                "active_objective_type": "",
                "active_target": "",
                "active_zone_id": None,
                "active_zone_code": "",
                "active_remaining": 0,
                "mode": "idle",
                "prepared_key": "",
                "prepared_level": 0,
                "campaign_number": 0,
                "same_monster_wins": 0,
                "last_monster_id": None,
                "last_status": "",
                "completed_campaigns": 0,
            },
        )

        if not isinstance(self.campaign, dict):
            self.campaign = {}

        self.campaign.setdefault("schema_version", 1)
        self.campaign.setdefault("active_key", "")
        self.campaign.setdefault("mode", "idle")
        self.campaign.setdefault("prepared_key", "")
        self.campaign.setdefault("prepared_level", 0)
        self.campaign.setdefault("campaign_number", 0)
        self.campaign.setdefault("same_monster_wins", 0)
        self.campaign.setdefault("last_monster_id", None)
        self.campaign.setdefault("last_status", "")
        self.campaign.setdefault("completed_campaigns", 0)

        self._campaign_pending = None
        self._campaign_active = False
        self.save_campaign()

    def save_campaign(self) -> None:
        engine.save_json(
            self.campaign_file,
            self.campaign,
        )

    @staticmethod
    def objective_key(
        objective: v25.ProfessionalQuestObjective,
    ) -> str:
        return "|".join(
            [
                str(objective.quest_id or ""),
                objective.quest_code,
                objective.objective_type,
                normalize(objective.target),
                str(objective.zone_id or ""),
                normalize(objective.zone_code),
            ]
        )

    @staticmethod
    def objective_name(
        objective: v25.ProfessionalQuestObjective,
    ) -> str:
        if objective.objective_type == "craft":
            return (
                f"{objective.quest_name} | craft "
                f"{objective.target}"
            )

        if objective.zone_code:
            return (
                f"{objective.quest_name} | "
                f"{objective.zone_code}"
            )

        return (
            f"{objective.quest_name} | "
            f"{objective.target}"
        )

    def supported_campaign_objectives(
        self,
        objectives,
    ) -> list[v25.ProfessionalQuestObjective]:
        rows = []

        for objective in objectives:
            if not isinstance(
                objective,
                v25.ProfessionalQuestObjective,
            ):
                continue
            if objective.objective_type not in {
                "kill",
                "loot",
                "craft",
            }:
                continue
            rows.append(objective)

        return rows

    def objective_matches_row(
        self,
        objective: v25.ProfessionalQuestObjective,
        row: dict[str, Any],
    ) -> bool:
        candidate = row.get("candidate")
        if candidate is None:
            return False
        return self.objective_matches_candidate(
            objective,
            candidate,
        )

    @staticmethod
    def state_rank(state: str) -> int:
        return {
            "ready": 0,
            "heal": 1,
            "resource": 1,
            "strengthen": 3,
        }.get(state, 4)

    def objective_urgency_bucket(
        self,
        objective: v25.ProfessionalQuestObjective,
    ) -> int:
        seconds = objective.seconds_to_expiry()

        if (
            seconds is not None
            and 0 < seconds <= 24 * 3600
        ):
            return 0

        if objective.quest_type == "daily":
            return 1

        return 2

    def matching_rows(
        self,
        objective: v25.ProfessionalQuestObjective,
        states,
    ):
        if objective.objective_type == "craft":
            return []

        return [
            row
            for row in states
            if self.objective_matches_row(
                objective,
                row,
            )
        ]

    def craft_difficulty(
        self,
        objective: v25.ProfessionalQuestObjective,
    ) -> tuple:
        missing_total = sum(
            max(0, as_int(value))
            for value in self.cached_material_needs.values()
        )

        # Craft housekeeping runs before campaign selection.
        # A remaining Craft Quest usually means missing materials.
        material_state = 0 if missing_total == 0 else 2

        return (
            self.objective_urgency_bucket(objective),
            material_state,
            missing_total,
            objective.remaining,
            0,
            self.QUEST_TYPE_RANK.get(
                objective.quest_type,
                9,
            ),
            objective.quest_name,
        )

    def combat_objective_difficulty(
        self,
        objective: v25.ProfessionalQuestObjective,
        states,
        character: dict[str, Any],
    ) -> tuple:
        rows = self.matching_rows(
            objective,
            states,
        )

        if not rows:
            return (
                self.objective_urgency_bucket(objective),
                5,
                float("inf"),
                objective.remaining * 9999,
                9999,
                self.QUEST_TYPE_RANK.get(
                    objective.quest_type,
                    9,
                ),
                objective.quest_name,
            )

        best = min(
            rows,
            key=lambda row: (
                self.state_rank(row.get("state", "")),
                row.get("risk_ratio", 999.0),
                row.get("required_hp", 10**9),
                as_int(
                    row["candidate"].monster.get("level"),
                    0,
                ),
            ),
        )

        stamina_cost = max(
            1,
            as_int(best.get("stamina_target"), 1),
        )
        completion_cost = (
            objective.remaining * stamina_cost
        )
        monster_level = as_int(
            best["candidate"].monster.get("level"),
            0,
        )

        return (
            self.objective_urgency_bucket(objective),
            self.state_rank(best.get("state", "")),
            round(
                as_float(
                    best.get("risk_ratio"),
                    999.0,
                ),
                4,
            ),
            completion_cost,
            monster_level,
            self.QUEST_TYPE_RANK.get(
                objective.quest_type,
                9,
            ),
            objective.quest_name,
        )

    def objective_difficulty(
        self,
        objective: v25.ProfessionalQuestObjective,
        states,
        character: dict[str, Any],
    ) -> tuple:
        if objective.objective_type == "craft":
            return self.craft_difficulty(objective)

        return self.combat_objective_difficulty(
            objective,
            states,
            character,
        )

    def current_campaign_objective(
        self,
        objectives,
    ) -> v25.ProfessionalQuestObjective | None:
        active_key = str(
            self.campaign.get("active_key") or ""
        )

        if not active_key:
            return None

        for objective in objectives:
            if self.objective_key(objective) == active_key:
                return objective

        return None

    def should_preempt_for_daily(
        self,
        current: v25.ProfessionalQuestObjective,
        objectives,
        states,
        character: dict[str, Any],
    ) -> v25.ProfessionalQuestObjective | None:
        if current.quest_type == "daily":
            return None

        daily = [
            row
            for row in objectives
            if row.quest_type == "daily"
        ]
        if not daily:
            return None

        daily.sort(
            key=lambda row: self.objective_difficulty(
                row,
                states,
                character,
            )
        )
        return daily[0]

    def set_campaign(
        self,
        objective: v25.ProfessionalQuestObjective,
        reason: str,
    ) -> None:
        key = self.objective_key(objective)
        previous_key = str(
            self.campaign.get("active_key") or ""
        )

        if key == previous_key:
            self.campaign["active_remaining"] = (
                objective.remaining
            )
            self.save_campaign()
            return

        self.campaign.update(
            {
                "active_key": key,
                "active_quest_id": objective.quest_id,
                "active_quest_code": objective.quest_code,
                "active_quest_name": objective.quest_name,
                "active_quest_type": objective.quest_type,
                "active_objective_type": (
                    objective.objective_type
                ),
                "active_target": objective.target,
                "active_zone_id": objective.zone_id,
                "active_zone_code": objective.zone_code,
                "active_remaining": objective.remaining,
                "mode": "prepare",
                "prepared_key": "",
                "prepared_level": 0,
                "campaign_number": (
                    as_int(
                        self.campaign.get(
                            "campaign_number"
                        ),
                        0,
                    )
                    + 1
                ),
                "same_monster_wins": 0,
                "last_monster_id": None,
                "last_status": "",
            }
        )
        self.save_campaign()

        self.logger.info(
            "[QUEST CAMPAIGN %s] %s | %s remaining | %s.",
            self.campaign["campaign_number"],
            self.objective_name(objective),
            objective.remaining,
            reason,
        )

    def clear_completed_campaign(self) -> None:
        if not self.campaign.get("active_key"):
            return

        name = str(
            self.campaign.get("active_quest_name")
            or "Quest"
        )
        self.campaign["completed_campaigns"] = (
            as_int(
                self.campaign.get(
                    "completed_campaigns"
                ),
                0,
            )
            + 1
        )
        self.campaign.update(
            {
                "active_key": "",
                "active_quest_id": None,
                "active_quest_code": "",
                "active_quest_name": "",
                "active_quest_type": "",
                "active_objective_type": "",
                "active_target": "",
                "active_zone_id": None,
                "active_zone_code": "",
                "active_remaining": 0,
                "mode": "idle",
                "prepared_key": "",
                "prepared_level": 0,
                "same_monster_wins": 0,
                "last_monster_id": None,
                "last_status": "",
            }
        )
        self.save_campaign()

        self.logger.info(
            "[QUEST CAMPAIGN] Objective finished: %s | "
            "claim check runs immediately.",
            name,
        )

    def choose_campaign_objective(
        self,
        objectives,
        states,
        character: dict[str, Any],
    ) -> v25.ProfessionalQuestObjective | None:
        supported = self.supported_campaign_objectives(
            objectives
        )
        if not supported:
            self.clear_completed_campaign()
            return None

        current = self.current_campaign_objective(
            supported
        )

        if current is None:
            if self.campaign.get("active_key"):
                self.clear_completed_campaign()

            supported.sort(
                key=lambda row: self.objective_difficulty(
                    row,
                    states,
                    character,
                )
            )
            selected = supported[0]
            self.set_campaign(
                selected,
                "selected as the simplest current Quest",
            )
            return selected

        daily = self.should_preempt_for_daily(
            current,
            supported,
            states,
            character,
        )
        if daily is not None:
            self.set_campaign(
                daily,
                "Daily Quest preempted a non-Daily Quest",
            )
            return daily

        self.campaign["active_remaining"] = (
            current.remaining
        )
        self.save_campaign()
        return current

    def objective_is_broad(
        self,
        objective: v25.ProfessionalQuestObjective,
        rows,
    ) -> bool:
        target = normalize(objective.target)

        if target in {"", "any"}:
            return True

        monster_ids = {
            as_int(
                row["candidate"].monster.get("id"),
                0,
            )
            for row in rows
        }
        return len(monster_ids) > 1

    def select_target_row(
        self,
        objective: v25.ProfessionalQuestObjective,
        rows,
    ):
        if not rows:
            return None

        broad = self.objective_is_broad(
            objective,
            rows,
        )
        risk_ceiling = float(
            self.config["quest_campaign"][
                "broad_target_max_risk_ratio"
            ]
        )

        ready = [
            row
            for row in rows
            if row.get("state") == "ready"
        ]

        if ready:
            if broad:
                safe = [
                    row
                    for row in ready
                    if as_float(
                        row.get("risk_ratio"),
                        999.0,
                    )
                    <= risk_ceiling
                ]
                pool = safe or ready
                pool.sort(
                    key=lambda row: (
                        -as_int(
                            row["candidate"].monster.get(
                                "level"
                            ),
                            0,
                        ),
                        -row["candidate"].xp_per_stamina,
                        -as_int(
                            getattr(
                                row["candidate"],
                                "quest_overlap",
                                0,
                            ),
                            0,
                        ),
                        -row["candidate"].gold_per_stamina,
                        row.get("risk_ratio", 999.0),
                    )
                )
                return pool[0]

            ready.sort(
                key=lambda row: (
                    row.get("risk_ratio", 999.0),
                    -row["candidate"].xp_per_stamina,
                    -row["candidate"].gold_per_stamina,
                )
            )
            return ready[0]

        beatable = [
            row
            for row in rows
            if row.get("state")
            in {"heal", "resource"}
        ]

        if beatable:
            if broad:
                safe = [
                    row
                    for row in beatable
                    if as_float(
                        row.get("risk_ratio"),
                        999.0,
                    )
                    <= risk_ceiling
                ]
                pool = safe or beatable
                pool.sort(
                    key=lambda row: (
                        -as_int(
                            row["candidate"].monster.get(
                                "level"
                            ),
                            0,
                        ),
                        row.get("hp_short", 0),
                        -row["candidate"].xp_per_stamina,
                    )
                )
                return pool[0]

            beatable.sort(
                key=lambda row: (
                    row.get("hp_short", 0)
                    + row.get("stamina_short", 0) * 10,
                    row.get("risk_ratio", 999.0),
                )
            )
            return beatable[0]

        rows.sort(
            key=lambda row: (
                row.get("risk_ratio", 999.0),
                as_int(
                    row["candidate"].monster.get("level"),
                    0,
                ),
            )
        )
        return rows[0]

    def prepare_campaign_once(
        self,
        objective: v25.ProfessionalQuestObjective,
        character: dict[str, Any],
    ) -> bool:
        key = self.objective_key(objective)
        level = as_int(character.get("level"), 1)

        prepared = bool(
            self.campaign.get("prepared_key") == key
            and as_int(
                self.campaign.get("prepared_level"),
                0,
            )
            >= level
        )

        if prepared:
            return False

        self.logger.info(
            "[QUEST PREP] %s | optimizing Skills, equipment, "
            "attributes and Forge before combat.",
            objective.quest_name,
        )

        self.safe_step(
            "Campaign Skills",
            self.optimize_skills,
        )
        self.safe_step(
            "Campaign Skill Tree",
            self.optimize_skill_tree,
        )
        self.safe_step(
            "Campaign Equipment",
            self.optimize_progression,
        )

        self.campaign["prepared_key"] = key
        self.campaign["prepared_level"] = level
        self.campaign["mode"] = "ready-check"
        self.save_campaign()
        return True

    def profile_for_campaign(
        self,
        objective: v25.ProfessionalQuestObjective,
    ) -> dict[str, Any] | None:
        target = normalize(objective.target)

        profiles = self.active_profiles()
        if not profiles:
            return None

        for profile in profiles:
            if normalize(
                profile.get("monster_name")
            ) == target:
                return profile

        return profiles[0]

    def strongest_safe_training_row(
        self,
        states,
        character: dict[str, Any],
        excluded_ids: set[int],
    ):
        player_level = as_int(
            character.get("level"),
            1,
        )
        max_risk = float(
            self.config["quest_campaign"][
                "training_max_risk_ratio"
            ]
        )

        ready = [
            row
            for row in states
            if row.get("state") == "ready"
            and as_int(
                row["candidate"].monster.get("id"),
                0,
            )
            not in excluded_ids
            and not self.is_boss(
                row["candidate"].monster
            )
            and as_int(
                row["candidate"].monster.get("level"),
                0,
            )
            <= player_level
            and as_float(
                row.get("risk_ratio"),
                999.0,
            )
            <= max_risk
        ]

        if ready:
            ready.sort(
                key=lambda row: (
                    -as_int(
                        row["candidate"].monster.get("level"),
                        0,
                    ),
                    -row["candidate"].xp_per_stamina,
                    -as_int(
                        getattr(
                            row["candidate"],
                            "quest_overlap",
                            0,
                        ),
                        0,
                    ),
                    -row["candidate"].gold_per_stamina,
                    row.get("risk_ratio", 999.0),
                )
            )
            return ready[0]

        beatable = [
            row
            for row in states
            if row.get("state")
            in {"heal", "resource"}
            and as_int(
                row["candidate"].monster.get("id"),
                0,
            )
            not in excluded_ids
            and not self.is_boss(
                row["candidate"].monster
            )
            and as_int(
                row["candidate"].monster.get("level"),
                0,
            )
            <= player_level
            and as_float(
                row.get("risk_ratio"),
                999.0,
            )
            <= max_risk
        ]

        if beatable:
            beatable.sort(
                key=lambda row: (
                    -as_int(
                        row["candidate"].monster.get("level"),
                        0,
                    ),
                    row.get("hp_short", 0),
                    -row["candidate"].xp_per_stamina,
                )
            )
            return beatable[0]

        return None

    def training_row(
        self,
        objective: v25.ProfessionalQuestObjective,
        objective_rows,
        states,
        character: dict[str, Any],
    ):
        excluded_ids = {
            as_int(
                row["candidate"].monster.get("id"),
                0,
            )
            for row in objective_rows
        }

        profile = self.profile_for_campaign(
            objective
        )

        if profile is not None:
            self.assign_prerequisite(
                profile,
                states,
                character,
            )
            prerequisite_id = as_int(
                profile.get("prerequisite_id"),
                0,
            )
            prerequisite = self.candidate_state_by_id(
                states,
                prerequisite_id,
            )

            if (
                prerequisite is not None
                and prerequisite.get("state")
                in {"ready", "heal", "resource"}
            ):
                return prerequisite

        return self.strongest_safe_training_row(
            states,
            character,
            excluded_ids,
        )

    def material_training_row(
        self,
        states,
        character: dict[str, Any],
    ):
        rows = [
            row
            for row in states
            if row.get("state")
            in {"ready", "heal", "resource"}
            and as_float(
                row["candidate"].material_score,
                0.0,
            )
            > 0
            and not self.is_boss(
                row["candidate"].monster
            )
        ]

        if not rows:
            return self.strongest_safe_training_row(
                states,
                character,
                set(),
            )

        rows.sort(
            key=lambda row: (
                row.get("state") != "ready",
                -row["candidate"].material_score,
                -as_int(
                    row["candidate"].monster.get("level"),
                    0,
                ),
                -row["candidate"].xp_per_stamina,
                row.get("risk_ratio", 999.0),
            )
        )
        return rows[0]

    def choose_no_quest_progression(
        self,
        states,
        character: dict[str, Any],
    ):
        self.campaign["mode"] = "progression"
        self.save_campaign()

        row = self.strongest_safe_training_row(
            states,
            character,
            set(),
        )
        return row

    # This fully replaces the overlap-only selector from V2.5.
    def choose_action(
        self,
        character: dict[str, Any],
        objectives,
        material_needs,
    ):
        self._scheduler_character = character
        self._campaign_pending = None

        candidates = self.build_farm_candidates(
            character,
            objectives,
            material_needs,
        )
        states = [
            self.combat_assessment(
                candidate,
                character,
            )
            for candidate in candidates
        ]

        for profile in self.active_profiles():
            self.assign_prerequisite(
                profile,
                states,
                character,
            )

        if self.update_stamina_bank(
            character,
            states,
        ):
            self._campaign_active = True
            return None, states

        campaign_objective = (
            self.choose_campaign_objective(
                objectives,
                states,
                character,
            )
        )
        self._campaign_active = (
            campaign_objective is not None
        )

        if campaign_objective is None:
            selected = self.choose_no_quest_progression(
                states,
                character,
            )
            if (
                selected is not None
                and selected.get("state")
                in {"heal", "resource"}
            ):
                self._campaign_pending = selected
                return None, states
            return selected, states

        if campaign_objective.objective_type == "craft":
            self.campaign["mode"] = "craft-materials"
            self.save_campaign()

            selected = self.material_training_row(
                states,
                character,
            )
            if selected is None:
                return None, states

            if selected.get("state") in {
                "heal",
                "resource",
            }:
                self._campaign_pending = selected
                return None, states

            if self.prepare_campaign_once(
                campaign_objective,
                character,
            ):
                return None, states

            return selected, states

        objective_rows = self.matching_rows(
            campaign_objective,
            states,
        )
        selected = self.select_target_row(
            campaign_objective,
            objective_rows,
        )

        if selected is not None:
            if selected.get("state") == "ready":
                if self.prepare_campaign_once(
                    campaign_objective,
                    character,
                ):
                    return None, states

                self.campaign["mode"] = "quest-combat"
                self.save_campaign()
                return selected, states

            if selected.get("state") in {
                "heal",
                "resource",
            }:
                self.campaign["mode"] = "quest-prepare"
                self.save_campaign()
                self._campaign_pending = selected
                return None, states

        training = self.training_row(
            campaign_objective,
            objective_rows,
            states,
            character,
        )

        if training is not None:
            self.campaign["mode"] = "strength-training"
            self.save_campaign()

            if training.get("state") in {
                "heal",
                "resource",
            }:
                self._campaign_pending = training
                return None, states

            return training, states

        self.campaign["mode"] = "blocked"
        self.save_campaign()
        return None, states

    def pending_quest(self, states):
        if (
            isinstance(self._campaign_pending, dict)
            and self._campaign_pending.get("state")
            in {"heal", "resource"}
        ):
            return self._campaign_pending

        return super().pending_quest(states)

    def active_world_boss(self, objectives):
        if self._campaign_active:
            return None
        return super().active_world_boss(objectives)

    def run_dungeon_autopilot(
        self,
        has_urgent_quests: bool,
    ) -> bool:
        if self._campaign_active:
            return False
        return super().run_dungeon_autopilot(
            has_urgent_quests=has_urgent_quests,
        )

    def execute_fight(self, candidate) -> bool:
        monster_id = as_int(
            candidate.monster.get("id"),
            0,
        )
        result = super().execute_fight(candidate)

        if result:
            if (
                as_int(
                    self.campaign.get(
                        "last_monster_id"
                    ),
                    0,
                )
                == monster_id
            ):
                self.campaign[
                    "same_monster_wins"
                ] = (
                    as_int(
                        self.campaign.get(
                            "same_monster_wins"
                        ),
                        0,
                    )
                    + 1
                )
            else:
                self.campaign[
                    "last_monster_id"
                ] = monster_id
                self.campaign[
                    "same_monster_wins"
                ] = 1

            self.campaign[
                "active_remaining"
            ] = max(
                0,
                as_int(
                    self.campaign.get(
                        "active_remaining"
                    ),
                    0,
                )
                - 1,
            )
            self.save_campaign()

        else:
            self.campaign["mode"] = (
                "strength-training"
            )
            self.campaign["prepared_key"] = ""
            self.save_campaign()

        return result

    def log_scheduler_status(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        if self.campaign.get("active_key"):
            message = (
                f"{self.campaign.get('active_quest_name')} | "
                f"mode {self.campaign.get('mode')} | "
                f"remaining {self.campaign.get('active_remaining')}"
            )

            if (
                self.campaign.get("last_status")
                != message
            ):
                self.campaign["last_status"] = message
                self.save_campaign()
                self.logger.info(
                    "[QUEST STATUS] %s",
                    message,
                )

        super().log_scheduler_status(
            pending,
            character,
        )

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "quest_campaign_state": self.campaign,
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_6_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_6_final_"
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
        bot = QuestCampaignEngine(
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
