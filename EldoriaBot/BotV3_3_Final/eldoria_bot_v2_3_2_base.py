from __future__ import annotations

import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_3_2_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (
    V22_FILE,
    V21_FILE,
    V161_FILE,
    V15_FILE,
    ENGINE_FILE,
):
    if not required.exists():
        raise RuntimeError(f"Required file is missing: {required}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v22_base",
    V22_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.2 base could not be loaded.")

v22 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v22
spec.loader.exec_module(v22)

v21 = v22.v21
v161 = v22.v161
base = v22.base
engine = v22.engine

for module in (v22, v21, v161, base, engine):
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
        OUTPUT_DIR / "eldoria_bot_v2_3_2_final_last_report.json"
    )
    module.LOG_COPY_FILE = (
        OUTPUT_DIR / "eldoria_bot_v2_3_2_final.log"
    )

for module in (v22, v21, v161, base):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_3_2_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_3_2_final.log",
        OUTPUT_DIR / "eldoria_bot_v2_3_2_final.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class StaminaBankScheduler(v22.SmartCombatScheduler):
    VERSION = "2.3.2-final-resource-bridge-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.stamina_bank_file = (
            STATE_DIR / "stamina_bank_state.json"
        )
        self.stamina_bank = engine.load_json(
            self.stamina_bank_file,
            {
                "recharging": False,
                "target": 0,
                "reason": "",
                "next_target_name": "",
                "last_log": "",
                "completed_recharges": 0,
            },
        )

    def save_stamina_bank(self) -> None:
        engine.save_json(
            self.stamina_bank_file,
            self.stamina_bank,
        )

    @staticmethod
    def candidate_name(row) -> str:
        candidate = row["candidate"]
        monster = candidate.monster
        return str(
            monster.get("name_en")
            or monster.get("name")
            or monster.get("code")
            or monster.get("id")
        )

    def best_beatable_next_target(self, states):
        beatable = [
            row
            for row in states
            if row.get("state")
            in {"ready", "heal", "resource"}
        ]

        if not beatable:
            return None

        beatable.sort(
            key=lambda row: (
                not row.get("quest_exact", False),
                not row.get("quest_related", False),
                row["candidate"].priority,
                -row["candidate"].gold_per_stamina,
                -row["candidate"].xp_per_stamina,
                row.get("risk_ratio", 999.0),
            )
        )
        return beatable[0]

    def requested_recharge_target(
        self,
        character: dict[str, Any],
        states,
    ) -> tuple[int, str, str]:
        stamina_max = max(
            1,
            as_int(character.get("stamina_max"), 50),
        )
        base_target = int(
            self.config["stamina_bank"][
                "base_recharge_target"
            ]
        )

        next_row = self.best_beatable_next_target(states)
        if next_row is None:
            return (
                min(stamina_max, base_target),
                "restore the Stamina bank",
                "",
            )

        fight_cost = max(
            1,
            as_int(next_row.get("stamina_target"), 1),
        )
        target = min(
            stamina_max,
            max(base_target, fight_cost),
        )
        name = self.candidate_name(next_row)

        if fight_cost > base_target:
            reason = (
                f"prepare enough Stamina for {name}"
            )
        else:
            reason = (
                f"restore the Stamina bank before {name}"
            )

        return target, reason, name

    def update_stamina_bank(
        self,
        character: dict[str, Any],
        states,
    ) -> bool:
        stamina = max(
            0,
            as_int(character.get("stamina")),
        )
        trigger = int(
            self.config["stamina_bank"][
                "recharge_trigger"
            ]
        )

        recharging = bool(
            self.stamina_bank.get("recharging")
        )

        # Enter recharge mode only after the bank has been drained,
        # or when an exact beatable Quest needs more Stamina than current.
        exact_resource = [
            row
            for row in states
            if row.get("quest_exact")
            and row.get("state") == "resource"
        ]

        should_enter = stamina <= trigger
        if exact_resource:
            should_enter = True

        if should_enter and not recharging:
            target, reason, name = (
                self.requested_recharge_target(
                    character,
                    states,
                )
            )
            self.stamina_bank.update(
                {
                    "recharging": True,
                    "target": target,
                    "reason": reason,
                    "next_target_name": name,
                    "last_log": "",
                }
            )
            self.save_stamina_bank()
            recharging = True

        if not recharging:
            return False

        # Recalculate upward when a newly available Quest needs more
        # than the current target. Never lower the target mid-recharge.
        new_target, reason, name = (
            self.requested_recharge_target(
                character,
                states,
            )
        )
        old_target = max(
            1,
            as_int(self.stamina_bank.get("target"), 1),
        )

        if new_target > old_target:
            self.stamina_bank["target"] = new_target
            self.stamina_bank["reason"] = reason
            self.stamina_bank["next_target_name"] = name
            self.stamina_bank["last_log"] = ""
            self.save_stamina_bank()
            old_target = new_target

        if stamina >= old_target:
            self.stamina_bank.update(
                {
                    "recharging": False,
                    "target": 0,
                    "reason": "",
                    "next_target_name": "",
                    "last_log": "",
                    "completed_recharges": (
                        as_int(
                            self.stamina_bank.get(
                                "completed_recharges"
                            )
                        )
                        + 1
                    ),
                }
            )
            self.save_stamina_bank()
            self.logger.info(
                "[STAMINA] Bank ready | STM %s | combat resumes.",
                stamina,
            )
            return False

        return True

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

        if self.update_stamina_bank(
            character,
            states,
        ):
            return None, states

        # Recharge may have completed during this same cycle.
        # Recalculate once so the best Quest starts immediately.
        return super().choose_action(
            character,
            objectives,
            material_needs,
        )

    def normalize_resource_state(
        self,
        pending,
    ) -> dict[str, Any] | None:
        if not isinstance(pending, dict):
            return None

        normalized = dict(pending)

        # V2.1 used hp_target. V2.2+ uses required_hp.
        # Keep both aliases so inherited and current helpers agree.
        required_hp = as_int(
            normalized.get(
                "required_hp",
                normalized.get("hp_target"),
            ),
            0,
        )
        hp_target = as_int(
            normalized.get(
                "hp_target",
                normalized.get("required_hp"),
            ),
            required_hp,
        )

        if required_hp <= 0:
            required_hp = hp_target
        if hp_target <= 0:
            hp_target = required_hp

        normalized["required_hp"] = max(
            0,
            required_hp,
        )
        normalized["hp_target"] = max(
            0,
            hp_target,
        )
        normalized["hp_short"] = max(
            0,
            as_int(normalized.get("hp_short"), 0),
        )
        normalized["stamina_target"] = max(
            0,
            as_int(
                normalized.get("stamina_target"),
                0,
            ),
        )
        normalized["stamina_short"] = max(
            0,
            as_int(
                normalized.get("stamina_short"),
                0,
            ),
        )
        normalized["mp_target"] = max(
            0,
            as_int(normalized.get("mp_target"), 0),
        )
        normalized["mp_short"] = max(
            0,
            as_int(normalized.get("mp_short"), 0),
        )

        return normalized

    def try_quest_resources(
        self,
        pending,
        character: dict[str, Any],
    ) -> bool:
        state = self.normalize_resource_state(
            pending
        )
        if state is None:
            return False

        hp_target = state["required_hp"]
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )

        # A strengthen-only target must never consume potions.
        if hp_target > hp_max:
            return False

        if (
            state["hp_short"] > 0
            and hp_target > 0
        ):
            used = self.safe_step(
                "Quest HP Potion",
                lambda: self.use_hp_potions_until_safe(
                    hp_target,
                    high_priority=True,
                ),
                False,
            )
            if used:
                return True

        # Natural Stamina banking remains intentional while recharging.
        if self.stamina_bank.get("recharging"):
            return False

        if state["stamina_short"] > 0:
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

    def active_world_boss(self, objectives):
        if self.stamina_bank.get("recharging"):
            return None
        return super().active_world_boss(objectives)

    def run_dungeon_autopilot(
        self,
        has_urgent_quests: bool,
    ) -> bool:
        if self.stamina_bank.get("recharging"):
            return False
        return super().run_dungeon_autopilot(
            has_urgent_quests=has_urgent_quests,
        )

    def log_scheduler_status(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        if self.stamina_bank.get("recharging"):
            stamina = as_int(character.get("stamina"))
            target = max(
                1,
                as_int(self.stamina_bank.get("target"), 20),
            )
            name = str(
                self.stamina_bank.get("next_target_name")
                or "next combat cycle"
            )
            message = (
                f"Recharging Stamina | "
                f"STM {stamina}/{target} | next: {name}"
            )

            if self.stamina_bank.get("last_log") == message:
                return

            self.stamina_bank["last_log"] = message
            self.save_stamina_bank()
            self.logger.info(
                "[STAMINA] %s",
                message,
            )
            return

        super().log_scheduler_status(
            pending,
            character,
        )

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "stamina_bank_state": self.stamina_bank,
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_3_2_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_3_2_final_"
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
        bot = StaminaBankScheduler(
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
