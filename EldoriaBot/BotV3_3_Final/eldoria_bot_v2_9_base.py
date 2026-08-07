from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V281_FILE = SCRIPT_DIR / "eldoria_bot_v2_8_1_base.py"
V271_FILE = SCRIPT_DIR / "eldoria_bot_v2_7_1_base.py"
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
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_9_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_9_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v2_9_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

for required in (
    V281_FILE,
    V271_FILE,
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
    "eldoria_v281_base",
    V281_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.8.1 base could not be loaded.")

v281 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v281
spec.loader.exec_module(v281)

v271 = v281.v271
v27 = v281.v27
v26 = v281.v26
v25 = v281.v25
v24 = v281.v24
v232 = v281.v232
v22 = v281.v22
v21 = v281.v21
v161 = v281.v161
base = v281.base
engine = v281.engine

for module in (
    v281,
    v271,
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
        OUTPUT_DIR / "eldoria_bot_v2_9_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v281,
    v271,
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

# Inherited transparent writer resolves these module globals.
v27.LIVE_LOG_FILE = LIVE_LOG_FILE
v27.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE
v271.LIVE_LOG_FILE = LIVE_LOG_FILE
v271.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE
v281.LIVE_LOG_FILE = LIVE_LOG_FILE
v281.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE


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

    logger = logging.getLogger("eldoria_bot_v2_9_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_9_final.log",
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


class GuaranteedProgressQuestDirector(v281.RootQuestOrchestrator):
    VERSION = "2.9-final-guaranteed-progress-quest-director-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.guaranteed_file = (
            STATE_DIR / "guaranteed_progress_director_state.json"
        )
        self.guaranteed = engine.load_json(
            self.guaranteed_file,
            {
                "schema_version": 1,
                "objective_pauses": {},
                "last_priority_signature": "",
                "last_priority_at": 0.0,
                "last_audit_signature": "",
                "last_audit_at": 0.0,
                "priority_switches": 0,
                "expensive_loot_pauses": 0,
            },
        )

        if not isinstance(self.guaranteed, dict):
            self.guaranteed = {}

        for key, default in {
            "schema_version": 1,
            "objective_pauses": {},
            "last_priority_signature": "",
            "last_priority_at": 0.0,
            "last_audit_signature": "",
            "last_audit_at": 0.0,
            "priority_switches": 0,
            "expensive_loot_pauses": 0,
        }.items():
            self.guaranteed.setdefault(key, default)

        if not isinstance(
            self.guaranteed.get("objective_pauses"),
            dict,
        ):
            self.guaranteed["objective_pauses"] = {}

        self._priority_explanation = ""
        self._target_audit_signature = ""
        self.save_guaranteed()

    def save_guaranteed(self) -> None:
        engine.save_json(
            self.guaranteed_file,
            self.guaranteed,
        )

    # ----------------------------------------------------------
    # Objective probability and expected completion time
    # ----------------------------------------------------------

    def objective_paused(
        self,
        objective,
    ) -> bool:
        key = self.objective_key(objective)
        until = as_float(
            self.guaranteed[
                "objective_pauses"
            ].get(key),
            0.0,
        )

        if until <= 0:
            return False

        if time.time() >= until:
            self.guaranteed[
                "objective_pauses"
            ].pop(key, None)
            self.save_guaranteed()
            return False

        return True

    def pause_objective(
        self,
        objective,
        seconds: float,
        reason: str,
    ) -> None:
        key = self.objective_key(objective)
        self.guaranteed["objective_pauses"][key] = (
            time.time() + max(60.0, seconds)
        )
        self.guaranteed["expensive_loot_pauses"] = (
            as_int(
                self.guaranteed.get(
                    "expensive_loot_pauses"
                ),
                0,
            )
            + 1
        )
        self.save_guaranteed()

        self.logger.info(
            "[QUEST PAUSE] %s is paused temporarily: %s.",
            objective.quest_name,
            reason,
        )

    def actual_loot_progress_rate(
        self,
        objective,
        monster_id: int,
        fallback: float,
    ) -> float:
        key = self.audit_key(
            objective,
            monster_id,
        )
        record = self.orchestrator[
            "progress_audit"
        ].get(key, {})

        if not isinstance(record, dict):
            return fallback

        wins = as_int(record.get("wins"), 0)
        progress = as_int(
            record.get("progress_events"),
            0,
        )
        dry_streak = as_int(
            record.get("no_progress_streak"),
            0,
        )

        if wins <= 0:
            return fallback

        # Bayesian-style smoothing prevents one random result from
        # becoming absolute truth, while repeated dry wins matter.
        observed = progress / wins
        smoothed = (
            observed * wins + fallback * 2.0
        ) / (wins + 2.0)

        if dry_streak > 0:
            smoothed /= 1.0 + dry_streak * 0.75

        return max(
            float(
                self.config["guaranteed_progress"][
                    "minimum_loot_progress_rate"
                ]
            ),
            smoothed,
        )

    def progress_per_fight(
        self,
        objective,
        row,
    ) -> float:
        objective_type = str(
            objective.objective_type or ""
        ).lower()

        if objective_type == "kill":
            return 1.0

        if objective_type == "loot":
            monster_id = as_int(
                row["candidate"].monster.get("id"),
                0,
            )
            fallback = self.expected_loot_items(
                row["candidate"].monster
            )
            return self.actual_loot_progress_rate(
                objective,
                monster_id,
                fallback,
            )

        return 1.0

    def row_cycle_seconds(
        self,
        row,
        character: dict[str, Any],
    ) -> tuple[float, float]:
        required_hp = max(
            0,
            as_int(row.get("required_hp"), 0),
        )
        required_stamina = max(
            0,
            as_int(row.get("stamina_target"), 0),
        )

        first_wait = max(
            self.hp_wait_seconds(
                character,
                required_hp,
            ),
            self.stamina_wait_seconds(
                character,
                required_stamina,
            ),
        )

        damage = max(
            0.0,
            as_float(
                row.get("estimate"),
                row["candidate"].predicted_damage,
            ),
        )
        hp_regen = as_float(
            character.get("hp_regen_per_hour"),
            0.0,
        )
        stamina_regen = as_float(
            character.get("stamina_regen_per_hour"),
            8.333333,
        )

        hp_recovery = (
            damage / hp_regen * 3600.0
            if damage > 0 and hp_regen > 0
            else 0.0
        )
        stamina_cost = max(
            1,
            as_int(row.get("stamina_target"), 1),
        )
        stamina_recovery = (
            stamina_cost / stamina_regen * 3600.0
            if stamina_regen > 0
            else 0.0
        )

        repeat_cycle = max(
            hp_recovery,
            stamina_recovery,
            float(
                self.config["guaranteed_progress"][
                    "minimum_fight_cycle_seconds"
                ]
            ),
        )
        return first_wait, repeat_cycle

    def objective_expected_seconds(
        self,
        objective,
        states,
        character: dict[str, Any],
    ) -> tuple[float, Any | None, float]:
        if objective.objective_type == "craft":
            # Craft housekeeping gets a chance, but a missing recipe or
            # materials must not monopolize the campaign.
            missing = sum(
                max(0, as_int(value))
                for value in self.cached_material_needs.values()
            )
            seconds = (
                60.0
                if missing <= 0
                else float(
                    self.config["guaranteed_progress"][
                        "blocked_craft_estimate_seconds"
                    ]
                )
            )
            return seconds, None, 1.0

        rows = self.matching_rows(
            objective,
            states,
        )
        if not rows:
            return float("inf"), None, 0.0

        best_total = float("inf")
        best_row = None
        best_rate = 0.0

        for row in rows:
            if row.get("state") == "strengthen":
                continue

            rate = self.progress_per_fight(
                objective,
                row,
            )
            if rate <= 0:
                continue

            fights = max(
                1,
                math.ceil(
                    objective.remaining / rate
                ),
            )
            first_wait, repeat_cycle = (
                self.row_cycle_seconds(
                    row,
                    character,
                )
            )
            total = (
                first_wait
                + max(0, fights - 1)
                * repeat_cycle
            )

            overlap = max(
                0,
                as_int(
                    getattr(
                        row["candidate"],
                        "quest_overlap",
                        0,
                    ),
                    0,
                )
                - 1,
            )
            total /= (
                1.0
                + overlap
                * float(
                    self.config["guaranteed_progress"][
                        "overlap_time_discount"
                    ]
                )
            )

            if total < best_total:
                best_total = total
                best_row = row
                best_rate = rate

        return best_total, best_row, best_rate

    def deadline_multiplier(
        self,
        objective,
    ) -> float:
        seconds = objective.seconds_to_expiry()

        if seconds is None or seconds <= 0:
            return 1.0
        if seconds <= 2 * 3600:
            return 0.05
        if seconds <= 6 * 3600:
            return 0.15
        if seconds <= 24 * 3600:
            return 0.50
        return 0.85

    def objective_priority_record(
        self,
        objective,
        states,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        expected, best_row, rate = (
            self.objective_expected_seconds(
                objective,
                states,
                character,
            )
        )
        paused = self.objective_paused(
            objective
        )

        effective = expected
        if math.isfinite(effective):
            effective *= self.deadline_multiplier(
                objective
            )

            # Guaranteed Kill progress receives a small but decisive
            # preference over random Loot when completion time is close.
            if objective.objective_type == "kill":
                effective *= float(
                    self.config["guaranteed_progress"][
                        "guaranteed_kill_multiplier"
                    ]
                )
            elif objective.objective_type == "loot":
                effective *= float(
                    self.config["guaranteed_progress"][
                        "random_loot_multiplier"
                    ]
                )

        if paused:
            effective = float("inf")

        return {
            "objective": objective,
            "expected": expected,
            "effective": effective,
            "best_row": best_row,
            "rate": rate,
            "paused": paused,
        }

    def choose_campaign_objective(
        self,
        objectives,
        states,
        character: dict[str, Any],
    ):
        supported = self.supported_campaign_objectives(
            objectives
        )
        if not supported:
            self.clear_completed_campaign()
            return None

        records = [
            self.objective_priority_record(
                objective,
                states,
                character,
            )
            for objective in supported
        ]

        available = [
            record
            for record in records
            if not record["paused"]
        ]
        if not available:
            available = records

        available.sort(
            key=lambda record: (
                record["effective"],
                self.QUEST_TYPE_RANK.get(
                    record["objective"].quest_type,
                    9,
                ),
                record["objective"].remaining,
                record["objective"].quest_name,
            )
        )
        best = available[0]
        selected = best["objective"]

        current = self.current_campaign_objective(
            supported
        )
        current_record = next(
            (
                record
                for record in records
                if current is not None
                and self.objective_key(
                    record["objective"]
                )
                == self.objective_key(current)
            ),
            None,
        )

        switch = current is None

        if current_record is not None:
            if current_record["paused"]:
                switch = True
            elif (
                selected.objective_type == "kill"
                and current.objective_type == "loot"
                and best["effective"]
                < current_record["effective"]
            ):
                switch = True
            elif (
                best["effective"]
                < current_record["effective"]
                * float(
                    self.config["guaranteed_progress"][
                        "campaign_switch_ratio"
                    ]
                )
            ):
                switch = True

        if switch:
            reason = (
                "selected by guaranteed progress and estimated "
                "completion time"
            )
            self.set_campaign(
                selected,
                reason,
            )
            self.guaranteed["priority_switches"] = (
                as_int(
                    self.guaranteed.get(
                        "priority_switches"
                    ),
                    0,
                )
                + 1
            )
            self.save_guaranteed()
        elif current is not None:
            selected = current
            self.campaign["active_remaining"] = (
                current.remaining
            )
            self.save_campaign()

        chosen_record = next(
            (
                record
                for record in records
                if self.objective_key(
                    record["objective"]
                )
                == self.objective_key(selected)
            ),
            best,
        )

        expected_text = (
            v27.format_duration(
                chosen_record["expected"]
            )
            if math.isfinite(
                chosen_record["expected"]
            )
            else "blocked"
        )
        self._priority_explanation = (
            f"{selected.quest_name}: "
            f"{selected.objective_type} | "
            f"{selected.remaining} remaining | "
            f"estimated completion {expected_text}"
        )
        self.log_priority_once()
        return selected

    def log_priority_once(self) -> None:
        message = str(
            self._priority_explanation or ""
        ).strip()
        if not message:
            return

        signature = "|".join(
            [
                self.primary_key(),
                message.split(
                    "| estimated completion"
                )[0],
            ]
        )
        now = time.time()
        heartbeat = float(
            self.config["guaranteed_progress"][
                "priority_log_heartbeat_seconds"
            ]
        )

        if (
            signature
            == self.guaranteed.get(
                "last_priority_signature"
            )
            and now
            - as_float(
                self.guaranteed.get(
                    "last_priority_at"
                ),
                0.0,
            )
            < heartbeat
        ):
            return

        self.guaranteed[
            "last_priority_signature"
        ] = signature
        self.guaranteed[
            "last_priority_at"
        ] = now
        self.save_guaranteed()
        self.logger.info(
            "[QUEST PRIORITY] %s.",
            message,
        )

    # ----------------------------------------------------------
    # Log throttling
    # ----------------------------------------------------------

    def select_target_row(
        self,
        objective,
        rows,
    ):
        selected = super().select_target_row(
            objective,
            rows,
        )

        if selected is None:
            self._target_audit_signature = (
                f"{self.objective_key(objective)}|none"
            )
            return None

        ready_count = sum(
            1
            for row in rows
            if row.get("state") == "ready"
        )
        self._target_audit_signature = "|".join(
            [
                self.objective_key(objective),
                str(
                    selected["candidate"].monster.get(
                        "id"
                    )
                ),
                str(ready_count),
                str(selected.get("state") or ""),
                str(
                    as_int(
                        selected.get("required_hp"),
                        0,
                    )
                ),
            ]
        )
        return selected

    def log_target_audit_once(self) -> None:
        message = str(
            self._target_audit_message or ""
        ).strip()
        if not message:
            return

        signature = (
            self._target_audit_signature
            or self.primary_key()
        )
        now = time.time()
        heartbeat = float(
            self.config["guaranteed_progress"][
                "target_audit_heartbeat_seconds"
            ]
        )

        if (
            signature
            == self.guaranteed.get(
                "last_audit_signature"
            )
            and now
            - as_float(
                self.guaranteed.get(
                    "last_audit_at"
                ),
                0.0,
            )
            < heartbeat
        ):
            return

        self.guaranteed[
            "last_audit_signature"
        ] = signature
        self.guaranteed[
            "last_audit_at"
        ] = now
        self.save_guaranteed()
        self.logger.info(
            "[TARGET AUDIT] %s",
            message,
        )

    def should_log_plan(
        self,
        signature: str,
        *,
        wait: bool = False,
    ) -> bool:
        if wait:
            parts = signature.split("|")
            if len(parts) >= 7:
                # Ignore changing HP and STM display values. A change in
                # Quest, target, state or requirement still logs instantly.
                signature = "|".join(parts[:5])

        return super().should_log_plan(
            signature,
            wait=wait,
        )

    # A ready selected action must not be preceded by an unrelated
    # waiting target from another row.
    def pending_quest(self, states):
        if (
            isinstance(self._selected_row, dict)
            and self._selected_row.get("state")
            == "ready"
        ):
            return None
        return super().pending_quest(states)

    # ----------------------------------------------------------
    # Expensive random Loot protection
    # ----------------------------------------------------------

    def expensive_recovery_seconds(
        self,
        selected_row,
    ) -> float:
        character = (
            self._scheduler_character
            if isinstance(
                self._scheduler_character,
                dict,
            )
            else {}
        )
        damage = max(
            0.0,
            as_float(
                selected_row.get("estimate"),
                selected_row[
                    "candidate"
                ].predicted_damage,
            ),
        )
        regen = as_float(
            character.get("hp_regen_per_hour"),
            0.0,
        )
        if damage <= 0 or regen <= 0:
            return 0.0
        return damage / regen * 3600.0

    def record_verified_progress(
        self,
        *,
        objective,
        monster_id: int,
        monster_name: str,
        before_remaining: int,
        after_remaining: int | None,
        fight_won: bool,
        selected_row,
    ) -> None:
        super().record_verified_progress(
            objective=objective,
            monster_id=monster_id,
            monster_name=monster_name,
            before_remaining=before_remaining,
            after_remaining=after_remaining,
            fight_won=fight_won,
            selected_row=selected_row,
        )

        if (
            objective is None
            or not fight_won
            or objective.objective_type != "loot"
            or after_remaining is None
            or after_remaining < before_remaining
        ):
            return

        recovery = self.expensive_recovery_seconds(
            selected_row
        )
        threshold = float(
            self.config["guaranteed_progress"][
                "expensive_no_progress_seconds"
            ]
        )

        if recovery < threshold:
            return

        self.pause_objective(
            objective,
            float(
                self.config["guaranteed_progress"][
                    "expensive_loot_pause_seconds"
                ]
            ),
            (
                f"a verified win produced no Loot progress and "
                f"costs about {v27.format_duration(recovery)} "
                f"of HP recovery"
            ),
        )

    # ----------------------------------------------------------
    # Secondary Craft backoff
    # ----------------------------------------------------------

    def execute_secondary_noncombat(self) -> bool:
        changed = super().execute_secondary_noncombat()

        if not changed:
            self.orchestrator[
                "secondary_craft_cooldown_until"
            ] = (
                time.time()
                + float(
                    self.config["guaranteed_progress"][
                        "blocked_craft_retry_seconds"
                    ]
                )
            )
            self.save_orchestrator()

        return changed

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "guaranteed_progress_state": (
                    self.guaranteed
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_9_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_9_final_"
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
        bot = GuaranteedProgressQuestDirector(
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
