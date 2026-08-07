from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_1_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (BASE_FILE, V15_FILE, ENGINE_FILE):
    if not required.exists():
        raise RuntimeError(f"Required file is missing: {required}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v161_base",
    BASE_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V1.6.1 base could not be loaded.")

v161 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v161
spec.loader.exec_module(v161)

base = v161.base
engine = v161.engine

for module in (v161, base, engine):
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
        OUTPUT_DIR / "eldoria_bot_v2_1_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_1_final.log"
    )

for module in (v161, base):
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

    logger = logging.getLogger("eldoria_bot_v2_1_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_1_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_1_final.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class AggressiveLearningBot(v161.FinalEldoriaBot):
    VERSION = "2.0-final-aggressive-learning-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.learning_file = STATE_DIR / "battle_learning_state.json"
        self.learning = engine.load_json(
            self.learning_file,
            {
                "policy_version": 0,
                "death_locks": {},
                "last_plan": "",
                "deaths_learned": 0,
                "retries_unlocked": 0,
            },
        )

        if as_int(self.learning.get("policy_version")) < 2:
            self.final_state["danger_blocks"] = {}
            self.save_final_state()
            self.learning["policy_version"] = 2
            self.save_learning()

        self.deaths_learned_this_run = 0
        self.retries_unlocked_this_run = 0

    def save_learning(self) -> None:
        engine.save_json(
            self.learning_file,
            self.learning,
        )

    # ----------------------------------------------------------
    # Learn from death, then farm until modestly stronger.
    # ----------------------------------------------------------

    def combat_power_value(
        self,
        character: dict[str, Any],
    ) -> float:
        return self.combat_power(character)

    def record_death_learning(
        self,
        monster: dict[str, Any],
        character_before: dict[str, Any],
        damage_taken: int,
    ) -> None:
        monster_id = as_int(monster.get("id"))
        if monster_id <= 0:
            return

        locks = self.learning.setdefault(
            "death_locks",
            {},
        )
        previous = locks.get(str(monster_id))
        deaths = (
            as_int(previous.get("deaths"))
            if isinstance(previous, dict)
            else 0
        ) + 1

        level = as_int(character_before.get("level"), 1)
        hp_max = as_int(character_before.get("hp_max"), 1)
        power = self.combat_power_value(character_before)

        growth = min(
            float(
                self.config["aggressive_learning"][
                    "maximum_retry_power_growth"
                ]
            ),
            float(
                self.config["aggressive_learning"][
                    "first_retry_power_growth"
                ]
            )
            + (deaths - 1)
            * float(
                self.config["aggressive_learning"][
                    "additional_growth_per_death"
                ]
            ),
        )

        locks[str(monster_id)] = {
            "monster_name": (
                monster.get("name_en")
                or monster.get("name")
                or monster.get("code")
            ),
            "deaths": deaths,
            "recorded_at": utc_now(),
            "level_at_death": level,
            "power_at_death": power,
            "hp_max_at_death": hp_max,
            "damage_taken": max(damage_taken, hp_max),
            "retry_level": level + 1,
            "retry_power": math.ceil(
                power * (1.0 + growth)
            ),
            "retry_hp_max": max(
                hp_max + 1,
                damage_taken
                + int(
                    self.config["aggressive_learning"][
                        "retry_hp_buffer"
                    ]
                ),
            ),
        }

        self.learning["deaths_learned"] = (
            as_int(self.learning.get("deaths_learned"))
            + 1
        )
        self.deaths_learned_this_run += 1
        self.save_learning()

        row = locks[str(monster_id)]
        self.logger.info(
            "[LEARN] Defeated by %s | retry after LV %s "
            "or Power %s; farming continues.",
            row["monster_name"],
            row["retry_level"],
            row["retry_power"],
        )

    def death_lock_active(
        self,
        monster: dict[str, Any],
        character: dict[str, Any],
    ) -> bool:
        monster_id = str(as_int(monster.get("id")))
        lock = self.learning.setdefault(
            "death_locks",
            {},
        ).get(monster_id)

        if not isinstance(lock, dict):
            return False

        level = as_int(character.get("level"), 1)
        hp_max = as_int(character.get("hp_max"), 1)
        power = self.combat_power_value(character)

        unlocked = bool(
            level >= as_int(lock.get("retry_level"), 10**9)
            or hp_max >= as_int(lock.get("retry_hp_max"), 10**9)
            or power >= as_float(
                lock.get("retry_power"),
                float("inf"),
            )
        )

        if not unlocked:
            return True

        self.learning["death_locks"].pop(
            monster_id,
            None,
        )
        self.learning["retries_unlocked"] = (
            as_int(self.learning.get("retries_unlocked"))
            + 1
        )
        self.retries_unlocked_this_run += 1
        self.save_learning()

        self.logger.info(
            "[RETRY] %s unlocked after becoming stronger.",
            (
                monster.get("name_en")
                or monster.get("name")
                or monster.get("code")
                or monster_id
            ),
        )
        return False

    # ----------------------------------------------------------
    # Quest first. If a Quest caused death, Gold/XP farm.
    # ----------------------------------------------------------

    def raw_candidates(
        self,
        character,
        objectives,
        material_needs,
    ):
        return base.AdvancedEldoriaBot.build_farm_candidates(
            self,
            character,
            objectives,
            material_needs,
        )

    def build_farm_candidates(
        self,
        character,
        objectives,
        material_needs,
    ):
        candidates = [
            candidate
            for candidate in self.raw_candidates(
                character,
                objectives,
                material_needs,
            )
            if not self.death_lock_active(
                candidate.monster,
                character,
            )
        ]

        for candidate in candidates:
            learned = self.observed_gold_per_stamina(
                as_int(candidate.monster.get("id"))
            )
            if learned is not None:
                candidate.gold_per_stamina = learned

        candidates.sort(
            key=lambda row: (
                row.priority,
                -row.gold_per_stamina,
                -row.xp_per_stamina,
                -row.material_score,
                row.predicted_damage,
                as_int(row.monster.get("level")),
            )
        )
        return candidates

    def plan_label(
        self,
        candidate,
    ) -> None:
        mode = (
            "QUEST"
            if candidate.priority == 0
            else "QUEST"
            if candidate.priority <= 3
            else "FARM"
        )
        key = (
            f"{mode}:{candidate.monster.get('id')}:"
            f"{candidate.reason}"
        )

        if self.learning.get("last_plan") == key:
            return

        self.learning["last_plan"] = key
        self.save_learning()

        name = (
            candidate.monster.get("name_en")
            or candidate.monster.get("name")
            or candidate.monster.get("code")
        )

        if mode == "QUEST":
            self.logger.info(
                "[PLAN] Attack now -> %s | %s.",
                candidate.reason,
                name,
            )
        else:
            self.logger.info(
                "[PLAN] Strength farm -> %s | "
                "Gold/STM %.2f | XP/STM %.2f.",
                name,
                candidate.gold_per_stamina,
                candidate.xp_per_stamina,
            )

    # ----------------------------------------------------------
    # One Fight only: no waiting for a batch of 33 stamina.
    # ----------------------------------------------------------

    def known_damage_requirement(
        self,
        monster_id: int,
    ) -> int:
        row = self.combat_history.get(str(monster_id))
        if not isinstance(row, dict):
            return 0

        observed = max(
            as_float(row.get("maximum")),
            as_float(row.get("average")),
        )
        if observed <= 0:
            return 0

        return math.ceil(
            observed
            * float(
                self.config["aggressive_learning"][
                    "known_damage_margin"
                ]
            )
            + int(
                self.config["aggressive_learning"][
                    "known_hp_buffer"
                ]
            )
        )

    def dynamic_targets_for_candidate(
        self,
        candidate,
    ) -> tuple[int, int, int]:
        character = self.get_character()
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        monster_id = as_int(candidate.monster.get("id"))
        fight_cost = max(
            1,
            as_int(
                candidate.monster.get("stamina_cost"),
                1,
            ),
        )

        known_hp = self.known_damage_requirement(monster_id)

        if known_hp > 0:
            hp_target = min(hp_max, known_hp)
        elif candidate.monster.get("is_boss"):
            hp_target = math.ceil(
                hp_max
                * float(
                    self.config["aggressive_learning"][
                        "unknown_boss_hp_ratio"
                    ]
                )
            )
        elif candidate.priority == 0:
            hp_target = math.ceil(
                hp_max
                * float(
                    self.config["aggressive_learning"][
                        "unknown_quest_hp_ratio"
                    ]
                )
            )
        else:
            hp_target = math.ceil(
                hp_max
                * float(
                    self.config["aggressive_learning"][
                        "unknown_farm_hp_ratio"
                    ]
                )
            )

        return max(1, hp_target), fight_cost, 0

    def skill_schema_ready(self) -> bool:
        state = self.final_state.get("interactive", {})
        return bool(
            isinstance(state.get("basic_schema"), int)
            and isinstance(state.get("skill_schema"), int)
            and time.time()
            >= as_float(state.get("unavailable_until"), 0)
        )

    def execute_fight(self, candidate) -> bool:
        before = self.ensure_alive()
        monster = candidate.monster
        monster_id = as_int(monster.get("id"))
        if monster_id <= 0:
            return False

        self.plan_label(candidate)

        name = (
            monster.get("name_en")
            or monster.get("name")
            or monster.get("code")
        )
        label = f"{candidate.reason}: {name}"

        if label != self.last_task_label:
            self.logger.info(
                "[TASK] %s | damage~%s | Gold/STM %.2f",
                label,
                candidate.predicted_damage,
                candidate.gold_per_stamina,
            )
            self.last_task_label = label

        hp_before = as_int(before.get("hp"))
        hp_max_before = as_int(before.get("hp_max"), hp_before)
        stamina_before = as_int(before.get("stamina"))

        result = None
        used_interactive = False

        if (
            self.config["skills"]["use_mp_skills"]
            and (
                candidate.priority == 0
                or monster.get("is_boss")
            )
            and self.skill_schema_ready()
        ):
            try:
                result = self.interactive_combat(candidate)
                used_interactive = result is not None
            except Exception as exc:
                self.logger.info(
                    "[SKILL] Interactive mode failed; "
                    "normal Fight will be used: %s",
                    exc,
                )
                result = None

        if result is None:
            result = self.client.post(
                f"world/fight/{monster_id}"
            )

        self.record(
            "fight",
            result.ok,
            {
                "zone_id": candidate.zone_id,
                "monster_id": monster_id,
                "monster": name,
                "reason": candidate.reason,
                "interactive": used_interactive,
                "predicted_damage": candidate.predicted_damage,
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        response_damage = int(
            engine.deep_find_number(
                result.data,
                {"damage_taken", "total_damage_taken"},
            )
            or 0
        )
        gold = int(
            engine.deep_find_number(
                result.data,
                {"gold_gained", "gold_reward"},
            )
            or 0
        )
        xp = int(
            engine.deep_find_number(
                result.data,
                {"xp_gained", "xp_reward"},
            )
            or 0
        )

        after = self.get_character()
        hp_after = as_int(after.get("hp"))
        stamina_after = as_int(after.get("stamina"))

        damage = max(
            response_damage,
            max(0, hp_before - hp_after),
        )
        stamina_used = max(
            0,
            stamina_before - stamina_after,
        )

        alive = self.is_alive(after)
        try:
            outcome = self.combat_outcome(result.data)
        except Exception:
            outcome = None

        victory = bool(
            result.ok
            and alive
            and outcome != "defeat"
        )

        if damage > 0:
            self.update_damage_history(
                monster_id,
                damage,
            )

        if victory:
            self.update_farm_history(
                monster_id=monster_id,
                gold=gold,
                xp=xp,
                stamina=stamina_used,
                duration_seconds=1.0,
            )
            self.total_battles += 1
            self.total_gold_gained += gold

            every = int(
                self.config["logging"][
                    "battle_summary_every"
                ]
            )
            if self.total_battles % every == 0:
                self.log_status(
                    "FARM",
                    after,
                    (
                        f"Battles {self.total_battles} | "
                        f"last {name} | damage {damage} | "
                        f"+{gold} Gold"
                    ),
                )
            return True

        if not alive:
            self.record_death_learning(
                monster,
                before,
                max(
                    damage,
                    hp_before,
                    hp_max_before,
                ),
            )
            self.ensure_alive()
            return False

        self.logger.info(
            "[FIGHT] %s failed without death; "
            "another task will be selected.",
            name,
        )
        return False

    def run_farming_batch(self, material_needs) -> None:
        maximum = int(
            self.config["continuous"][
                "max_battles_per_batch"
            ]
        )
        completed = 0

        while completed < maximum:
            character = self.ensure_alive()
            objectives = self.objective_rows()
            candidates = self.build_farm_candidates(
                character,
                objectives,
                material_needs,
            )

            if not candidates:
                return

            candidate = candidates[0]
            hp_target, stamina_target, _ = (
                self.dynamic_targets_for_candidate(candidate)
            )

            hp = as_int(character.get("hp"))
            stamina = as_int(character.get("stamina"))

            if hp < hp_target:
                if (
                    candidate.priority <= 1
                    and self.use_hp_potions_until_safe(
                        hp_target,
                        high_priority=True,
                    )
                ):
                    continue
                return

            if stamina < stamina_target:
                if (
                    candidate.priority <= 3
                    and self.use_stamina_potion_if_worthwhile(
                        character,
                        has_priority_tasks=True,
                    )
                ):
                    time.sleep(
                        float(
                            self.config["automation"][
                                "action_delay_seconds"
                            ]
                        )
                    )
                    continue
                return

            travelled = self.travel_to(
                character,
                candidate.zone_id,
            )
            if travelled is None:
                return

            if not self.execute_fight(candidate):
                return

            completed += 1

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

            self.claim_free_rewards()
            self.claim_achievements()

            interval = int(
                self.config["logging"][
                    "craft_recheck_every_battles"
                ]
            )
            if (
                candidate.material_score > 0
                and self.total_battles % interval == 0
            ):
                material_needs.update(
                    self.complete_craft_quests()
                )

    def next_regular_targets(
        self,
    ) -> tuple[int, int, int, str, bool]:
        character = self.ensure_alive()
        objectives = self.objective_rows()
        material_needs = self.complete_craft_quests()
        candidates = self.build_farm_candidates(
            character,
            objectives,
            material_needs,
        )

        if not candidates:
            return (
                as_int(character.get("hp")),
                1,
                0,
                "Waiting for an accessible target",
                False,
            )

        candidate = candidates[0]
        hp_target, stamina_target, mp_target = (
            self.dynamic_targets_for_candidate(candidate)
        )

        return (
            hp_target,
            stamina_target,
            mp_target,
            candidate.reason,
            candidate.priority <= 3,
        )

    def final_report(self) -> dict[str, Any]:
        report = self.advanced_report()
        report.update(
            {
                "version": self.VERSION,
                "deaths_learned_this_run": (
                    self.deaths_learned_this_run
                ),
                "retries_unlocked_this_run": (
                    self.retries_unlocked_this_run
                ),
                "battle_learning_state": self.learning,
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_1_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_1_final_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".json"
            ),
            report,
        )
        return report



class ActiveQuestScheduler(AggressiveLearningBot):
    VERSION = "2.1-final-active-quest-scheduler-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.scheduler_file = STATE_DIR / "active_scheduler_state.json"
        self.scheduler_state = engine.load_json(
            self.scheduler_file,
            {
                "last_status": "",
                "last_error": "",
                "cycles": 0,
            },
        )

        self.cached_material_needs: dict[str, int] = {}
        self.next_fast_housekeeping = 0.0
        self.next_craft_check = 0.0
        self.next_progression_check = 0.0
        self.next_special_check = 0.0
        self._scheduler_character: dict[str, Any] | None = None

    def save_scheduler_state(self) -> None:
        engine.save_json(
            self.scheduler_file,
            self.scheduler_state,
        )

    # ----------------------------------------------------------
    # Requirements are for one real Fight, never a batch.
    # Old death damage cannot force full-HP waiting.
    # ----------------------------------------------------------

    def dynamic_targets_for_candidate(
        self,
        candidate,
    ) -> tuple[int, int, int]:
        character = (
            self._scheduler_character
            if isinstance(self._scheduler_character, dict)
            else self.get_character()
        )

        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        monster_id = as_int(candidate.monster.get("id"))
        predicted = max(
            1,
            as_int(candidate.predicted_damage, 1),
        )
        stamina_cost = max(
            1,
            as_int(
                candidate.monster.get("stamina_cost"),
                1,
            ),
        )

        history = self.combat_history.get(str(monster_id))
        history_average = 0.0
        if isinstance(history, dict):
            history_average = as_float(
                history.get("average"),
                0.0,
            )

        estimate = max(
            predicted
            * float(
                self.config["active_scheduler"][
                    "prediction_margin"
                ]
            ),
            history_average
            * float(
                self.config["active_scheduler"][
                    "history_average_margin"
                ]
            ),
        )

        # A contaminated old history must never require full HP.
        history_cap = math.floor(
            hp_max
            * float(
                self.config["active_scheduler"][
                    "history_hp_cap_ratio"
                ]
            )
        )

        if self.death_lock_active(
            candidate.monster,
            character,
        ):
            hp_target = hp_max
        elif candidate.monster.get("is_boss"):
            hp_target = math.ceil(
                hp_max
                * float(
                    self.config["active_scheduler"][
                        "unknown_boss_hp_ratio"
                    ]
                )
            )
        elif candidate.priority == 0:
            hp_target = min(
                history_cap,
                max(
                    math.ceil(
                        hp_max
                        * float(
                            self.config["active_scheduler"][
                                "quest_min_hp_ratio"
                            ]
                        )
                    ),
                    math.ceil(
                        estimate
                        + int(
                            self.config["active_scheduler"][
                                "hp_buffer"
                            ]
                        )
                    ),
                ),
            )
        else:
            hp_target = min(
                history_cap,
                max(
                    math.ceil(
                        hp_max
                        * float(
                            self.config["active_scheduler"][
                                "farm_min_hp_ratio"
                            ]
                        )
                    ),
                    math.ceil(
                        min(
                            estimate,
                            hp_max
                            * float(
                                self.config["active_scheduler"][
                                    "farm_estimate_cap_ratio"
                                ]
                            ),
                        )
                    ),
                ),
            )

        return (
            max(1, min(hp_max, hp_target)),
            stamina_cost,
            0,
        )

    def candidate_state(
        self,
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        self._scheduler_character = character
        hp_target, stamina_target, mp_target = (
            self.dynamic_targets_for_candidate(candidate)
        )

        hp = as_int(character.get("hp"))
        stamina = as_int(character.get("stamina"))
        mp = as_int(character.get("mp"))

        return {
            "candidate": candidate,
            "hp_target": hp_target,
            "stamina_target": stamina_target,
            "mp_target": mp_target,
            "hp_short": max(0, hp_target - hp),
            "stamina_short": max(
                0,
                stamina_target - stamina,
            ),
            "mp_short": max(0, mp_target - mp),
            "actionable": bool(
                hp >= hp_target
                and stamina >= stamina_target
                and mp >= mp_target
            ),
        }

    def choose_action(
        self,
        character: dict[str, Any],
        objectives,
        material_needs,
    ):
        self._scheduler_character = character

        candidates = self.build_farm_candidates(
            character,
            objectives,
            material_needs,
        )

        states = [
            self.candidate_state(
                candidate,
                character,
            )
            for candidate in candidates
        ]

        actionable = [
            row
            for row in states
            if row["actionable"]
        ]

        if not actionable:
            return None, states

        actionable.sort(
            key=lambda row: (
                row["candidate"].priority,
                -row["candidate"].gold_per_stamina,
                -row["candidate"].xp_per_stamina,
                row["candidate"].predicted_damage,
            )
        )
        return actionable[0], states

    def best_pending(self, states):
        if not states:
            return None

        return min(
            states,
            key=lambda row: (
                row["candidate"].priority,
                bool(row["stamina_short"]),
                row["hp_short"]
                + row["stamina_short"] * 10,
                -row["candidate"].gold_per_stamina,
                -row["candidate"].xp_per_stamina,
            ),
        )

    def pending_quest(self, states):
        quests = [
            row
            for row in states
            if row["candidate"].priority <= 3
            and not row["actionable"]
        ]
        if not quests:
            return None

        return min(
            quests,
            key=lambda row: (
                row["candidate"].priority,
                row["hp_short"]
                + row["stamina_short"] * 10,
            ),
        )

    # ----------------------------------------------------------
    # Daily, claims, quests, crafting, skills and equipment run
    # independently. One failure cannot stop fighting.
    # ----------------------------------------------------------

    def safe_step(
        self,
        name: str,
        action,
        default=None,
    ):
        try:
            return action()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            key = f"{name}:{type(exc).__name__}:{exc}"
            if self.scheduler_state.get("last_error") != key:
                self.scheduler_state["last_error"] = key
                self.save_scheduler_state()
                self.logger.info(
                    "[RECOVER] %s skipped this cycle: %s",
                    name,
                    exc,
                )
            return default

    def run_housekeeping(
        self,
        now: float,
        startup: bool = False,
    ) -> None:
        if startup or now >= self.next_fast_housekeeping:
            self.safe_step(
                "Daily and Quest rewards",
                self.claim_free_rewards,
            )
            self.safe_step(
                "Achievements",
                self.claim_achievements,
            )
            self.safe_step(
                "Free Quest start",
                self.start_all_free_quests,
            )
            self.next_fast_housekeeping = (
                now
                + float(
                    self.config["active_scheduler"][
                        "fast_housekeeping_seconds"
                    ]
                )
            )

        if startup or now >= self.next_craft_check:
            materials = self.safe_step(
                "Craft Quests",
                self.complete_craft_quests,
                {},
            )
            if isinstance(materials, dict):
                self.cached_material_needs = materials
            self.next_craft_check = (
                now
                + float(
                    self.config["active_scheduler"][
                        "craft_check_seconds"
                    ]
                )
            )

        if startup or now >= self.next_progression_check:
            self.safe_step(
                "Skills",
                self.optimize_skills,
            )
            self.safe_step(
                "Skill Tree",
                self.optimize_skill_tree,
            )
            self.safe_step(
                "Equipment and upgrades",
                self.optimize_progression,
            )
            self.next_progression_check = (
                now
                + float(
                    self.config["active_scheduler"][
                        "progression_check_seconds"
                    ]
                )
            )

    def after_fight_housekeeping(self) -> None:
        self.safe_step(
            "Quest reward after Fight",
            self.claim_free_rewards,
        )
        self.safe_step(
            "Achievement after Fight",
            self.claim_achievements,
        )
        self.safe_step(
            "New Quest after Fight",
            self.start_all_free_quests,
        )

    def try_quest_resources(
        self,
        pending,
        character: dict[str, Any],
    ) -> bool:
        if pending is None:
            return False

        if pending["hp_short"] > 0:
            used = self.safe_step(
                "Quest HP Potion",
                lambda: self.use_hp_potions_until_safe(
                    pending["hp_target"],
                    high_priority=True,
                ),
                False,
            )
            if used:
                return True

        if pending["stamina_short"] > 0:
            used = self.safe_step(
                "Quest Stamina Potion",
                lambda: self.use_stamina_potion_if_worthwhile(
                    character,
                    has_priority_tasks=True,
                ),
                False,
            )
            if used:
                return True

        return False

    def log_scheduler_status(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        hp = as_int(character.get("hp"))
        stamina = as_int(character.get("stamina"))
        mp = as_int(character.get("mp"))

        if pending is None:
            message = (
                f"No accessible target | "
                f"HP {hp} | STM {stamina} | MP {mp}"
            )
        else:
            candidate = pending["candidate"]
            name = (
                candidate.monster.get("name_en")
                or candidate.monster.get("name")
                or candidate.monster.get("code")
            )
            missing = []
            if pending["hp_short"]:
                missing.append(
                    f"HP +{pending['hp_short']}"
                )
            if pending["stamina_short"]:
                missing.append(
                    f"STM +{pending['stamina_short']}"
                )
            if pending["mp_short"]:
                missing.append(
                    f"MP +{pending['mp_short']}"
                )

            message = (
                f"{name} pending: "
                + (
                    ", ".join(missing)
                    if missing
                    else "re-evaluating"
                )
            )

        if self.scheduler_state.get("last_status") == message:
            return

        self.scheduler_state["last_status"] = message
        self.save_scheduler_state()
        self.logger.info(
            "[SCHEDULER] %s",
            message,
        )

    # ----------------------------------------------------------
    # No blocking wait. Every loop re-plans all targets.
    # ----------------------------------------------------------

    def run(self) -> None:
        authentication = self.client.get("auth/me")
        if not authentication.ok:
            raise RuntimeError(
                "Authentication failed: "
                f"status={authentication.status} "
                f"error={authentication.error}"
            )

        self.initial_character = self.get_character()

        self.logger.info(
            "[START] Eldoria Bot %s",
            self.VERSION,
        )
        self.logger.info(
            "[MODE] Active Quest scheduling, aggressive combat and continuous Gold farming."
        )
        self.log_status(
            "START",
            self.initial_character,
        )

        poll = float(
            self.config["active_scheduler"][
                "poll_seconds"
            ]
        )

        try:
            self.run_housekeeping(
                time.time(),
                startup=True,
            )

            while True:
                try:
                    character = self.ensure_alive()
                    self._scheduler_character = character
                    now = time.time()

                    self.run_housekeeping(now)

                    objectives = self.safe_step(
                        "Quest objectives",
                        self.objective_rows,
                        [],
                    )
                    if not isinstance(objectives, list):
                        objectives = []

                    selected, states = self.choose_action(
                        character,
                        objectives,
                        self.cached_material_needs,
                    )

                    # A high-priority Quest may use available potions before
                    # the scheduler falls back to farming.
                    waiting_quest = self.pending_quest(states)
                    if (
                        waiting_quest is not None
                        and self.try_quest_resources(
                            waiting_quest,
                            character,
                        )
                    ):
                        time.sleep(
                            float(
                                self.config["automation"][
                                    "action_delay_seconds"
                                ]
                            )
                        )
                        continue

                    if selected is not None:
                        candidate = selected["candidate"]

                        travelled = self.safe_step(
                            "Travel",
                            lambda: self.travel_to(
                                character,
                                candidate.zone_id,
                            ),
                            None,
                        )
                        if travelled is None:
                            time.sleep(poll)
                            continue

                        self.scheduler_state["last_status"] = ""
                        self.save_scheduler_state()

                        self.execute_fight(candidate)
                        self.after_fight_housekeeping()

                        time.sleep(
                            float(
                                self.config["automation"][
                                    "action_delay_seconds"
                                ]
                            )
                        )
                        continue

                    pending = self.best_pending(states)

                    # Boss and Dungeon checks are opportunistic and can never
                    # block normal Quest or farming decisions.
                    if now >= self.next_special_check:
                        has_urgent = any(
                            getattr(row, "objective_type", "")
                            in {"kill", "craft", "loot"}
                            for row in objectives
                        )

                        boss = self.safe_step(
                            "World Boss scan",
                            lambda: self.active_world_boss(
                                objectives
                            ),
                            None,
                        )
                        if boss is not None:
                            acted = self.safe_step(
                                "World Boss",
                                lambda: self.run_world_boss(
                                    boss
                                ),
                                False,
                            )
                            if acted:
                                self.next_special_check = now + 60
                                continue

                        acted = self.safe_step(
                            "Dungeon",
                            lambda: self.run_dungeon_autopilot(
                                has_urgent_quests=has_urgent,
                            ),
                            False,
                        )
                        self.next_special_check = (
                            now
                            + float(
                                self.config["active_scheduler"][
                                    "special_check_seconds"
                                ]
                            )
                        )
                        if acted:
                            continue

                    self.log_scheduler_status(
                        pending,
                        character,
                    )
                    time.sleep(poll)
                    self.total_wait_seconds += poll

                    self.scheduler_state["cycles"] = (
                        as_int(
                            self.scheduler_state.get("cycles")
                        )
                        + 1
                    )
                    self.save_scheduler_state()

                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    key = f"cycle:{type(exc).__name__}:{exc}"
                    if self.scheduler_state.get("last_error") != key:
                        self.scheduler_state["last_error"] = key
                        self.save_scheduler_state()
                        self.logger.info(
                            "[RECOVER] Scheduler cycle failed; "
                            "retrying in %ss: %s",
                            int(poll),
                            exc,
                        )
                    time.sleep(poll)

        finally:
            self.final_report()

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "active_scheduler_state": (
                    self.scheduler_state
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_1_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_1_final_"
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
        directory.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        print(f"Configuration file is missing: {CONFIG_FILE}")
        return 2

    config = engine.load_json(CONFIG_FILE, {})
    logger = configure_logging()

    try:
        client = engine.APIClient(config, logger)
        bot = ActiveQuestScheduler(client, config, logger)
        bot.run()
        return 0

    except KeyboardInterrupt:
        logger.info("[STOP] Interrupted by user.")
        return 130

    except Exception as exc:
        logger.exception("[FATAL] %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
