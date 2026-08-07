from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_2_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (V21_FILE, V161_FILE, V15_FILE, ENGINE_FILE):
    if not required.exists():
        raise RuntimeError(f"Required file is missing: {required}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v21_base",
    V21_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.1 base could not be loaded.")

v21 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v21
spec.loader.exec_module(v21)

v161 = v21.v161
base = v21.base
engine = v21.engine

for module in (v21, v161, base, engine):
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
        OUTPUT_DIR / "eldoria_bot_v2_2_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_2_final.log"
    )

for module in (v21, v161, base):
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


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_2_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_2_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_2_final.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class SmartCombatScheduler(v21.ActiveQuestScheduler):
    VERSION = "2.2-final-smart-combat-scheduler-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.smart_file = STATE_DIR / "smart_combat_state.json"
        self.smart_state = engine.load_json(
            self.smart_file,
            {
                "successful_damage": {},
                "last_hard_block": "",
                "last_wait": "",
                "hard_blocks_seen": 0,
            },
        )

    def save_smart_state(self) -> None:
        engine.save_json(
            self.smart_file,
            self.smart_state,
        )

    @staticmethod
    def monster_name(monster: dict[str, Any]) -> str:
        return str(
            monster.get("name_en")
            or monster.get("name")
            or monster.get("code")
            or monster.get("id")
        )

    @staticmethod
    def is_boss(monster: dict[str, Any]) -> bool:
        return bool(
            monster.get("is_boss")
            or monster.get("boss")
            or "boss" in str(
                monster.get("type", "")
            ).lower()
        )

    # ----------------------------------------------------------
    # Separate victories from deaths. Only successful damage is used
    # to calculate the next HP requirement for that enemy.
    # ----------------------------------------------------------

    def record_successful_damage(
        self,
        monster_id: int,
        damage: int,
    ) -> None:
        if monster_id <= 0 or damage < 0:
            return

        rows = self.smart_state.setdefault(
            "successful_damage",
            {},
        )
        row = rows.setdefault(
            str(monster_id),
            {
                "count": 0,
                "average": 0.0,
                "maximum": 0,
            },
        )

        count = as_int(row.get("count"))
        average = as_float(row.get("average"))
        maximum = as_int(row.get("maximum"))

        new_count = count + 1
        row["count"] = new_count
        row["average"] = (
            average * count + damage
        ) / max(1, new_count)
        row["maximum"] = max(maximum, damage)
        self.save_smart_state()

    def successful_damage_estimate(
        self,
        monster_id: int,
    ) -> float | None:
        row = self.smart_state.get(
            "successful_damage",
            {},
        ).get(str(monster_id))

        if not isinstance(row, dict):
            return None
        if as_int(row.get("count")) <= 0:
            return None

        return max(
            as_float(row.get("maximum")),
            as_float(row.get("average"))
            * float(
                self.config["smart_combat"][
                    "successful_average_multiplier"
                ]
            ),
        )

    # ----------------------------------------------------------
    # Three outcomes:
    # ready -> attack now
    # heal -> fight is winnable at higher current HP
    # strengthen -> even full HP is insufficient, so farm safely
    # ----------------------------------------------------------

    def combat_assessment(
        self,
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        monster = candidate.monster
        monster_id = as_int(monster.get("id"))
        hp = max(0, as_int(character.get("hp")))
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        stamina = max(
            0,
            as_int(character.get("stamina")),
        )
        mp = max(0, as_int(character.get("mp")))

        stamina_cost = max(
            1,
            as_int(monster.get("stamina_cost"), 1),
        )
        player_level = max(
            1,
            as_int(character.get("level"), 1),
        )
        monster_level = max(
            1,
            as_int(monster.get("level"), 1),
        )
        level_gap = monster_level - player_level

        predicted = max(
            0.0,
            as_float(candidate.predicted_damage),
        )
        success_damage = self.successful_damage_estimate(
            monster_id
        )
        quest_exact = candidate.priority == 0
        quest_related = candidate.priority <= 3
        boss = self.is_boss(monster)
        death_locked = self.death_lock_active(
            monster,
            character,
        )

        if success_damage is not None:
            estimate = success_damage
            margin = float(
                self.config["smart_combat"][
                    "successful_damage_margin"
                ]
            )
            buffer = int(
                self.config["smart_combat"][
                    "successful_hp_buffer"
                ]
            )
            required_hp = math.ceil(
                estimate * margin + buffer
            )
            confidence = "proven"
        else:
            if predicted <= 0:
                # Missing predictions are allowed only for clearly weaker
                # ordinary monsters, never for unknown bosses.
                if boss or level_gap > -2:
                    return {
                        "candidate": candidate,
                        "state": "strengthen",
                        "reason": "no reliable damage estimate",
                        "required_hp": hp_max + 1,
                        "stamina_target": stamina_cost,
                        "mp_target": 0,
                        "estimate": predicted,
                        "risk_ratio": 999.0,
                        "quest_exact": quest_exact,
                        "quest_related": quest_related,
                    }
                predicted = hp_max * float(
                    self.config["smart_combat"][
                        "weak_unknown_damage_ratio"
                    ]
                )

            if boss:
                margin = float(
                    self.config["smart_combat"][
                        "unknown_boss_damage_margin"
                    ]
                )
                buffer = int(
                    self.config["smart_combat"][
                        "unknown_boss_hp_buffer"
                    ]
                )
            elif quest_exact:
                margin = float(
                    self.config["smart_combat"][
                        "unknown_quest_damage_margin"
                    ]
                )
                buffer = int(
                    self.config["smart_combat"][
                        "unknown_quest_hp_buffer"
                    ]
                )
            else:
                margin = float(
                    self.config["smart_combat"][
                        "unknown_farm_damage_margin"
                    ]
                )
                buffer = int(
                    self.config["smart_combat"][
                        "unknown_farm_hp_buffer"
                    ]
                )

            required_hp = math.ceil(
                predicted * margin + buffer
            )
            estimate = predicted
            confidence = "predicted"

        if death_locked:
            return {
                "candidate": candidate,
                "state": "strengthen",
                "reason": "previous defeat; retry condition not reached",
                "required_hp": max(required_hp, hp_max + 1),
                "stamina_target": stamina_cost,
                "mp_target": 0,
                "estimate": estimate,
                "risk_ratio": required_hp / hp_max,
                "quest_exact": quest_exact,
                "quest_related": quest_related,
                "confidence": confidence,
            }

        # Unknown high-level farming is never used as a shortcut.
        # Exact Quest targets may be bolder, but still must fit inside HP max.
        if success_damage is None:
            if boss and level_gap > int(
                self.config["smart_combat"][
                    "maximum_unknown_boss_level_gap"
                ]
            ):
                return {
                    "candidate": candidate,
                    "state": "strengthen",
                    "reason": "boss level gap is too high",
                    "required_hp": max(required_hp, hp_max + 1),
                    "stamina_target": stamina_cost,
                    "mp_target": 0,
                    "estimate": estimate,
                    "risk_ratio": required_hp / hp_max,
                    "quest_exact": quest_exact,
                    "quest_related": quest_related,
                    "confidence": confidence,
                }

            if (
                quest_exact
                and level_gap
                > int(
                    self.config["smart_combat"][
                        "maximum_unknown_exact_quest_level_gap"
                    ]
                )
            ):
                return {
                    "candidate": candidate,
                    "state": "strengthen",
                    "reason": "Quest target level gap is too high",
                    "required_hp": max(required_hp, hp_max + 1),
                    "stamina_target": stamina_cost,
                    "mp_target": 0,
                    "estimate": estimate,
                    "risk_ratio": required_hp / hp_max,
                    "quest_exact": quest_exact,
                    "quest_related": quest_related,
                    "confidence": confidence,
                }

            if (
                not quest_exact
                and level_gap
                > int(
                    self.config["smart_combat"][
                        "maximum_unknown_farm_level_gap"
                    ]
                )
            ):
                return {
                    "candidate": candidate,
                    "state": "strengthen",
                    "reason": "farm target is unnecessarily strong",
                    "required_hp": max(required_hp, hp_max + 1),
                    "stamina_target": stamina_cost,
                    "mp_target": 0,
                    "estimate": estimate,
                    "risk_ratio": required_hp / hp_max,
                    "quest_exact": quest_exact,
                    "quest_related": quest_related,
                    "confidence": confidence,
                }

        # Crucial rule: never cap an impossible damage estimate down to HP.
        if required_hp > hp_max:
            return {
                "candidate": candidate,
                "state": "strengthen",
                "reason": "full HP is not enough for this fight",
                "required_hp": required_hp,
                "stamina_target": stamina_cost,
                "mp_target": 0,
                "estimate": estimate,
                "risk_ratio": required_hp / hp_max,
                "quest_exact": quest_exact,
                "quest_related": quest_related,
                "confidence": confidence,
            }

        if hp < required_hp:
            state = "heal"
            reason = "waiting for enough HP"
        elif stamina < stamina_cost:
            state = "resource"
            reason = "waiting for one Fight stamina"
        else:
            state = "ready"
            reason = "ready to attack"

        return {
            "candidate": candidate,
            "state": state,
            "reason": reason,
            "required_hp": required_hp,
            "stamina_target": stamina_cost,
            "mp_target": 0,
            "estimate": estimate,
            "risk_ratio": required_hp / hp_max,
            "quest_exact": quest_exact,
            "quest_related": quest_related,
            "confidence": confidence,
            "hp_short": max(0, required_hp - hp),
            "stamina_short": max(
                0,
                stamina_cost - stamina,
            ),
            "mp_short": 0,
            "actionable": state == "ready",
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
        assessments = [
            self.combat_assessment(
                candidate,
                character,
            )
            for candidate in candidates
        ]

        # 1. An exact Quest that is ready is always attacked first.
        ready_exact = [
            row
            for row in assessments
            if row["state"] == "ready"
            and row["quest_exact"]
        ]
        if ready_exact:
            ready_exact.sort(
                key=lambda row: (
                    row["candidate"].priority,
                    row["risk_ratio"],
                    -row["candidate"].gold_per_stamina,
                    -row["candidate"].xp_per_stamina,
                )
            )
            return ready_exact[0], assessments

        # 2. If an exact Quest is beatable at full HP but current HP is
        # insufficient, heal instead of wasting HP on unrelated fights.
        healing_exact = [
            row
            for row in assessments
            if row["state"] in {"heal", "resource"}
            and row["quest_exact"]
        ]
        if healing_exact:
            healing_exact.sort(
                key=lambda row: (
                    row["hp_short"]
                    + row["stamina_short"] * 10,
                    row["risk_ratio"],
                )
            )
            return None, assessments

        # 3. Other ready Quest/Craft targets.
        ready_related = [
            row
            for row in assessments
            if row["state"] == "ready"
            and row["quest_related"]
        ]
        if ready_related:
            ready_related.sort(
                key=lambda row: (
                    row["candidate"].priority,
                    row["risk_ratio"],
                    -row["candidate"].gold_per_stamina,
                    -row["candidate"].xp_per_stamina,
                )
            )
            return ready_related[0], assessments

        # 4. No beatable Quest is ready. Choose the best safe Gold/XP fight.
        ready_farm = [
            row
            for row in assessments
            if row["state"] == "ready"
            and not row["quest_related"]
        ]
        if ready_farm:
            gold_weight = float(
                self.config["smart_combat"][
                    "gold_weight"
                ]
            )
            xp_weight = float(
                self.config["smart_combat"][
                    "xp_weight"
                ]
            )
            risk_penalty = float(
                self.config["smart_combat"][
                    "risk_penalty"
                ]
            )

            ready_farm.sort(
                key=lambda row: -(
                    row["candidate"].gold_per_stamina
                    * gold_weight
                    + row["candidate"].xp_per_stamina
                    * xp_weight
                    - row["risk_ratio"]
                    * risk_penalty
                )
            )
            return ready_farm[0], assessments

        # 5. A safe related material target can still progress a Quest.
        safe_related = [
            row
            for row in assessments
            if row["state"] == "ready"
        ]
        if safe_related:
            safe_related.sort(
                key=lambda row: (
                    row["risk_ratio"],
                    -row["candidate"].gold_per_stamina,
                    -row["candidate"].xp_per_stamina,
                )
            )
            return safe_related[0], assessments

        return None, assessments

    def pending_quest(self, states):
        # Only genuinely beatable Quests are allowed to request healing.
        quests = [
            row
            for row in states
            if row.get("quest_related")
            and row.get("state") in {"heal", "resource"}
        ]
        if not quests:
            return None

        return min(
            quests,
            key=lambda row: (
                not row.get("quest_exact"),
                row.get("candidate").priority,
                row.get("hp_short", 0)
                + row.get("stamina_short", 0) * 10,
            ),
        )

    def best_pending(self, states):
        if not states:
            return None

        beatable = [
            row
            for row in states
            if row.get("state") in {"heal", "resource"}
        ]
        if beatable:
            return min(
                beatable,
                key=lambda row: (
                    not row.get("quest_exact"),
                    row.get("candidate").priority,
                    row.get("hp_short", 0)
                    + row.get("stamina_short", 0) * 10,
                ),
            )

        # All current Quest targets need strengthening.
        blocked = [
            row
            for row in states
            if row.get("state") == "strengthen"
            and row.get("quest_related")
        ]
        if blocked:
            return min(
                blocked,
                key=lambda row: (
                    not row.get("quest_exact"),
                    row.get("candidate").priority,
                    row.get("required_hp", 10**12),
                ),
            )

        return None

    def log_scheduler_status(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        hp = as_int(character.get("hp"))
        hp_max = as_int(character.get("hp_max"))
        stamina = as_int(character.get("stamina"))
        mp = as_int(character.get("mp"))

        if pending is None:
            message = (
                f"No combat candidate returned | "
                f"HP {hp}/{hp_max} | STM {stamina} | MP {mp}"
            )
        else:
            candidate = pending["candidate"]
            name = self.monster_name(candidate.monster)
            state = pending.get("state")

            if state == "heal":
                message = (
                    f"Waiting for {name} | "
                    f"HP {hp}/{pending['required_hp']} | "
                    f"STM {stamina}/{pending['stamina_target']}"
                )
            elif state == "resource":
                message = (
                    f"Waiting for {name} | "
                    f"STM {stamina}/{pending['stamina_target']}"
                )
            elif state == "strengthen":
                message = (
                    f"{name} needs strengthening | "
                    f"estimated HP need {pending['required_hp']} "
                    f"> max {hp_max}; safe farming remains active"
                )
            else:
                message = (
                    f"{name} is being re-evaluated | "
                    f"HP {hp}/{hp_max} | STM {stamina}"
                )

        if self.scheduler_state.get("last_status") == message:
            return

        self.scheduler_state["last_status"] = message
        self.save_scheduler_state()
        self.logger.info(
            "[SCHEDULER] %s",
            message,
        )

    def execute_fight(self, candidate) -> bool:
        before = self.get_character()
        hp_before = as_int(before.get("hp"))
        monster_id = as_int(candidate.monster.get("id"))

        result = super().execute_fight(candidate)

        if result:
            after = self.get_character()
            hp_after = as_int(after.get("hp"))
            self.record_successful_damage(
                monster_id,
                max(0, hp_before - hp_after),
            )

        return result

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "smart_combat_state": self.smart_state,
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_2_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_2_final_"
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
        bot = SmartCombatScheduler(
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
