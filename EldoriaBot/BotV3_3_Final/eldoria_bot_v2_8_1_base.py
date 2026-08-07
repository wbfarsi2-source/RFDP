from __future__ import annotations

import importlib.util
import math
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
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
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_8_1_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_8_1_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v2_8_1_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

for required in (
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
    "eldoria_v271_base",
    V271_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.7.1 base could not be loaded.")

v271 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v271
spec.loader.exec_module(v271)

v27 = v271.v27
v26 = v271.v26
v25 = v271.v25
v24 = v271.v24
v232 = v271.v232
v22 = v271.v22
v21 = v271.v21
v161 = v271.v161
base = v271.base
engine = v271.engine

for module in (
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
        OUTPUT_DIR / "eldoria_bot_v2_8_1_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
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

# Inherited transparent writer resolves these globals in V2.7.
v27.LIVE_LOG_FILE = LIVE_LOG_FILE
v27.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE
v271.LIVE_LOG_FILE = LIVE_LOG_FILE
v271.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE


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

    logger = logging.getLogger("eldoria_bot_v2_8_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_8_final.log",
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


class RootQuestOrchestrator(v271.LootAwareQuestDirector):
    VERSION = "2.8.1-final-quiet-root-quest-orchestrator-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.orchestrator_file = (
            STATE_DIR / "root_quest_orchestrator_state.json"
        )
        self.orchestrator = engine.load_json(
            self.orchestrator_file,
            {
                "schema_version": 1,
                "progress_audit": {},
                "target_penalties": {},
                "last_target_audit": "",
                "last_secondary_task": "",
                "secondary_craft_cooldown_until": 0.0,
                "verified_progress_events": 0,
                "verified_no_progress_events": 0,
                "secondary_actions": 0,
                "last_why_wait_signature": "",
                "last_why_wait_at": 0.0,
                "last_wait_opportunity_signature": "",
                "last_wait_opportunity_at": 0.0,
            },
        )

        if not isinstance(self.orchestrator, dict):
            self.orchestrator = {}

        for key, default in {
            "schema_version": 1,
            "progress_audit": {},
            "target_penalties": {},
            "last_target_audit": "",
            "last_secondary_task": "",
            "secondary_craft_cooldown_until": 0.0,
            "verified_progress_events": 0,
            "verified_no_progress_events": 0,
            "secondary_actions": 0,
            "last_why_wait_signature": "",
            "last_why_wait_at": 0.0,
            "last_wait_opportunity_signature": "",
            "last_wait_opportunity_at": 0.0,
        }.items():
            self.orchestrator.setdefault(key, default)

        if not isinstance(
            self.orchestrator.get("progress_audit"),
            dict,
        ):
            self.orchestrator["progress_audit"] = {}

        if not isinstance(
            self.orchestrator.get("target_penalties"),
            dict,
        ):
            self.orchestrator["target_penalties"] = {}

        self._secondary_noncombat = None
        self._secondary_noncombat_objective = None
        self._target_audit_message = ""
        self.save_orchestrator()

    def save_orchestrator(self) -> None:
        engine.save_json(
            self.orchestrator_file,
            self.orchestrator,
        )

    # ----------------------------------------------------------
    # Objective and progress identity
    # ----------------------------------------------------------

    def objective_remaining(
        self,
        key: str,
        objectives,
    ) -> int | None:
        for objective in objectives:
            if (
                isinstance(
                    objective,
                    v25.ProfessionalQuestObjective,
                )
                and self.objective_key(objective) == key
            ):
                return objective.remaining
        return None

    def audit_key(
        self,
        objective,
        monster_id: int,
    ) -> str:
        return (
            f"{self.objective_key(objective)}"
            f"|monster:{monster_id}"
        )

    def penalty_for(
        self,
        objective,
        monster_id: int,
    ) -> float:
        key = self.audit_key(
            objective,
            monster_id,
        )
        record = self.orchestrator[
            "target_penalties"
        ].get(key, {})
        if not isinstance(record, dict):
            return 0.0

        expires_at = as_float(
            record.get("expires_at"),
            0.0,
        )
        if expires_at and time.time() >= expires_at:
            self.orchestrator[
                "target_penalties"
            ].pop(key, None)
            self.save_orchestrator()
            return 0.0

        return max(
            0.0,
            as_float(record.get("penalty"), 0.0),
        )

    def dry_fight_threshold(
        self,
        row,
    ) -> int:
        expected = self.expected_loot_items(
            row["candidate"].monster
        )
        desired_expected_drops = float(
            self.config["root_orchestrator"][
                "expected_drops_before_penalty"
            ]
        )
        calculated = math.ceil(
            desired_expected_drops
            / max(
                expected,
                float(
                    self.config["loot_aware"][
                        "minimum_expected_loot"
                    ]
                ),
            )
        )
        return max(
            int(
                self.config["root_orchestrator"][
                    "minimum_dry_fights"
                ]
            ),
            min(
                int(
                    self.config["root_orchestrator"][
                        "maximum_dry_fights"
                    ]
                ),
                calculated,
            ),
        )

    # ----------------------------------------------------------
    # Root target selection:
    # 1. All legal candidate rows are evaluated.
    # 2. Ready target beats a waiting target.
    # 3. If all wait, ETA per expected Quest progress wins.
    # 4. Targets proven ineffective receive a temporary penalty.
    # ----------------------------------------------------------

    def loot_effective_score(
        self,
        row,
        objective,
        character: dict[str, Any],
    ) -> float:
        base_score = self.loot_row_score(
            row,
            objective,
        )
        monster_id = as_int(
            row["candidate"].monster.get("id"),
            0,
        )
        penalty = self.penalty_for(
            objective,
            monster_id,
        )

        wait_seconds = max(
            self.hp_wait_seconds(
                character,
                as_int(row.get("required_hp"), 0),
            ),
            self.stamina_wait_seconds(
                character,
                as_int(row.get("stamina_target"), 0),
            ),
        )
        expected = self.expected_loot_items(
            row["candidate"].monster
        )
        wait_cost = (
            wait_seconds
            / max(
                expected,
                float(
                    self.config["loot_aware"][
                        "minimum_expected_loot"
                    ]
                ),
            )
            / 60.0
            * float(
                self.config["root_orchestrator"][
                    "loot_wait_minute_penalty"
                ]
            )
        )

        readiness_bonus = (
            float(
                self.config["root_orchestrator"][
                    "ready_target_bonus"
                ]
            )
            if row.get("state") == "ready"
            else 0.0
        )

        return (
            base_score
            + readiness_bonus
            - wait_cost
            - penalty
        )

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
            self._target_audit_message = (
                "No legal monster candidate is currently available "
                "for this Loot objective."
            )
            return None

        character = (
            self._scheduler_character
            if isinstance(
                self._scheduler_character,
                dict,
            )
            else {}
        )

        ranked = sorted(
            rows,
            key=lambda row: (
                -self.loot_effective_score(
                    row,
                    objective,
                    character,
                ),
                row.get("state") != "ready",
                row.get("risk_ratio", 999.0),
                as_int(
                    row.get("required_hp"),
                    10**9,
                ),
            ),
        )
        selected = ranked[0]

        ready_count = sum(
            1
            for row in rows
            if row.get("state") == "ready"
        )
        selected_name = self.monster_name(
            selected["candidate"]
        )
        selected_wait = max(
            self.hp_wait_seconds(
                character,
                as_int(
                    selected.get("required_hp"),
                    0,
                ),
            ),
            self.stamina_wait_seconds(
                character,
                as_int(
                    selected.get("stamina_target"),
                    0,
                ),
            ),
        )

        if selected.get("state") == "ready":
            self._target_audit_message = (
                f"{len(rows)} legal Loot targets checked; "
                f"{ready_count} ready now; {selected_name} selected "
                f"for the best immediate expected progress."
            )
        else:
            self._target_audit_message = (
                f"{len(rows)} legal Loot targets checked; none are "
                f"ready now; {selected_name} has the best estimated "
                f"progress time ({v27.format_duration(selected_wait)})."
            )

        return selected

    def log_target_audit_once(self) -> None:
        message = str(
            self._target_audit_message or ""
        ).strip()
        if not message:
            return

        signature = "|".join(
            [
                self.primary_key(),
                message,
            ]
        )
        if (
            signature
            == self.orchestrator.get(
                "last_target_audit"
            )
        ):
            return

        self.orchestrator[
            "last_target_audit"
        ] = signature
        self.save_orchestrator()
        self.logger.info(
            "[TARGET AUDIT] %s",
            message,
        )

    # ----------------------------------------------------------
    # Secondary tasks while the primary Quest waits
    # ----------------------------------------------------------

    def secondary_craft_objective(
        self,
        objectives,
    ):
        primary_key = self.primary_key()

        craft_rows = [
            objective
            for objective in objectives
            if (
                isinstance(
                    objective,
                    v25.ProfessionalQuestObjective,
                )
                and objective.objective_type == "craft"
                and self.objective_key(objective)
                != primary_key
            )
        ]

        if not craft_rows:
            return None

        craft_rows.sort(
            key=lambda objective: (
                self.objective_urgency_bucket(
                    objective
                ),
                objective.remaining,
                self.QUEST_TYPE_RANK.get(
                    objective.quest_type,
                    9,
                ),
            )
        )
        return craft_rows[0]

    def schedule_secondary_noncombat(
        self,
        objectives,
    ) -> None:
        self._secondary_noncombat = None
        self._secondary_noncombat_objective = None

        if time.time() < as_float(
            self.orchestrator.get(
                "secondary_craft_cooldown_until"
            ),
            0.0,
        ):
            return

        objective = self.secondary_craft_objective(
            objectives
        )
        if objective is None:
            return

        self._secondary_noncombat = "craft"
        self._secondary_noncombat_objective = objective

    def execute_secondary_noncombat(self) -> bool:
        if self._secondary_noncombat != "craft":
            return False

        objective = (
            self._secondary_noncombat_objective
        )
        if objective is None:
            return False

        self.logger.info(
            "[SECONDARY TASK] Primary Quest is waiting. "
            "Attempting Craft Quest: %s | %s remaining.",
            objective.quest_name,
            objective.remaining,
        )

        before_remaining = objective.remaining

        try:
            self.complete_craft_quests()
            self.claim_free_rewards()
            self.invalidate_quest_cache()
            refreshed = self.objective_rows()
            after_remaining = self.objective_remaining(
                self.objective_key(objective),
                refreshed,
            )
        except Exception as exc:
            self.logger.info(
                "[SECONDARY TASK] Craft attempt failed safely: %s",
                exc,
            )
            self.orchestrator[
                "secondary_craft_cooldown_until"
            ] = (
                time.time()
                + float(
                    self.config[
                        "root_orchestrator"
                    ][
                        "secondary_craft_failure_cooldown_seconds"
                    ]
                )
            )
            self.save_orchestrator()
            return False

        changed = bool(
            after_remaining is None
            or after_remaining < before_remaining
        )

        if changed:
            self.logger.info(
                "[SECONDARY RESULT] %s progressed: %s -> %s.",
                objective.quest_name,
                before_remaining,
                (
                    "completed"
                    if after_remaining is None
                    else after_remaining
                ),
            )
            self.orchestrator["secondary_actions"] = (
                as_int(
                    self.orchestrator.get(
                        "secondary_actions"
                    ),
                    0,
                )
                + 1
            )
            cooldown = float(
                self.config["root_orchestrator"][
                    "secondary_craft_success_cooldown_seconds"
                ]
            )
        else:
            self.logger.info(
                "[SECONDARY RESULT] %s could not progress now; "
                "required materials or recipe are not available.",
                objective.quest_name,
            )
            cooldown = float(
                self.config["root_orchestrator"][
                    "secondary_craft_failure_cooldown_seconds"
                ]
            )

        self.orchestrator[
            "secondary_craft_cooldown_until"
        ] = time.time() + cooldown
        self.save_orchestrator()
        return changed

    # ----------------------------------------------------------
    # Selection integration
    # ----------------------------------------------------------

    def choose_action(
        self,
        character: dict[str, Any],
        objectives,
        material_needs,
    ):
        self._secondary_noncombat = None
        self._secondary_noncombat_objective = None

        selected, states = super().choose_action(
            character,
            objectives,
            material_needs,
        )

        self.log_target_audit_once()

        if (
            selected is None
            and isinstance(
                self._primary_pending,
                dict,
            )
        ):
            self.schedule_secondary_noncombat(
                objectives
            )

        return selected, states

    # ----------------------------------------------------------
    # Verified Quest progress after every Fight
    # ----------------------------------------------------------

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
        if objective is None or not fight_won:
            return

        key = self.audit_key(
            objective,
            monster_id,
        )
        audit = self.orchestrator[
            "progress_audit"
        ].setdefault(
            key,
            {
                "wins": 0,
                "progress_events": 0,
                "no_progress_streak": 0,
                "last_before": None,
                "last_after": None,
            },
        )

        audit["wins"] = (
            as_int(audit.get("wins"), 0) + 1
        )
        audit["last_before"] = before_remaining
        audit["last_after"] = after_remaining

        progressed = bool(
            after_remaining is None
            or after_remaining < before_remaining
        )

        if progressed:
            audit["progress_events"] = (
                as_int(
                    audit.get("progress_events"),
                    0,
                )
                + 1
            )
            audit["no_progress_streak"] = 0
            self.orchestrator[
                "verified_progress_events"
            ] = (
                as_int(
                    self.orchestrator.get(
                        "verified_progress_events"
                    ),
                    0,
                )
                + 1
            )
            self.orchestrator[
                "target_penalties"
            ].pop(key, None)

            self.logger.info(
                "[QUEST PROGRESS] %s via %s | %s -> %s.",
                objective.quest_name,
                monster_name,
                before_remaining,
                (
                    "completed"
                    if after_remaining is None
                    else after_remaining
                ),
            )
        else:
            audit["no_progress_streak"] = (
                as_int(
                    audit.get("no_progress_streak"),
                    0,
                )
                + 1
            )
            self.orchestrator[
                "verified_no_progress_events"
            ] = (
                as_int(
                    self.orchestrator.get(
                        "verified_no_progress_events"
                    ),
                    0,
                )
                + 1
            )

            streak = as_int(
                audit.get("no_progress_streak"),
                0,
            )
            threshold = self.dry_fight_threshold(
                selected_row
            )

            self.logger.info(
                "[QUEST CHECK] %s did not progress after %s | "
                "dry streak %s/%s.",
                objective.quest_name,
                monster_name,
                streak,
                threshold,
            )

            if (
                objective.objective_type == "loot"
                and streak >= threshold
            ):
                penalty = float(
                    self.config["root_orchestrator"][
                        "ineffective_target_penalty"
                    ]
                )
                expiry = (
                    time.time()
                    + float(
                        self.config[
                            "root_orchestrator"
                        ][
                            "ineffective_target_penalty_seconds"
                        ]
                    )
                )
                self.orchestrator[
                    "target_penalties"
                ][key] = {
                    "penalty": penalty,
                    "expires_at": expiry,
                    "reason": (
                        f"{streak} wins without verified "
                        "Quest progress"
                    ),
                }
                self.logger.info(
                    "[TARGET CHANGE] %s is temporarily deprioritized "
                    "for %s; another legal Loot target will be tested.",
                    monster_name,
                    objective.quest_name,
                )

        self.save_orchestrator()

    def execute_fight(self, candidate) -> bool:
        objective = self._primary_objective
        objective_key = (
            self.objective_key(objective)
            if objective is not None
            else ""
        )
        before_remaining = (
            objective.remaining
            if objective is not None
            else None
        )
        selected_row = (
            self._selected_row
            if isinstance(
                self._selected_row,
                dict,
            )
            else None
        )
        monster_id = as_int(
            candidate.monster.get("id"),
            0,
        )
        monster_name = self.monster_name(
            candidate
        )

        result = super().execute_fight(
            candidate
        )

        if (
            objective is None
            or before_remaining is None
            or selected_row is None
        ):
            return result

        try:
            self.invalidate_quest_cache()
            self.get_quests(force=True)
            refreshed = self.objective_rows()
            after_remaining = (
                self.objective_remaining(
                    objective_key,
                    refreshed,
                )
            )
        except Exception as exc:
            self.logger.info(
                "[QUEST CHECK] Progress verification delayed by "
                "network error: %s",
                exc,
            )
            return result

        self.record_verified_progress(
            objective=objective,
            monster_id=monster_id,
            monster_name=monster_name,
            before_remaining=before_remaining,
            after_remaining=after_remaining,
            fight_won=result,
            selected_row=selected_row,
        )

        return result

    # ----------------------------------------------------------
    # Quiet wait-log controller
    # ----------------------------------------------------------

    def should_log_wait_message(
        self,
        *,
        signature_key: str,
        time_key: str,
        signature: str,
    ) -> bool:
        now = time.time()
        heartbeat = float(
            self.config["root_orchestrator"][
                "wait_log_heartbeat_seconds"
            ]
        )

        previous_signature = str(
            self.orchestrator.get(
                signature_key,
                "",
            )
        )
        previous_at = as_float(
            self.orchestrator.get(
                time_key,
                0.0,
            ),
            0.0,
        )

        if (
            previous_signature == signature
            and now - previous_at < heartbeat
        ):
            return False

        self.orchestrator[signature_key] = signature
        self.orchestrator[time_key] = now
        self.save_orchestrator()
        return True

    # ----------------------------------------------------------
    # Transparent waiting diagnosis
    # ----------------------------------------------------------

    def log_resource_plan(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        super().log_resource_plan(
            pending,
            character,
        )

        if not isinstance(pending, dict):
            return

        objective = self._primary_objective
        if objective is None:
            return

        candidate = pending.get("candidate")
        if candidate is None:
            return

        name = self.monster_name(candidate)
        required_hp = as_int(
            pending.get("required_hp"),
            0,
        )
        required_stamina = as_int(
            pending.get("stamina_target"),
            0,
        )
        state = str(
            pending.get("state") or ""
        )

        why_signature = "|".join(
            [
                self.objective_key(objective),
                str(candidate.monster.get("id") or ""),
                state,
                str(required_hp),
                str(required_stamina),
            ]
        )

        if self.should_log_wait_message(
            signature_key="last_why_wait_signature",
            time_key="last_why_wait_at",
            signature=why_signature,
        ):
            self.logger.info(
                "[WHY WAIT] This recovery is for Quest '%s'. "
                "The current legal target is %s.",
                objective.quest_name,
                name,
            )

        if self._secondary_noncombat == "craft":
            secondary = (
                self._secondary_noncombat_objective
            )
            opportunity_signature = "|".join(
                [
                    why_signature,
                    self.objective_key(secondary),
                ]
            )

            if self.should_log_wait_message(
                signature_key=(
                    "last_wait_opportunity_signature"
                ),
                time_key=(
                    "last_wait_opportunity_at"
                ),
                signature=opportunity_signature,
            ):
                self.logger.info(
                    "[WAIT OPPORTUNITY] Craft Quest '%s' can be "
                    "attempted while HP regenerates.",
                    secondary.quest_name,
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

        extra = [
            "",
            "ROOT QUEST ORCHESTRATOR",
            (
                "Target audit: "
                + (
                    self._target_audit_message
                    or "not available"
                )
            ),
        ]

        if self._secondary_noncombat == "craft":
            objective = (
                self._secondary_noncombat_objective
            )
            extra.append(
                "Secondary task: Craft Quest "
                + objective.quest_name
            )
        else:
            extra.append(
                "Secondary task: none currently executable"
            )

        with CURRENT_PLAN_FILE.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "\n".join(extra) + "\n"
            )

    # ----------------------------------------------------------
    # Run loop with secondary non-combat action before idle waiting.
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
            "[MODE] Root Quest orchestration, verified progress "
            "and secondary task scheduling."
        )
        self.logger.info(
            "[LOG FILE] %s",
            LIVE_LOG_FILE,
        )
        self.logger.info(
            "[CURRENT PLAN] %s",
            CURRENT_PLAN_FILE,
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

                    waiting_quest = self.pending_quest(
                        states
                    )
                    if waiting_quest is not None:
                        self.log_resource_plan(
                            waiting_quest,
                            character,
                        )

                        if self.try_quest_resources(
                            waiting_quest,
                            character,
                        ):
                            time.sleep(
                                float(
                                    self.config[
                                        "automation"
                                    ][
                                        "action_delay_seconds"
                                    ]
                                )
                            )
                            continue

                    if selected is not None:
                        candidate = selected["candidate"]
                        self.log_action_plan(
                            selected,
                            character,
                        )

                        self.logger.info(
                            "[TRAVEL] Ensuring zone: %s.",
                            candidate.zone_name,
                        )
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

                        self.logger.info(
                            "[ACTION] Starting Fight: %s.",
                            self.monster_name(candidate),
                        )
                        self.scheduler_state[
                            "last_status"
                        ] = ""
                        self.save_scheduler_state()

                        self.execute_fight(candidate)
                        self.after_fight_housekeeping()

                        time.sleep(
                            float(
                                self.config[
                                    "automation"
                                ][
                                    "action_delay_seconds"
                                ]
                            )
                        )
                        continue

                    if self._secondary_noncombat is not None:
                        self.execute_secondary_noncombat()
                        time.sleep(
                            float(
                                self.config[
                                    "automation"
                                ][
                                    "action_delay_seconds"
                                ]
                            )
                        )
                        continue

                    pending = (
                        self._primary_pending
                        if isinstance(
                            self._primary_pending,
                            dict,
                        )
                        else self.best_pending(states)
                    )

                    if now >= self.next_special_check:
                        has_urgent = any(
                            getattr(
                                row,
                                "objective_type",
                                "",
                            )
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
                                self.next_special_check = (
                                    now + 60
                                )
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
                                self.config[
                                    "active_scheduler"
                                ][
                                    "special_check_seconds"
                                ]
                            )
                        )
                        if acted:
                            continue

                    self.log_no_action(
                        pending,
                        character,
                    )
                    time.sleep(poll)
                    self.total_wait_seconds += poll

                    self.scheduler_state["cycles"] = (
                        as_int(
                            self.scheduler_state.get(
                                "cycles"
                            )
                        )
                        + 1
                    )
                    self.save_scheduler_state()

                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    key = (
                        f"cycle:{type(exc).__name__}:"
                        f"{exc}"
                    )
                    if (
                        self.scheduler_state.get(
                            "last_error"
                        )
                        != key
                    ):
                        self.scheduler_state[
                            "last_error"
                        ] = key
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
                "root_quest_orchestrator_state": (
                    self.orchestrator
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_8_1_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_8_1_final_"
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
        bot = RootQuestOrchestrator(
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
