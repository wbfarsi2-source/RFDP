from __future__ import annotations

import importlib.util
import math
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V232_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_base.py"
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_4_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_4_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (
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
    "eldoria_v232_base",
    V232_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.3.2 base could not be loaded.")

v232 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v232
spec.loader.exec_module(v232)

v22 = v232.v22
v21 = v232.v21
v161 = v232.v161
base = v232.base
engine = v232.engine

for module in (v232, v22, v21, v161, base, engine):
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
        OUTPUT_DIR / "eldoria_bot_v2_4_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_4_final.log"
    )

for module in (v232, v22, v21, v161, base):
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


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_4_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_4_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_4_final.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class AdaptiveTierTrainer(v232.StaminaBankScheduler):
    VERSION = "2.4-final-adaptive-tier-trainer-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.adaptive_file = (
            STATE_DIR / "adaptive_tier_training_state.json"
        )
        self.adaptive = engine.load_json(
            self.adaptive_file,
            {
                "schema_version": 0,
                "profiles": {},
                "promotion_gate": None,
                "last_training_log": "",
                "breakthroughs": 0,
                "mastery_wins": 0,
            },
        )

        if not isinstance(
            self.adaptive.get("profiles"),
            dict,
        ):
            self.adaptive["profiles"] = {}

        self.migrate_legacy_death_locks()
        self.adaptive["schema_version"] = 1
        self.save_adaptive()

    def save_adaptive(self) -> None:
        engine.save_json(
            self.adaptive_file,
            self.adaptive,
        )

    @staticmethod
    def name_of(monster: dict[str, Any]) -> str:
        return str(
            monster.get("name_en")
            or monster.get("name")
            or monster.get("code")
            or monster.get("id")
        )

    def current_power(
        self,
        character: dict[str, Any],
    ) -> float:
        return float(self.combat_power_value(character))

    def profile_for(
        self,
        monster_id: int,
    ) -> dict[str, Any] | None:
        value = self.adaptive.setdefault(
            "profiles",
            {},
        ).get(str(monster_id))
        return value if isinstance(value, dict) else None

    def retry_value(
        self,
        key: str,
        failure_count: int,
    ):
        values = list(
            self.config["adaptive_retry"][key]
        )
        if not values:
            raise RuntimeError(
                f"adaptive_retry.{key} cannot be empty"
            )
        index = min(
            max(1, failure_count) - 1,
            len(values) - 1,
        )
        return values[index]

    def migrate_legacy_death_locks(self) -> None:
        profiles = self.adaptive.setdefault(
            "profiles",
            {},
        )
        old_locks = self.learning.get(
            "death_locks",
            {},
        )

        if not isinstance(old_locks, dict):
            return

        changed = False

        for monster_id, old in old_locks.items():
            if (
                monster_id in profiles
                or not isinstance(old, dict)
            ):
                continue

            failures = max(
                1,
                as_int(old.get("deaths"), 1),
            )
            level_at_death = max(
                1,
                as_int(old.get("level_at_death"), 1),
            )
            power_at_death = max(
                1.0,
                as_float(old.get("power_at_death"), 1.0),
            )
            level_step = int(
                self.retry_value(
                    "level_steps",
                    failures,
                )
            )
            power_growth = float(
                self.retry_value(
                    "power_growth_ratios",
                    failures,
                )
            )

            profiles[str(monster_id)] = {
                "monster_id": as_int(monster_id),
                "monster_name": (
                    old.get("monster_name")
                    or monster_id
                ),
                "monster_level": 0,
                "failures": failures,
                "last_failure_at": (
                    old.get("recorded_at")
                    or utc_now()
                ),
                "attempt_level": level_at_death,
                "attempt_power": power_at_death,
                "attempt_hp_max": as_int(
                    old.get("hp_max_at_death"),
                    1,
                ),
                "damage_taken": as_int(
                    old.get("damage_taken"),
                    0,
                ),
                "retry_level": (
                    level_at_death + level_step
                ),
                "retry_power": math.ceil(
                    power_at_death
                    * (1.0 + power_growth)
                ),
                "level_step": level_step,
                "power_growth_ratio": power_growth,
                "mastery_required_wins": int(
                    self.retry_value(
                        "mastery_wins",
                        failures,
                    )
                ),
                "mastery_max_average_loss_ratio": float(
                    self.retry_value(
                        "mastery_max_average_loss_ratios",
                        failures,
                    )
                ),
                "mastery_required_high_hp_wins": int(
                    self.retry_value(
                        "mastery_high_hp_wins",
                        failures,
                    )
                ),
                "prerequisite_id": None,
                "prerequisite_name": "",
                "prerequisite_level": 0,
                "mastery": {
                    "wins": 0,
                    "consecutive_wins": 0,
                    "damage_ratio_sum": 0.0,
                    "high_hp_wins": 0,
                },
                "focus": "balanced",
                "recommended_stats": [
                    "strength",
                    "vitality",
                    "defense",
                ],
                "retry_ready_announced": False,
            }
            changed = True

        # Old OR-based locks must not remain authoritative.
        if old_locks:
            self.learning["death_locks"] = {}
            self.save_learning()
            changed = True

        if changed:
            self.save_adaptive()

    def diagnose_failure(
        self,
        monster: dict[str, Any],
        character: dict[str, Any],
        damage_taken: int,
    ) -> tuple[str, list[str]]:
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        player_attack = max(
            1.0,
            as_float(
                engine.deep_find_number(
                    character,
                    {
                        "attack",
                        "atk",
                        "total_attack",
                        "physical_attack",
                    },
                ),
                1.0,
            ),
        )
        player_defense = max(
            0.0,
            as_float(
                engine.deep_find_number(
                    character,
                    {
                        "defense",
                        "def",
                        "total_defense",
                        "armor",
                    },
                ),
                0.0,
            ),
        )
        enemy_hp = max(
            1.0,
            as_float(
                engine.deep_find_number(
                    monster,
                    {
                        "hp",
                        "max_hp",
                        "health",
                    },
                ),
                1.0,
            ),
        )
        enemy_attack = max(
            0.0,
            as_float(
                engine.deep_find_number(
                    monster,
                    {
                        "attack",
                        "atk",
                        "damage",
                    },
                ),
                0.0,
            ),
        )
        enemy_defense = max(
            0.0,
            as_float(
                engine.deep_find_number(
                    monster,
                    {
                        "defense",
                        "def",
                        "armor",
                    },
                ),
                0.0,
            ),
        )

        survival_pressure = max(
            damage_taken / hp_max,
            enemy_attack / max(1.0, player_defense + 5.0),
        )
        offense_pressure = max(
            enemy_hp / max(1.0, player_attack * 4.0),
            enemy_defense / max(1.0, player_attack),
        )

        if (
            survival_pressure
            >= float(
                self.config["adaptive_retry"][
                    "survival_focus_threshold"
                ]
            )
            and survival_pressure
            > offense_pressure * 1.10
        ):
            return (
                "survival",
                [
                    "vitality",
                    "defense",
                    "resistance",
                    "hp",
                    "shield",
                ],
            )

        if (
            offense_pressure
            >= float(
                self.config["adaptive_retry"][
                    "offense_focus_threshold"
                ]
            )
            and offense_pressure
            > survival_pressure * 1.10
        ):
            return (
                "offense",
                [
                    "strength",
                    "attack",
                    "skill_damage",
                    "critical",
                ],
            )

        return (
            "balanced",
            [
                "strength",
                "vitality",
                "defense",
                "resistance",
            ],
        )

    # ----------------------------------------------------------
    # Failure policy:
    # 1st defeat: +2 levels, +15% power, 10 mastery wins.
    # 2nd defeat: +4 levels, +30% power, 15 mastery wins.
    # Then +6/+8 levels and +45%/+60% power.
    # All requirements are AND conditions, not OR conditions.
    # ----------------------------------------------------------

    def record_death_learning(
        self,
        monster: dict[str, Any],
        character_before: dict[str, Any],
        damage_taken: int,
    ) -> None:
        monster_id = as_int(monster.get("id"))
        if monster_id <= 0:
            return

        previous = self.profile_for(monster_id)
        failures = (
            as_int(previous.get("failures"), 0)
            if previous
            else 0
        ) + 1

        level = max(
            1,
            as_int(character_before.get("level"), 1),
        )
        power = max(
            1.0,
            self.current_power(character_before),
        )
        hp_max = max(
            1,
            as_int(character_before.get("hp_max"), 1),
        )
        monster_level = max(
            0,
            as_int(monster.get("level"), 0),
        )

        level_step = int(
            self.retry_value(
                "level_steps",
                failures,
            )
        )
        power_growth = float(
            self.retry_value(
                "power_growth_ratios",
                failures,
            )
        )
        mastery_wins = int(
            self.retry_value(
                "mastery_wins",
                failures,
            )
        )
        max_average_loss = float(
            self.retry_value(
                "mastery_max_average_loss_ratios",
                failures,
            )
        )
        high_hp_wins = int(
            self.retry_value(
                "mastery_high_hp_wins",
                failures,
            )
        )
        focus, recommended = self.diagnose_failure(
            monster,
            character_before,
            damage_taken,
        )

        profile = {
            "monster_id": monster_id,
            "monster_name": self.name_of(monster),
            "monster_level": monster_level,
            "failures": failures,
            "last_failure_at": utc_now(),
            "attempt_level": level,
            "attempt_power": power,
            "attempt_hp_max": hp_max,
            "damage_taken": max(
                damage_taken,
                hp_max,
            ),
            "retry_level": level + level_step,
            "retry_power": math.ceil(
                power * (1.0 + power_growth)
            ),
            "level_step": level_step,
            "power_growth_ratio": power_growth,
            "mastery_required_wins": mastery_wins,
            "mastery_max_average_loss_ratio": max_average_loss,
            "mastery_required_high_hp_wins": high_hp_wins,
            "prerequisite_id": None,
            "prerequisite_name": "",
            "prerequisite_level": 0,
            "mastery": {
                "wins": 0,
                "consecutive_wins": 0,
                "damage_ratio_sum": 0.0,
                "high_hp_wins": 0,
            },
            "focus": focus,
            "recommended_stats": recommended,
            "retry_ready_announced": False,
        }

        self.adaptive.setdefault(
            "profiles",
            {},
        )[str(monster_id)] = profile
        self.adaptive["promotion_gate"] = None
        self.save_adaptive()

        self.logger.info(
            "[DEFEAT PLAN] %s | failure %s | retry at LV %s "
            "+ Power %s + %s mastery wins | focus: %s.",
            profile["monster_name"],
            failures,
            profile["retry_level"],
            profile["retry_power"],
            mastery_wins,
            focus,
        )

    def mastery_metrics(
        self,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        mastery = profile.get("mastery")
        if not isinstance(mastery, dict):
            mastery = {}

        wins = max(0, as_int(mastery.get("wins"), 0))
        consecutive = max(
            0,
            as_int(mastery.get("consecutive_wins"), 0),
        )
        ratio_sum = max(
            0.0,
            as_float(mastery.get("damage_ratio_sum"), 0.0),
        )
        high_hp_wins = max(
            0,
            as_int(mastery.get("high_hp_wins"), 0),
        )
        average_loss = (
            ratio_sum / wins
            if wins > 0
            else 999.0
        )

        required = max(
            0,
            as_int(
                profile.get("mastery_required_wins"),
                0,
            ),
        )
        required_high = max(
            0,
            as_int(
                profile.get(
                    "mastery_required_high_hp_wins"
                ),
                0,
            ),
        )
        max_loss = float(
            profile.get(
                "mastery_max_average_loss_ratio",
                1.0,
            )
        )

        complete = bool(
            profile.get("prerequisite_id") is not None
            and wins >= required
            and consecutive >= required
            and high_hp_wins >= required_high
            and average_loss <= max_loss
        )

        return {
            "wins": wins,
            "consecutive": consecutive,
            "average_loss_ratio": average_loss,
            "high_hp_wins": high_hp_wins,
            "required_wins": required,
            "required_high_hp_wins": required_high,
            "max_average_loss_ratio": max_loss,
            "complete": complete,
        }

    def retry_readiness(
        self,
        profile: dict[str, Any],
        character: dict[str, Any],
    ) -> dict[str, Any]:
        level = as_int(character.get("level"), 1)
        power = self.current_power(character)
        mastery = self.mastery_metrics(profile)

        return {
            "level_ok": (
                level
                >= as_int(
                    profile.get("retry_level"),
                    10**9,
                )
            ),
            "power_ok": (
                power
                >= as_float(
                    profile.get("retry_power"),
                    float("inf"),
                )
            ),
            "mastery_ok": mastery["complete"],
            "mastery": mastery,
            "level": level,
            "power": power,
        }

    def death_lock_active(
        self,
        monster: dict[str, Any],
        character: dict[str, Any],
    ) -> bool:
        monster_id = as_int(monster.get("id"))
        profile = self.profile_for(monster_id)
        if profile is None:
            return False

        readiness = self.retry_readiness(
            profile,
            character,
        )
        ready = bool(
            readiness["level_ok"]
            and readiness["power_ok"]
            and readiness["mastery_ok"]
        )

        if ready:
            if not profile.get("retry_ready_announced"):
                profile["retry_ready_announced"] = True
                self.save_adaptive()
                self.logger.info(
                    "[RETRY READY] %s | LV %s | Power %.0f | "
                    "mastery %s/%s.",
                    profile["monster_name"],
                    readiness["level"],
                    readiness["power"],
                    readiness["mastery"]["wins"],
                    readiness["mastery"]["required_wins"],
                )
            return False

        return True

    # ----------------------------------------------------------
    # Choose and master the closest safe enemy below the failed tier.
    # ----------------------------------------------------------

    def assign_prerequisite(
        self,
        profile: dict[str, Any],
        states,
        character: dict[str, Any],
    ) -> None:
        current_id = profile.get("prerequisite_id")

        available_ids = {
            as_int(
                row["candidate"].monster.get("id")
            )
            for row in states
            if row.get("state")
            in {"ready", "heal", "resource"}
        }

        if (
            current_id is not None
            and as_int(current_id) in available_ids
        ):
            return

        failed_level = max(
            0,
            as_int(profile.get("monster_level"), 0),
        )
        player_level = max(
            1,
            as_int(character.get("level"), 1),
        )
        failed_id = as_int(profile.get("monster_id"))

        choices = []

        for row in states:
            if row.get("state") not in {
                "ready",
                "heal",
                "resource",
            }:
                continue

            candidate = row["candidate"]
            monster = candidate.monster
            monster_id = as_int(monster.get("id"))
            monster_level = max(
                0,
                as_int(monster.get("level"), 0),
            )

            if monster_id <= 0 or monster_id == failed_id:
                continue
            if self.is_boss(monster):
                continue

            ceiling = (
                failed_level - 1
                if failed_level > 0
                else player_level
            )
            if monster_level > ceiling:
                continue

            proven = (
                self.successful_damage_estimate(
                    monster_id
                )
                is not None
            )

            choices.append(
                (
                    row,
                    monster_level,
                    proven,
                )
            )

        if not choices:
            return

        choices.sort(
            key=lambda item: (
                -item[1],
                not item[2],
                item[0].get("risk_ratio", 999.0),
                -item[0]["candidate"].xp_per_stamina,
                -item[0]["candidate"].gold_per_stamina,
            )
        )

        row, level, _ = choices[0]
        candidate = row["candidate"]
        monster = candidate.monster

        profile["prerequisite_id"] = as_int(
            monster.get("id")
        )
        profile["prerequisite_name"] = self.name_of(
            monster
        )
        profile["prerequisite_level"] = level
        profile["mastery"] = {
            "wins": 0,
            "consecutive_wins": 0,
            "damage_ratio_sum": 0.0,
            "high_hp_wins": 0,
        }
        profile["retry_ready_announced"] = False
        self.save_adaptive()

        self.logger.info(
            "[TRAINING] %s selected before retrying %s | "
            "need %s clean consecutive wins.",
            profile["prerequisite_name"],
            profile["monster_name"],
            profile["mastery_required_wins"],
        )

    def active_profiles(self):
        profiles = self.adaptive.get(
            "profiles",
            {},
        )
        if not isinstance(profiles, dict):
            return []

        values = [
            row
            for row in profiles.values()
            if isinstance(row, dict)
        ]
        values.sort(
            key=lambda row: (
                -as_int(row.get("failures"), 0),
                -as_int(row.get("monster_level"), 0),
                as_int(row.get("retry_level"), 10**9),
            )
        )
        return values

    def active_training_focus(self) -> str:
        profiles = self.active_profiles()
        if not profiles:
            return "balanced"
        return str(
            profiles[0].get("focus")
            or "balanced"
        )

    def candidate_state_by_id(
        self,
        states,
        monster_id: int,
    ):
        for row in states:
            if (
                as_int(
                    row["candidate"].monster.get("id")
                )
                == monster_id
            ):
                return row
        return None

    def promotion_gate_active(
        self,
        character: dict[str, Any],
    ) -> bool:
        gate = self.adaptive.get("promotion_gate")
        if not isinstance(gate, dict):
            return False

        level = as_int(character.get("level"), 1)
        power = self.current_power(character)

        ready = bool(
            level >= as_int(
                gate.get("unlock_level"),
                10**9,
            )
            and power >= as_float(
                gate.get("unlock_power"),
                float("inf"),
            )
        )

        if ready:
            self.logger.info(
                "[TIER READY] Harder enemies unlocked after "
                "the required post-victory growth."
            )
            self.adaptive["promotion_gate"] = None
            self.save_adaptive()
            return False

        return True

    def combat_assessment(
        self,
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        row = super().combat_assessment(
            candidate,
            character,
        )

        gate = self.adaptive.get("promotion_gate")
        if (
            isinstance(gate, dict)
            and self.promotion_gate_active(character)
        ):
            monster = candidate.monster
            monster_level = as_int(
                monster.get("level"),
                0,
            )
            predicted = as_float(
                candidate.predicted_damage,
                0.0,
            )
            anchor_level = as_int(
                gate.get("anchor_monster_level"),
                0,
            )
            anchor_damage = max(
                1.0,
                as_float(
                    gate.get("anchor_predicted_damage"),
                    1.0,
                ),
            )

            harder = bool(
                monster_level > anchor_level
                or predicted
                > anchor_damage
                * float(
                    self.config["adaptive_retry"][
                        "harder_damage_multiplier"
                    ]
                )
            )

            if harder:
                hp_max = max(
                    1,
                    as_int(character.get("hp_max"), 1),
                )
                row = dict(row)
                row.update(
                    {
                        "state": "strengthen",
                        "reason": (
                            "post-victory +2 Level growth "
                            "is not complete"
                        ),
                        "required_hp": hp_max + 1,
                        "hp_short": 0,
                        "stamina_short": 0,
                        "actionable": False,
                    }
                )

        return row

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

        for profile in self.active_profiles():
            self.assign_prerequisite(
                profile,
                states,
                character,
            )

        if self.stamina_bank.get("recharging"):
            return selected, states

        # Never displace a ready exact Quest that is not locked.
        if (
            selected is not None
            and selected.get("quest_exact")
        ):
            return selected, states

        profiles = self.active_profiles()
        if not profiles:
            return selected, states

        # First finish mastery for the most important failed enemy.
        for profile in profiles:
            readiness = self.retry_readiness(
                profile,
                character,
            )
            if readiness["mastery_ok"]:
                continue

            prerequisite_id = as_int(
                profile.get("prerequisite_id"),
                0,
            )
            training = self.candidate_state_by_id(
                states,
                prerequisite_id,
            )
            if (
                training is not None
                and training.get("state") == "ready"
            ):
                return training, states

        # Mastery is done but Level/Power is still missing:
        # favor safe XP and useful Gold rather than random material fights.
        incomplete_growth = [
            profile
            for profile in profiles
            if not (
                self.retry_readiness(
                    profile,
                    character,
                )["level_ok"]
                and self.retry_readiness(
                    profile,
                    character,
                )["power_ok"]
            )
        ]

        if incomplete_growth:
            ready_safe = [
                row
                for row in states
                if row.get("state") == "ready"
                and not self.is_boss(
                    row["candidate"].monster
                )
            ]

            if ready_safe:
                ready_safe.sort(
                    key=lambda row: -(
                        row["candidate"].xp_per_stamina
                        * float(
                            self.config["adaptive_retry"][
                                "training_xp_weight"
                            ]
                        )
                        + row["candidate"].gold_per_stamina
                        * float(
                            self.config["adaptive_retry"][
                                "training_gold_weight"
                            ]
                        )
                        - row.get("risk_ratio", 999.0)
                        * float(
                            self.config["adaptive_retry"][
                                "training_risk_penalty"
                            ]
                        )
                    )
                )
                return ready_safe[0], states

        return selected, states

    # ----------------------------------------------------------
    # Targeted upgrades based on the most important active failure.
    # ----------------------------------------------------------

    def attribute_order(self, character) -> list[str]:
        race = str(
            character.get("race", "")
        ).lower()
        defensive = (
            "resistance"
            if race == "drakkar"
            else "agility"
        )
        focus = self.active_training_focus()

        if focus == "survival":
            return [
                "vitality",
                defensive,
                "vitality",
                "strength",
            ]
        if focus == "offense":
            return [
                "strength",
                "strength",
                "vitality",
                defensive,
            ]
        return [
            "strength",
            "vitality",
            defensive,
        ]

    def allocate_attributes(self) -> None:
        if not self.config["progression"][
            "auto_allocate_attributes"
        ]:
            return

        character = self.get_character()
        points = as_int(
            character.get("attribute_points"),
            0,
        )
        if points <= 0:
            return

        stat_order = self.attribute_order(character)
        cached_schema = self.runtime.get(
            "attribute_schema"
        )
        schemas = [
            lambda stat: {stat: 1},
            lambda stat: {
                "attribute": stat,
                "points": 1,
            },
            lambda stat: {
                "stat": stat,
                "points": 1,
            },
            lambda stat: {"attribute": stat},
        ]

        if (
            isinstance(cached_schema, int)
            and 0 <= cached_schema < len(schemas)
        ):
            schema_indexes = [cached_schema]
        else:
            schema_indexes = list(
                range(len(schemas))
            )

        spent = 0

        while points > 0:
            stat = stat_order[
                spent % len(stat_order)
            ]
            accepted = False

            for schema_index in schema_indexes:
                result = self.client.post(
                    "character/allocate",
                    schemas[schema_index](stat),
                )

                if result.ok:
                    self.runtime[
                        "attribute_schema"
                    ] = schema_index
                    engine.save_json(
                        engine.RUNTIME_STATE_FILE,
                        self.runtime,
                    )
                    schema_indexes = [schema_index]
                    accepted = True
                    spent += 1
                    points -= 1
                    self.attribute_points_spent += 1
                    self.logger.info(
                        "[ATTR] +1 %s | training focus %s.",
                        stat,
                        self.active_training_focus(),
                    )
                    self.record(
                        "allocate_attribute",
                        True,
                        {
                            "stat": stat,
                            "schema": schema_index,
                            "response": result.data,
                        },
                    )
                    break

                if result.status not in {
                    400,
                    404,
                    422,
                }:
                    self.record(
                        "allocate_attribute",
                        False,
                        {
                            "stat": stat,
                            "status": result.status,
                            "error": result.error,
                        },
                    )
                    return

            if not accepted:
                self.logger.info(
                    "[ATTR] Server allocation format "
                    "was not recognized; skipped."
                )
                return

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

    def focus_weight_overrides(
        self,
    ) -> tuple[dict[str, float], dict[str, float]]:
        focus = self.active_training_focus()

        equipment = {}
        forge = {}

        if focus == "survival":
            equipment = {
                "bonus_defense": 10.0,
                "bonus_magic_def": 7.0,
                "bonus_hp": 0.80,
                "bonus_vitality": 10.0,
                "bonus_resistance": 7.0,
                "bonus_dodge": 6.0,
                "gold_generation": 1.25,
            }
            forge = {
                "def": 10.0,
                "hp": 0.85,
                "vit": 10.0,
                "mdef": 7.0,
                "dodge": 6.0,
            }
        elif focus == "offense":
            equipment = {
                "bonus_attack": 14.0,
                "bonus_spell_attack": 9.0,
                "bonus_strength": 12.0,
                "bonus_crit": 8.0,
                "gold_generation": 1.35,
            }
            forge = {
                "atk": 14.0,
                "str": 12.0,
                "agi": 5.0,
            }

        return equipment, forge

    def auto_equip_best(self) -> None:
        old_weights = deepcopy(
            engine.EQUIPMENT_WEIGHTS
        )
        equipment, _ = (
            self.focus_weight_overrides()
        )
        engine.EQUIPMENT_WEIGHTS.update(
            equipment
        )

        try:
            super().auto_equip_best()
        finally:
            engine.EQUIPMENT_WEIGHTS.clear()
            engine.EQUIPMENT_WEIGHTS.update(
                old_weights
            )

    def forge_best_stats(self) -> None:
        old_weights = deepcopy(
            engine.STAT_ROI_WEIGHTS
        )
        _, forge = self.focus_weight_overrides()
        engine.STAT_ROI_WEIGHTS.update(forge)

        try:
            super().forge_best_stats()
        finally:
            engine.STAT_ROI_WEIGHTS.clear()
            engine.STAT_ROI_WEIGHTS.update(
                old_weights
            )

    # ----------------------------------------------------------
    # Victory updates mastery. A breakthrough creates a +2 Level
    # and +10% Power gate before a harder tier can be attacked.
    # ----------------------------------------------------------

    def update_mastery_profiles(
        self,
        monster_id: int,
        hp_before: int,
        hp_after: int,
        hp_max: int,
    ) -> None:
        changed = False

        for profile in self.active_profiles():
            if (
                as_int(profile.get("prerequisite_id"))
                != monster_id
            ):
                continue

            mastery = profile.setdefault(
                "mastery",
                {},
            )
            loss_ratio = max(
                0.0,
                (hp_before - hp_after)
                / max(1, hp_max),
            )
            hp_remaining_ratio = (
                hp_after / max(1, hp_max)
            )

            mastery["wins"] = (
                as_int(mastery.get("wins"), 0)
                + 1
            )
            mastery["consecutive_wins"] = (
                as_int(
                    mastery.get(
                        "consecutive_wins"
                    ),
                    0,
                )
                + 1
            )
            mastery["damage_ratio_sum"] = (
                as_float(
                    mastery.get(
                        "damage_ratio_sum"
                    ),
                    0.0,
                )
                + loss_ratio
            )

            if hp_remaining_ratio >= float(
                self.config["adaptive_retry"][
                    "mastery_high_hp_remaining_ratio"
                ]
            ):
                mastery["high_hp_wins"] = (
                    as_int(
                        mastery.get(
                            "high_hp_wins"
                        ),
                        0,
                    )
                    + 1
                )

            self.adaptive["mastery_wins"] = (
                as_int(
                    self.adaptive.get(
                        "mastery_wins"
                    ),
                    0,
                )
                + 1
            )
            profile["retry_ready_announced"] = False
            changed = True

            metrics = self.mastery_metrics(profile)
            wins = metrics["wins"]

            if (
                metrics["complete"]
                or wins % int(
                    self.config["adaptive_retry"][
                        "mastery_progress_log_every"
                    ]
                )
                == 0
            ):
                self.logger.info(
                    "[MASTERY] %s for %s | wins %s/%s | "
                    "average HP loss %.0f%% | high-HP wins %s/%s.",
                    profile["prerequisite_name"],
                    profile["monster_name"],
                    wins,
                    metrics["required_wins"],
                    metrics["average_loss_ratio"] * 100,
                    metrics["high_hp_wins"],
                    metrics["required_high_hp_wins"],
                )

        if changed:
            self.save_adaptive()

    def reset_mastery_on_training_defeat(
        self,
        monster_id: int,
    ) -> None:
        changed = False

        for profile in self.active_profiles():
            if (
                as_int(profile.get("prerequisite_id"))
                != monster_id
            ):
                continue

            mastery = profile.setdefault(
                "mastery",
                {},
            )
            mastery["consecutive_wins"] = 0
            profile["retry_ready_announced"] = False
            changed = True

        if changed:
            self.save_adaptive()

    def execute_fight(self, candidate) -> bool:
        monster = candidate.monster
        monster_id = as_int(monster.get("id"))
        profile_before = self.profile_for(
            monster_id
        )

        before = self.get_character()
        hp_before = as_int(before.get("hp"))
        hp_max_before = max(
            1,
            as_int(before.get("hp_max"), 1),
        )
        power_before = self.current_power(before)

        result = super().execute_fight(candidate)

        after = self.get_character()
        hp_after = as_int(after.get("hp"))
        alive_after = self.is_alive(after)

        if result:
            self.update_mastery_profiles(
                monster_id,
                hp_before,
                hp_after,
                hp_max_before,
            )

            if profile_before is not None:
                profiles = self.adaptive.setdefault(
                    "profiles",
                    {},
                )
                profiles.pop(
                    str(monster_id),
                    None,
                )
                self.adaptive["breakthroughs"] = (
                    as_int(
                        self.adaptive.get(
                            "breakthroughs"
                        ),
                        0,
                    )
                    + 1
                )

                current_level = max(
                    1,
                    as_int(after.get("level"), 1),
                )
                current_power = max(
                    1.0,
                    self.current_power(after),
                )

                self.adaptive["promotion_gate"] = {
                    "anchor_monster_id": monster_id,
                    "anchor_monster_name": self.name_of(
                        monster
                    ),
                    "anchor_monster_level": as_int(
                        monster.get("level"),
                        current_level,
                    ),
                    "anchor_predicted_damage": max(
                        1.0,
                        as_float(
                            candidate.predicted_damage,
                            1.0,
                        ),
                    ),
                    "base_level": current_level,
                    "base_power": current_power,
                    "unlock_level": (
                        current_level
                        + int(
                            self.config[
                                "adaptive_retry"
                            ][
                                "post_victory_level_growth"
                            ]
                        )
                    ),
                    "unlock_power": math.ceil(
                        current_power
                        * (
                            1.0
                            + float(
                                self.config[
                                    "adaptive_retry"
                                ][
                                    "post_victory_power_growth_ratio"
                                ]
                            )
                        )
                    ),
                    "created_at": utc_now(),
                }
                self.save_adaptive()

                self.logger.info(
                    "[BREAKTHROUGH] %s defeated | harder tier waits "
                    "until LV %s and Power %s.",
                    self.name_of(monster),
                    self.adaptive[
                        "promotion_gate"
                    ]["unlock_level"],
                    self.adaptive[
                        "promotion_gate"
                    ]["unlock_power"],
                )

            return True

        if not alive_after:
            self.reset_mastery_on_training_defeat(
                monster_id
            )

        return False

    def log_scheduler_status(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        profiles = self.active_profiles()
        if profiles:
            profile = profiles[0]
            readiness = self.retry_readiness(
                profile,
                character,
            )
            metrics = readiness["mastery"]

            message = (
                f"Training for {profile['monster_name']} | "
                f"LV {readiness['level']}/{profile['retry_level']} | "
                f"Power {readiness['power']:.0f}/{profile['retry_power']} | "
                f"Mastery {metrics['wins']}/{metrics['required_wins']}"
            )

            if (
                self.adaptive.get(
                    "last_training_log"
                )
                != message
            ):
                self.adaptive[
                    "last_training_log"
                ] = message
                self.save_adaptive()
                self.logger.info(
                    "[TRAINING STATUS] %s",
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
                "adaptive_tier_training_state": (
                    self.adaptive
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_4_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_4_final_"
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
        bot = AdaptiveTierTrainer(
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
