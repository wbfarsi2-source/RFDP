from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V27_FILE = SCRIPT_DIR / "eldoria_bot_v2_7_base.py"
V26_FILE = SCRIPT_DIR / "eldoria_bot_v2_6_base.py"
V25_FILE = SCRIPT_DIR / "eldoria_bot_v2_5_base.py"
V24_FILE = SCRIPT_DIR / "eldoria_bot_v2_4_base.py"
V232_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_base.py"
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_7_1_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_7_1_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v2_7_1_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

for required in (
    V27_FILE,
    V26_FILE,
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
    "eldoria_v27_base",
    V27_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.7 base could not be loaded.")

v27 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v27
spec.loader.exec_module(v27)

v26 = v27.v26
v25 = v27.v25
v24 = v27.v24
v232 = v27.v232
v22 = v27.v22
v21 = v27.v21
v161 = v27.v161
base = v27.base
engine = v27.engine

for module in (
    v27,
    v26,
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
        OUTPUT_DIR / "eldoria_bot_v2_7_1_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v27,
    v26,
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

# The inherited writer resolves these globals in the V2.7 module.
v27.LIVE_LOG_FILE = LIVE_LOG_FILE
v27.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE


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

    logger = logging.getLogger("eldoria_bot_v2_7_1_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_7_1_final.log",
        LIVE_LOG_FILE,
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


class LootAwareQuestDirector(v27.TransparentQuestDirector):
    VERSION = "2.7.1-final-loot-aware-opportunity-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.loot_fix_file = (
            STATE_DIR / "loot_aware_director_state.json"
        )
        self.loot_fix = engine.load_json(
            self.loot_fix_file,
            {
                "schema_version": 1,
                "last_opportunity_skip": "",
                "last_resource_note": "",
                "loot_target_changes": 0,
            },
        )

        if not isinstance(self.loot_fix, dict):
            self.loot_fix = {}

        self.loot_fix.setdefault("schema_version", 1)
        self.loot_fix.setdefault("last_opportunity_skip", "")
        self.loot_fix.setdefault("last_resource_note", "")
        self.loot_fix.setdefault("loot_target_changes", 0)

        self._opportunity_skip_reason = ""
        self._resource_acceleration_note = ""
        self.save_loot_fix()

    def save_loot_fix(self) -> None:
        engine.save_json(
            self.loot_fix_file,
            self.loot_fix,
        )

    # ----------------------------------------------------------
    # Loot efficiency
    # ----------------------------------------------------------

    @staticmethod
    def normalized_drop_chance(value: Any) -> float:
        chance = max(0.0, as_float(value, 0.0))
        if chance > 1.0:
            chance /= 100.0
        return min(1.0, chance)

    def expected_loot_items(
        self,
        monster: dict[str, Any],
    ) -> float:
        expected = 0.0

        guaranteed = monster.get("guaranteed_drops")
        if isinstance(guaranteed, list):
            for drop in guaranteed:
                if not isinstance(drop, dict):
                    continue
                expected += max(
                    1.0,
                    as_float(drop.get("qty"), 1.0),
                )

        chance_drops = monster.get("chance_drops")
        if isinstance(chance_drops, list):
            for drop in chance_drops:
                if not isinstance(drop, dict):
                    continue
                chance = self.normalized_drop_chance(
                    drop.get("chance")
                )
                quantity = max(
                    1.0,
                    as_float(drop.get("qty"), 1.0),
                )
                expected += chance * quantity

        # The API may omit drops for some monsters.
        # Keep a small neutral fallback rather than declaring zero.
        return max(
            expected,
            float(
                self.config["loot_aware"][
                    "unknown_drop_expectation"
                ]
            ),
        )

    def loot_row_score(
        self,
        row,
        objective,
    ) -> float:
        candidate = row["candidate"]
        monster = candidate.monster
        expected_loot = self.expected_loot_items(
            monster
        )
        damage = max(
            1.0,
            as_float(
                row.get("estimate"),
                candidate.predicted_damage,
            ),
        )
        stamina = max(
            1,
            as_int(row.get("stamina_target"), 1),
        )
        overlap = as_int(
            getattr(
                candidate,
                "quest_overlap",
                0,
            ),
            0,
        )

        return (
            expected_loot
            * float(
                self.config["loot_aware"][
                    "loot_progress_weight"
                ]
            )
            / damage
            + candidate.xp_per_stamina
            * float(
                self.config["loot_aware"][
                    "loot_xp_weight"
                ]
            )
            + candidate.gold_per_stamina
            * float(
                self.config["loot_aware"][
                    "loot_gold_weight"
                ]
            )
            + overlap
            * float(
                self.config["loot_aware"][
                    "loot_overlap_weight"
                ]
            )
            - row.get("risk_ratio", 999.0)
            * float(
                self.config["loot_aware"][
                    "loot_risk_penalty"
                ]
            )
            - stamina
            * float(
                self.config["loot_aware"][
                    "loot_stamina_penalty"
                ]
            )
        )

    def loot_wait_efficiency(
        self,
        row,
        character: dict[str, Any],
    ) -> float:
        required_hp = as_int(
            row.get("required_hp"),
            0,
        )
        required_stamina = as_int(
            row.get("stamina_target"),
            0,
        )

        wait = max(
            self.hp_wait_seconds(
                character,
                required_hp,
            ),
            self.stamina_wait_seconds(
                character,
                required_stamina,
            ),
        )
        expected = self.expected_loot_items(
            row["candidate"].monster
        )
        return wait / max(
            expected,
            float(
                self.config["loot_aware"][
                    "minimum_expected_loot"
                ]
            ),
        )

    # For LOOT any, choose fastest expected loot progress.
    # Kill-any behavior remains strongest-safe from V2.6.
    def select_target_row(
        self,
        objective: v25.ProfessionalQuestObjective,
        rows,
    ):
        if (
            objective.objective_type != "loot"
            or normalize(objective.target)
            not in {"", "any"}
        ):
            return super().select_target_row(
                objective,
                rows,
            )

        if not rows:
            return None

        ready = [
            row
            for row in rows
            if row.get("state") == "ready"
        ]

        if ready:
            ready.sort(
                key=lambda row: (
                    -self.loot_row_score(
                        row,
                        objective,
                    ),
                    row.get("risk_ratio", 999.0),
                    row.get("required_hp", 10**9),
                )
            )
            selected = ready[0]
            self.loot_fix["loot_target_changes"] = (
                as_int(
                    self.loot_fix.get(
                        "loot_target_changes"
                    ),
                    0,
                )
                + 1
            )
            self.save_loot_fix()
            return selected

        beatable = [
            row
            for row in rows
            if row.get("state")
            in {"heal", "resource"}
        ]

        if beatable:
            character = (
                self._scheduler_character
                if isinstance(
                    self._scheduler_character,
                    dict,
                )
                else {}
            )
            beatable.sort(
                key=lambda row: (
                    self.loot_wait_efficiency(
                        row,
                        character,
                    ),
                    -self.loot_row_score(
                        row,
                        objective,
                    ),
                    row.get("risk_ratio", 999.0),
                )
            )
            return beatable[0]

        return super().select_target_row(
            objective,
            rows,
        )

    # ----------------------------------------------------------
    # Dynamic opportunity budget
    # ----------------------------------------------------------

    def opportunity_delay_budget(
        self,
        primary_pending,
        character: dict[str, Any],
    ) -> float:
        required_hp = as_int(
            primary_pending.get("required_hp"),
            0,
        )
        required_stamina = as_int(
            primary_pending.get("stamina_target"),
            0,
        )
        current_wait = max(
            self.hp_wait_seconds(
                character,
                required_hp,
            ),
            self.stamina_wait_seconds(
                character,
                required_stamina,
            ),
        )

        base = float(
            self.config["transparent_logs"][
                "maximum_opportunity_delay_seconds"
            ]
        )
        ratio = float(
            self.config["loot_aware"][
                "opportunity_wait_budget_ratio"
            ]
        )
        cap = float(
            self.config["loot_aware"][
                "opportunity_wait_budget_cap_seconds"
            ]
        )

        return max(
            base,
            min(cap, current_wait * ratio),
        )

    def dynamic_hp_floor_ratio(
        self,
        character: dict[str, Any],
    ) -> float:
        hp = max(
            0,
            as_int(character.get("hp"), 0),
        )
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        current_ratio = hp / hp_max

        configured = float(
            self.config["transparent_logs"][
                "minimum_hp_after_opportunity_ratio"
            ]
        )
        absolute_floor = float(
            self.config["loot_aware"][
                "absolute_opportunity_hp_floor_ratio"
            ]
        )
        allowed_drop = float(
            self.config["loot_aware"][
                "maximum_opportunity_hp_ratio_drop"
            ]
        )

        return max(
            absolute_floor,
            min(
                configured,
                max(
                    absolute_floor,
                    current_ratio - allowed_drop,
                ),
            ),
        )

    def find_opportunity(
        self,
        primary_pending,
        states,
        character: dict[str, Any],
        primary_objective,
    ):
        self._opportunity_skip_reason = ""

        if not isinstance(primary_pending, dict):
            self._opportunity_skip_reason = (
                "Primary Quest has no resource wait."
            )
            return None

        self.reset_opportunity_if_needed(
            primary_pending
        )

        if self.director.get("opportunity_used"):
            self._opportunity_skip_reason = (
                "One side action was already used for this wait window."
            )
            return None

        delay_budget = self.opportunity_delay_budget(
            primary_pending,
            character,
        )
        maximum_risk = float(
            self.config["transparent_logs"][
                "maximum_opportunity_risk_ratio"
            ]
        )
        minimum_hp_ratio = self.dynamic_hp_floor_ratio(
            character
        )

        hp = as_int(character.get("hp"), 0)
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        primary_candidate = primary_pending.get(
            "candidate"
        )
        primary_monster_id = (
            as_int(
                primary_candidate.monster.get("id"),
                0,
            )
            if primary_candidate is not None
            else 0
        )

        choices = []
        rejection_reasons = []
        ready_with_parallel = 0

        for row in states:
            if row.get("state") != "ready":
                continue

            candidate = row["candidate"]
            monster = candidate.monster
            monster_id = as_int(
                monster.get("id"),
                0,
            )

            if (
                monster_id <= 0
                or monster_id == primary_monster_id
                or self.is_boss(monster)
            ):
                continue

            secondary = self.parallel_objectives(
                row,
                primary_objective,
            )
            if not secondary:
                continue

            ready_with_parallel += 1
            name = self.monster_name(candidate)
            risk = as_float(
                row.get("risk_ratio"),
                999.0,
            )

            if risk > maximum_risk:
                rejection_reasons.append(
                    (
                        risk - maximum_risk,
                        f"{name} risk {risk:.2f} exceeds "
                        f"the side-action limit {maximum_risk:.2f}",
                    )
                )
                continue

            estimate = max(
                0.0,
                as_float(
                    row.get("estimate"),
                    candidate.predicted_damage,
                ),
            )
            hp_after = hp - math.ceil(
                estimate
                * float(
                    self.config[
                        "transparent_logs"
                    ][
                        "opportunity_damage_safety"
                    ]
                )
            )
            projected_ratio = hp_after / hp_max

            if projected_ratio < minimum_hp_ratio:
                rejection_reasons.append(
                    (
                        minimum_hp_ratio - projected_ratio,
                        f"{name} would leave HP near "
                        f"{projected_ratio:.0%}, below the "
                        f"dynamic floor {minimum_hp_ratio:.0%}",
                    )
                )
                continue

            added_delay = self.added_primary_delay(
                primary_pending,
                row,
                character,
            )

            if not math.isfinite(added_delay):
                rejection_reasons.append(
                    (
                        999999,
                        f"{name} has an unknown recovery delay",
                    )
                )
                continue

            if added_delay > delay_budget:
                rejection_reasons.append(
                    (
                        added_delay - delay_budget,
                        f"{name} would delay the primary Quest by "
                        f"{v27.format_duration(added_delay)}, "
                        f"budget is {v27.format_duration(delay_budget)}",
                    )
                )
                continue

            score = self.opportunity_score(
                row,
                primary_objective,
                added_delay,
            )
            choices.append(
                (
                    score,
                    added_delay,
                    row,
                )
            )

        if choices:
            choices.sort(
                key=lambda item: (
                    -item[0],
                    item[1],
                    -item[2]["candidate"].xp_per_stamina,
                )
            )
            return choices[0]

        if ready_with_parallel == 0:
            self._opportunity_skip_reason = (
                "No ready side Fight currently advances another Quest."
            )
        elif rejection_reasons:
            rejection_reasons.sort(
                key=lambda item: item[0]
            )
            self._opportunity_skip_reason = (
                rejection_reasons[0][1]
            )
        else:
            self._opportunity_skip_reason = (
                "No side action passed the safety checks."
            )

        return None

    def log_opportunity_skip_once(self) -> None:
        reason = str(
            self._opportunity_skip_reason or ""
        ).strip()
        if not reason:
            return

        signature = "|".join(
            [
                self.primary_key(),
                reason,
            ]
        )
        if (
            signature
            == self.loot_fix.get(
                "last_opportunity_skip"
            )
        ):
            return

        self.loot_fix[
            "last_opportunity_skip"
        ] = signature
        self.save_loot_fix()
        self.logger.info(
            "[OPPORTUNITY SKIP] %s.",
            reason,
        )

    def try_quest_resources(
        self,
        pending,
        character: dict[str, Any],
    ) -> bool:
        used = super().try_quest_resources(
            pending,
            character,
        )

        if used:
            self._resource_acceleration_note = (
                "A recovery item or crafted Potion was used."
            )
            return True

        if isinstance(pending, dict):
            required_hp = as_int(
                pending.get(
                    "required_hp",
                    pending.get("hp_target"),
                ),
                0,
            )
            hp = as_int(character.get("hp"), 0)

            if required_hp > hp:
                self._resource_acceleration_note = (
                    "No HP recovery item was used in this cycle; "
                    "natural regeneration continues."
                )

        return False

    def log_resource_plan(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        super().log_resource_plan(
            pending,
            character,
        )
        self.log_opportunity_skip_once()

        note = str(
            self._resource_acceleration_note or ""
        ).strip()
        if not note:
            return

        signature = "|".join(
            [
                self.primary_key(),
                note,
            ]
        )
        if (
            signature
            == self.loot_fix.get(
                "last_resource_note"
            )
        ):
            return

        self.loot_fix["last_resource_note"] = signature
        self.save_loot_fix()
        self.logger.info(
            "[RECOVERY PLAN] %s",
            note,
        )

    def write_current_plan(
        self,
        *,
        step: str,
        row=None,
        character=None,
        details: str = "",
    ) -> None:
        super().write_current_plan(
            step=step,
            row=row,
            character=character,
            details=details,
        )

        extra = []
        if self._opportunity_skip_reason:
            extra.append(
                "Opportunity status: skipped"
            )
            extra.append(
                "Opportunity reason: "
                + self._opportunity_skip_reason
            )
        elif self._selected_role == "OPPORTUNITY":
            extra.append(
                "Opportunity status: selected"
            )
            extra.append(
                "Opportunity reason: "
                + self._opportunity_reason
            )

        if self._resource_acceleration_note:
            extra.append(
                "Recovery status: "
                + self._resource_acceleration_note
            )

        if not extra:
            return

        with CURRENT_PLAN_FILE.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "\nLOOT / OPPORTUNITY DIRECTOR\n"
            )
            for line in extra:
                handle.write(line + "\n")

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "loot_aware_director_state": (
                    self.loot_fix
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_7_1_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_7_1_final_"
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
        bot = LootAwareQuestDirector(
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
