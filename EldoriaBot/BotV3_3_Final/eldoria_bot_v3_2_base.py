from __future__ import annotations

import importlib.util
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V31_FILE = SCRIPT_DIR / "eldoria_bot_v3_1_base.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_2_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV3_2_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v3_2_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

if not V31_FILE.exists():
    raise RuntimeError(f"Required file is missing: {V31_FILE}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v31_base",
    V31_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V3.1 base could not be loaded.")

v31 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v31
spec.loader.exec_module(v31)

v30 = v31.v30
v29 = v31.v29
v281 = v31.v281
v271 = v31.v271
v27 = v31.v27
v26 = v31.v26
v25 = v31.v25
v24 = v31.v24
v232 = v31.v232
v22 = v31.v22
v21 = v31.v21
v161 = v31.v161
base = v31.base
engine = v31.engine

for module in (
    v31, v30, v29, v281, v271, v27, v26, v25,
    v24, v232, v22, v21, v161, base, engine,
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
        OUTPUT_DIR / "eldoria_bot_v3_2_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v31, v30, v29, v281, v271, v27, v26, v25,
    v24, v232, v22, v21, v161, base,
):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE

for module in (v27, v271, v281, v29, v30, v31):
    module.LIVE_LOG_FILE = LIVE_LOG_FILE
    module.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE


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

    logger = logging.getLogger("eldoria_bot_v3_2_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v3_2_final.log",
        LIVE_LOG_FILE,
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


class NoDeathEfficiencyDirector(v31.StrictCraftQuestDirector):
    VERSION = "3.2-final-no-death-efficiency-director-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.safety_file = (
            STATE_DIR / "no_death_efficiency_state.json"
        )
        self.safety = engine.load_json(
            self.safety_file,
            {
                "schema_version": 1,
                "blocked_preflights": 0,
                "unproven_blocks": 0,
                "death_lock_blocks": 0,
                "broad_safe_selections": 0,
                "last_block_signature": "",
                "last_block_at": 0.0,
                "last_efficiency_signature": "",
                "last_efficiency_at": 0.0,
            },
        )
        if not isinstance(self.safety, dict):
            self.safety = {}

        defaults = {
            "schema_version": 1,
            "blocked_preflights": 0,
            "unproven_blocks": 0,
            "death_lock_blocks": 0,
            "broad_safe_selections": 0,
            "last_block_signature": "",
            "last_block_at": 0.0,
            "last_efficiency_signature": "",
            "last_efficiency_at": 0.0,
        }
        for key, default in defaults.items():
            self.safety.setdefault(key, default)

        self._efficiency_audit_message = ""
        self._efficiency_audit_signature = ""
        self.save_safety()

    def save_safety(self) -> None:
        engine.save_json(self.safety_file, self.safety)

    # ----------------------------------------------------------
    # No-death combat gate
    # ----------------------------------------------------------

    def successful_sample_count(self, monster_id: int) -> int:
        recent = self.combat_sample_rows(monster_id)
        aggregate = self.smart_state.get(
            "successful_damage",
            {},
        ).get(str(monster_id))

        count = len(recent)
        if isinstance(aggregate, dict):
            count = max(count, as_int(aggregate.get("count"), 0))
        return count

    def conservative_damage_estimate(
        self,
        row: dict[str, Any],
        candidate,
    ) -> tuple[float, bool]:
        monster_id = as_int(candidate.monster.get("id"), 0)
        successful = self.successful_damage_estimate(monster_id)
        recent, _ = self.contextual_damage_estimate(
            monster_id,
            self._scheduler_character
            if isinstance(
                getattr(self, "_scheduler_character", None),
                dict,
            )
            else {},
        )

        values = [
            max(0.0, as_float(row.get("estimate"), 0.0)),
            max(0.0, as_float(candidate.predicted_damage, 0.0)),
        ]
        if successful is not None:
            values.append(max(0.0, as_float(successful, 0.0)))
        if recent is not None:
            values.append(max(0.0, as_float(recent, 0.0)))

        return max(values or [0.0]), self.successful_sample_count(monster_id) > 0

    def apply_no_death_gate(
        self,
        row: dict[str, Any],
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(row)
        monster = candidate.monster
        monster_id = as_int(monster.get("id"), 0)

        hp = max(0, as_int(character.get("hp"), 0))
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        stamina = max(0, as_int(character.get("stamina"), 0))
        stamina_cost = max(
            1,
            as_int(
                updated.get(
                    "stamina_target",
                    monster.get("stamina_cost"),
                ),
                1,
            ),
        )

        if self.death_lock_active(monster, character):
            updated.update(
                {
                    "state": "strengthen",
                    "reason": (
                        "hard death lock: Level, Power and Mastery "
                        "requirements are not all complete"
                    ),
                    "required_hp": hp_max + 1,
                    "hp_short": 0,
                    "stamina_short": 0,
                    "actionable": False,
                    "no_death_blocked": True,
                    "no_death_reason": "death-lock",
                }
            )
            return updated

        estimate, proven = self.conservative_damage_estimate(
            updated,
            candidate,
        )
        exact = bool(
            updated.get("quest_exact")
            or candidate.priority == 0
        )

        if proven:
            margin = float(
                self.config["no_death"][
                    "proven_damage_margin"
                ]
            )
            post_ratio = float(
                self.config["no_death"][
                    "proven_minimum_post_hp_ratio"
                ]
            )
            flat_buffer = int(
                self.config["no_death"][
                    "proven_flat_buffer"
                ]
            )
        elif exact:
            margin = float(
                self.config["no_death"][
                    "unproven_exact_damage_margin"
                ]
            )
            post_ratio = float(
                self.config["no_death"][
                    "unproven_exact_minimum_post_hp_ratio"
                ]
            )
            flat_buffer = int(
                self.config["no_death"][
                    "unproven_exact_flat_buffer"
                ]
            )
        else:
            margin = float(
                self.config["no_death"][
                    "unproven_broad_damage_margin"
                ]
            )
            post_ratio = float(
                self.config["no_death"][
                    "unproven_broad_minimum_post_hp_ratio"
                ]
            )
            flat_buffer = int(
                self.config["no_death"][
                    "unproven_broad_flat_buffer"
                ]
            )

        post_floor = max(
            int(self.config["combat"]["minimum_hp_after_battle"]),
            math.ceil(hp_max * post_ratio),
        )
        required_hp = math.ceil(
            estimate * margin + flat_buffer + post_floor
        )

        unproven_ratio = estimate / hp_max
        if (
            not proven
            and exact
            and unproven_ratio
            > float(
                self.config["no_death"][
                    "maximum_unproven_exact_damage_ratio"
                ]
            )
        ):
            updated.update(
                {
                    "state": "strengthen",
                    "reason": (
                        "unproven exact target is too dangerous "
                        "for a first no-death attempt"
                    ),
                    "required_hp": max(required_hp, hp_max + 1),
                    "risk_ratio": unproven_ratio,
                    "hp_short": 0,
                    "stamina_short": 0,
                    "actionable": False,
                    "estimate": estimate,
                    "confidence": "unproven-blocked",
                    "no_death_blocked": True,
                    "no_death_reason": "unproven-exact",
                }
            )
            return updated

        if required_hp > hp_max:
            updated.update(
                {
                    "state": "strengthen",
                    "reason": (
                        "no-death margin does not fit inside maximum HP"
                    ),
                    "required_hp": required_hp,
                    "risk_ratio": estimate / hp_max,
                    "hp_short": 0,
                    "stamina_short": 0,
                    "actionable": False,
                    "estimate": estimate,
                    "confidence": (
                        "proven-conservative"
                        if proven
                        else "unproven-conservative"
                    ),
                    "no_death_blocked": True,
                    "no_death_reason": "insufficient-max-hp",
                }
            )
            return updated

        if hp < required_hp:
            state = "heal"
            reason = "waiting for no-death HP margin"
        elif stamina < stamina_cost:
            state = "resource"
            reason = "waiting for Fight stamina"
        else:
            state = "ready"
            reason = "ready with no-death margin"

        updated.update(
            {
                "state": state,
                "reason": reason,
                "required_hp": required_hp,
                "stamina_target": stamina_cost,
                "estimate": estimate,
                "risk_ratio": estimate / hp_max,
                "hp_short": max(0, required_hp - hp),
                "stamina_short": max(0, stamina_cost - stamina),
                "actionable": state == "ready",
                "confidence": (
                    "proven-conservative"
                    if proven
                    else "unproven-conservative"
                ),
                "minimum_post_hp": post_floor,
                "no_death_blocked": False,
            }
        )
        return updated

    def combat_assessment(
        self,
        candidate,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        row = super().combat_assessment(
            candidate,
            character,
        )
        return self.apply_no_death_gate(
            row,
            candidate,
            character,
        )

    # ----------------------------------------------------------
    # KILL any: choose minimum real recovery cost
    # ----------------------------------------------------------

    def broad_kill_objective(self, objective, rows) -> bool:
        return bool(
            objective.objective_type == "kill"
            and self.objective_is_broad(objective, rows)
        )

    def row_recovery_cost(
        self,
        row: dict[str, Any],
        character: dict[str, Any],
    ) -> tuple[float, float, float]:
        required_hp = max(0, as_int(row.get("required_hp"), 0))
        stamina_target = max(
            1,
            as_int(row.get("stamina_target"), 1),
        )
        first_wait = max(
            self.hp_wait_seconds(character, required_hp),
            self.stamina_wait_seconds(
                character,
                stamina_target,
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
            else float("inf")
        )
        stamina_recovery = (
            stamina_target / stamina_regen * 3600.0
            if stamina_regen > 0
            else float("inf")
        )
        cycle = max(hp_recovery, stamina_recovery)
        return first_wait, cycle, first_wait + cycle

    def select_target_row(self, objective, rows):
        if not rows:
            return None

        if not self.broad_kill_objective(objective, rows):
            selected = super().select_target_row(objective, rows)
            if selected is not None and objective.objective_type != "loot":
                self._target_audit_message = (
                    f"{len(rows)} legal targets checked for "
                    f"{objective.quest_name}; "
                    f"{self.monster_name(selected['candidate'])} selected."
                )
                self._target_audit_signature = "|".join(
                    [
                        self.objective_key(objective),
                        str(
                            selected["candidate"].monster.get("id")
                        ),
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

        character = (
            self._scheduler_character
            if isinstance(
                getattr(self, "_scheduler_character", None),
                dict,
            )
            else {}
        )
        usable = [
            row
            for row in rows
            if row.get("state") in {"ready", "heal", "resource"}
            and not row.get("no_death_blocked")
        ]
        if not usable:
            self._target_audit_message = (
                f"{len(rows)} Kill-any targets checked; "
                "all are blocked by safety or progression requirements."
            )
            self._target_audit_signature = (
                self.objective_key(objective) + "|blocked"
            )
            return None

        usable.sort(
            key=lambda row: (
                self.row_recovery_cost(row, character)[2],
                self.row_recovery_cost(row, character)[1],
                as_float(row.get("risk_ratio"), 999.0),
                as_float(row.get("estimate"), float("inf")),
                as_int(row.get("stamina_target"), 999),
                -as_int(
                    getattr(
                        row["candidate"],
                        "quest_overlap",
                        0,
                    ),
                    0,
                ),
                -row["candidate"].gold_per_stamina,
            )
        )
        selected = usable[0]
        first_wait, cycle, total = self.row_recovery_cost(
            selected,
            character,
        )
        self._efficiency_audit_message = (
            f"{len(rows)} Kill-any targets checked; "
            f"{self.monster_name(selected['candidate'])} has the "
            f"lowest safe recovery cost | first wait "
            f"{v27.format_duration(first_wait)} | repeat cycle "
            f"{v27.format_duration(cycle)}."
        )
        self._efficiency_audit_signature = "|".join(
            [
                self.objective_key(objective),
                str(selected["candidate"].monster.get("id")),
                str(selected.get("state") or ""),
                str(as_int(selected.get("required_hp"), 0)),
            ]
        )
        self._target_audit_message = self._efficiency_audit_message
        self._target_audit_signature = (
            self._efficiency_audit_signature
        )
        self.safety["broad_safe_selections"] = (
            as_int(
                self.safety.get("broad_safe_selections"),
                0,
            )
            + 1
        )
        self.save_safety()
        return selected

    # ----------------------------------------------------------
    # Only the real campaign pending target may appear in wait logs
    # ----------------------------------------------------------

    def pending_quest(self, states):
        if (
            isinstance(
                getattr(self, "_selected_row", None),
                dict,
            )
            and self._selected_row.get("state") == "ready"
        ):
            return None

        pending = getattr(self, "_campaign_pending", None)
        if (
            isinstance(pending, dict)
            and pending.get("state") in {"heal", "resource"}
        ):
            return pending

        primary = getattr(self, "_primary_pending", None)
        if (
            isinstance(primary, dict)
            and primary.get("state") in {"heal", "resource"}
        ):
            return primary

        # Never fall back to an unrelated global candidate.
        return None

    # ----------------------------------------------------------
    # Final real-time preflight immediately before every Fight
    # ----------------------------------------------------------

    def log_no_death_block(
        self,
        candidate,
        row: dict[str, Any],
    ) -> None:
        reason = str(
            row.get("reason")
            or row.get("no_death_reason")
            or "safety gate"
        )
        signature = "|".join(
            [
                str(candidate.monster.get("id") or ""),
                reason,
                str(as_int(row.get("required_hp"), 0)),
            ]
        )
        now = time.time()
        heartbeat = float(
            self.config["no_death"][
                "block_log_heartbeat_seconds"
            ]
        )
        if (
            signature == self.safety.get("last_block_signature")
            and now
            - as_float(
                self.safety.get("last_block_at"),
                0.0,
            )
            < heartbeat
        ):
            return

        self.safety["last_block_signature"] = signature
        self.safety["last_block_at"] = now
        self.safety["blocked_preflights"] = (
            as_int(
                self.safety.get("blocked_preflights"),
                0,
            )
            + 1
        )
        if row.get("no_death_reason") == "death-lock":
            self.safety["death_lock_blocks"] = (
                as_int(
                    self.safety.get("death_lock_blocks"),
                    0,
                )
                + 1
            )
        if row.get("no_death_reason") == "unproven-exact":
            self.safety["unproven_blocks"] = (
                as_int(
                    self.safety.get("unproven_blocks"),
                    0,
                )
                + 1
            )
        self.save_safety()

        self.logger.info(
            "[NO-DEATH BLOCK] %s | %s | current HP %s | "
            "required HP %s.",
            self.monster_name(candidate),
            reason,
            as_int(
                getattr(self, "_scheduler_character", {}).get(
                    "hp"
                ),
                0,
            ),
            as_int(row.get("required_hp"), 0),
        )

    def execute_fight(self, candidate) -> bool:
        try:
            current = self.get_character()
        except Exception as exc:
            self.logger.info(
                "[NO-DEATH BLOCK] Fight cancelled because the "
                "current character state could not be verified: %s",
                exc,
            )
            return False

        self._scheduler_character = current
        row = self.combat_assessment(candidate, current)

        if row.get("state") != "ready":
            self.log_no_death_block(candidate, row)

            if (
                getattr(self, "_selected_role", "")
                != "STRICT CRAFT MATERIAL"
                and isinstance(
                    getattr(self, "_primary_objective", None),
                    v25.ProfessionalQuestObjective,
                )
            ):
                self._campaign_pending = row
                self._primary_pending = row
            return False

        hp = as_int(current.get("hp"), 0)
        estimate = as_float(row.get("estimate"), 0.0)
        minimum_post = as_int(
            row.get("minimum_post_hp"),
            int(
                self.config["combat"][
                    "minimum_hp_after_battle"
                ]
            ),
        )
        if hp - math.ceil(estimate) < minimum_post:
            blocked = dict(row)
            blocked.update(
                {
                    "state": "heal",
                    "reason": (
                        "real-time post-Fight HP floor is not satisfied"
                    ),
                    "required_hp": math.ceil(
                        estimate + minimum_post
                    ),
                    "no_death_reason": "real-time-floor",
                }
            )
            self.log_no_death_block(candidate, blocked)
            self._campaign_pending = blocked
            self._primary_pending = blocked
            return False

        return super().execute_fight(candidate)

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

        lines = [
            "",
            "NO-DEATH EFFICIENCY DIRECTOR",
            "Death-locked enemies require Level + Power + Mastery.",
            "Unproven high-damage exact targets are never test-fought.",
        ]
        if self._efficiency_audit_message:
            lines.append(
                "Kill-any selection: "
                + self._efficiency_audit_message
            )

        with CURRENT_PLAN_FILE.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write("\n".join(lines) + "\n")

    def final_report(self):
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "no_death_efficiency_state": self.safety,
            }
        )
        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v3_2_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v3_2_final_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
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
        bot = NoDeathEfficiencyDirector(
            client,
            config,
            logger,
        )
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
