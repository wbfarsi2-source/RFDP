from __future__ import annotations

import importlib.util
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V26_FILE = SCRIPT_DIR / "eldoria_bot_v2_6_base.py"
V25_FILE = SCRIPT_DIR / "eldoria_bot_v2_5_base.py"
V24_FILE = SCRIPT_DIR / "eldoria_bot_v2_4_base.py"
V232_FILE = SCRIPT_DIR / "eldoria_bot_v2_3_2_base.py"
V22_FILE = SCRIPT_DIR / "eldoria_bot_v2_2_base.py"
V21_FILE = SCRIPT_DIR / "eldoria_bot_v2_1_base.py"
V161_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_base.py"
V15_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v2_7_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV2_7_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v2_7_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

for required in (
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
    "eldoria_v26_base",
    V26_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.6 base could not be loaded.")

v26 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v26
spec.loader.exec_module(v26)

v25 = v26.v25
v24 = v26.v24
v232 = v26.v232
v22 = v26.v22
v21 = v26.v21
v161 = v26.v161
base = v26.base
engine = v26.engine

for module in (
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
        OUTPUT_DIR / "eldoria_bot_v2_7_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
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


def unique_names(values) -> list[str]:
    result = []
    seen = set()

    for value in values:
        text = str(value or "").strip()
        key = normalize(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)

    return result


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "unknown"
    if seconds <= 0:
        return "ready now"

    total = int(math.ceil(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def configure_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v2_7_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v2_7_final.log",
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


class TransparentQuestDirector(v26.QuestCampaignEngine):
    VERSION = "2.7-final-transparent-quest-director-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.director_file = (
            STATE_DIR / "transparent_quest_director_state.json"
        )
        self.director = engine.load_json(
            self.director_file,
            {
                "schema_version": 1,
                "last_plan_signature": "",
                "last_plan_at": 0.0,
                "last_wait_signature": "",
                "last_wait_at": 0.0,
                "opportunity_wait_key": "",
                "opportunity_used": False,
                "opportunity_actions": 0,
                "last_result_signature": "",
            },
        )

        if not isinstance(self.director, dict):
            self.director = {}

        self.director.setdefault("schema_version", 1)
        self.director.setdefault("last_plan_signature", "")
        self.director.setdefault("last_plan_at", 0.0)
        self.director.setdefault("last_wait_signature", "")
        self.director.setdefault("last_wait_at", 0.0)
        self.director.setdefault("opportunity_wait_key", "")
        self.director.setdefault("opportunity_used", False)
        self.director.setdefault("opportunity_actions", 0)
        self.director.setdefault("last_result_signature", "")

        self._primary_objective = None
        self._primary_pending = None
        self._selected_row = None
        self._selected_role = ""
        self._opportunity_reason = ""
        self.save_director()

    def save_director(self) -> None:
        engine.save_json(
            self.director_file,
            self.director,
        )

    def objective_from_campaign(
        self,
        objectives,
    ):
        return self.current_campaign_objective(
            self.supported_campaign_objectives(
                objectives
            )
        )

    def primary_key(self) -> str:
        return str(
            self.campaign.get("active_key") or ""
        )

    def objective_label(self, objective) -> str:
        if objective is None:
            return "No active Quest"

        target = str(objective.target or "any")
        zone = (
            objective.zone_code
            or (
                str(objective.zone_id)
                if objective.zone_id is not None
                else ""
            )
        )

        details = (
            f"{objective.objective_type.upper()} {target}"
        )
        if zone:
            details += f" in {zone}"

        return details

    @staticmethod
    def monster_name(candidate) -> str:
        return str(
            candidate.monster.get("name_en")
            or candidate.monster.get("name")
            or candidate.monster.get("code")
            or candidate.monster.get("id")
        )

    def parallel_objectives(
        self,
        row,
        primary_objective=None,
    ):
        candidate = row.get("candidate")
        if candidate is None:
            return []

        primary_key = (
            self.objective_key(primary_objective)
            if primary_objective is not None
            else ""
        )

        result = []

        for objective in getattr(
            candidate,
            "quest_hits",
            [],
        ):
            if not isinstance(
                objective,
                v25.ProfessionalQuestObjective,
            ):
                continue
            if (
                primary_key
                and self.objective_key(objective)
                == primary_key
            ):
                continue
            result.append(objective)

        return result

    def parallel_text(
        self,
        row,
        primary_objective=None,
    ) -> str:
        objectives = self.parallel_objectives(
            row,
            primary_objective,
        )
        names = unique_names(
            f"{item.quest_name} ({item.remaining} left)"
            for item in objectives
        )
        return (
            ", ".join(names)
            if names
            else "none"
        )

    def hp_wait_seconds(
        self,
        character: dict[str, Any],
        target: int,
        hp_override: int | None = None,
    ) -> float:
        current = (
            as_int(hp_override)
            if hp_override is not None
            else as_int(character.get("hp"), 0)
        )
        missing = max(0, target - current)
        regen = as_float(
            character.get("hp_regen_per_hour"),
            0.0,
        )

        if missing <= 0:
            return 0.0
        if regen <= 0:
            return float("inf")
        return missing / regen * 3600.0

    def stamina_wait_seconds(
        self,
        character: dict[str, Any],
        target: int,
        stamina_override: int | None = None,
    ) -> float:
        current = (
            as_int(stamina_override)
            if stamina_override is not None
            else as_int(character.get("stamina"), 0)
        )
        missing = max(0, target - current)
        regen = as_float(
            character.get("stamina_regen_per_hour"),
            8.333333,
        )

        if missing <= 0:
            return 0.0
        if regen <= 0:
            return float("inf")
        return missing / regen * 3600.0

    def pending_wait_key(self, pending) -> str:
        if not isinstance(pending, dict):
            return ""

        candidate = pending.get("candidate")
        monster_id = (
            as_int(candidate.monster.get("id"), 0)
            if candidate is not None
            else 0
        )

        return "|".join(
            [
                self.primary_key(),
                str(monster_id),
                str(as_int(pending.get("required_hp"), 0)),
                str(as_int(pending.get("stamina_target"), 0)),
                str(pending.get("state") or ""),
            ]
        )

    def reset_opportunity_if_needed(
        self,
        pending,
    ) -> None:
        key = self.pending_wait_key(pending)

        if (
            key
            != self.director.get(
                "opportunity_wait_key"
            )
        ):
            self.director["opportunity_wait_key"] = key
            self.director["opportunity_used"] = False
            self.save_director()

    def added_primary_delay(
        self,
        primary_pending,
        opportunity_row,
        character: dict[str, Any],
    ) -> float:
        required_hp = max(
            0,
            as_int(
                primary_pending.get("required_hp"),
                0,
            ),
        )
        required_stamina = max(
            0,
            as_int(
                primary_pending.get("stamina_target"),
                0,
            ),
        )

        current_hp = as_int(character.get("hp"), 0)
        current_stamina = as_int(
            character.get("stamina"),
            0,
        )

        opportunity_estimate = max(
            0.0,
            as_float(
                opportunity_row.get("estimate"),
                opportunity_row[
                    "candidate"
                ].predicted_damage,
            ),
        )
        opportunity_cost = max(
            1,
            as_int(
                opportunity_row.get(
                    "stamina_target"
                ),
                1,
            ),
        )

        hp_after = max(
            0,
            current_hp
            - math.ceil(
                opportunity_estimate
                * float(
                    self.config[
                        "transparent_logs"
                    ][
                        "opportunity_damage_safety"
                    ]
                )
            ),
        )
        stamina_after = max(
            0,
            current_stamina - opportunity_cost,
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
        after_wait = max(
            self.hp_wait_seconds(
                character,
                required_hp,
                hp_override=hp_after,
            ),
            self.stamina_wait_seconds(
                character,
                required_stamina,
                stamina_override=stamina_after,
            ),
        )

        return max(0.0, after_wait - current_wait)

    def opportunity_score(
        self,
        row,
        primary_objective,
        added_delay: float,
    ) -> float:
        secondary = self.parallel_objectives(
            row,
            primary_objective,
        )
        if not secondary:
            return float("-inf")

        daily = sum(
            1
            for objective in secondary
            if objective.quest_type == "daily"
        )
        urgent = sum(
            1
            for objective in secondary
            if (
                objective.seconds_to_expiry()
                is not None
                and 0
                < objective.seconds_to_expiry()
                <= 24 * 3600
            )
        )

        candidate = row["candidate"]

        return (
            daily * 500.0
            + urgent * 350.0
            + len(secondary) * 180.0
            + candidate.xp_per_stamina * 10.0
            + candidate.gold_per_stamina * 4.0
            - row.get("risk_ratio", 999.0) * 250.0
            - added_delay / 60.0 * 4.0
        )

    def find_opportunity(
        self,
        primary_pending,
        states,
        character: dict[str, Any],
        primary_objective,
    ):
        if not isinstance(primary_pending, dict):
            return None

        self.reset_opportunity_if_needed(
            primary_pending
        )

        if self.director.get("opportunity_used"):
            return None

        maximum_delay = float(
            self.config["transparent_logs"][
                "maximum_opportunity_delay_seconds"
            ]
        )
        maximum_risk = float(
            self.config["transparent_logs"][
                "maximum_opportunity_risk_ratio"
            ]
        )
        minimum_hp_ratio = float(
            self.config["transparent_logs"][
                "minimum_hp_after_opportunity_ratio"
            ]
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

            if (
                as_float(
                    row.get("risk_ratio"),
                    999.0,
                )
                > maximum_risk
            ):
                continue

            secondary = self.parallel_objectives(
                row,
                primary_objective,
            )
            if not secondary:
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

            if (
                hp_after / hp_max
                < minimum_hp_ratio
            ):
                continue

            added_delay = self.added_primary_delay(
                primary_pending,
                row,
                character,
            )

            if (
                not math.isfinite(added_delay)
                or added_delay > maximum_delay
            ):
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

        if not choices:
            return None

        choices.sort(
            key=lambda item: (
                -item[0],
                item[1],
                -item[2]["candidate"].xp_per_stamina,
            )
        )
        return choices[0]

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

        self._primary_objective = (
            self.objective_from_campaign(
                objectives
            )
        )
        self._primary_pending = (
            self._campaign_pending
            if isinstance(
                self._campaign_pending,
                dict,
            )
            else None
        )
        self._selected_row = selected
        self._selected_role = ""
        self._opportunity_reason = ""

        if selected is not None:
            mode = str(
                self.campaign.get("mode") or ""
            )
            self._selected_role = {
                "quest-combat": "PRIMARY QUEST",
                "strength-training": "STRENGTH TRAINING",
                "craft-materials": "MATERIAL FARMING",
                "progression": "PROGRESSION",
            }.get(mode, "QUEST ACTION")
            return selected, states

        if self._primary_pending is None:
            return selected, states

        opportunity = self.find_opportunity(
            self._primary_pending,
            states,
            character,
            self._primary_objective,
        )
        if opportunity is None:
            return None, states

        _, added_delay, row = opportunity
        self._selected_row = row
        self._selected_role = "OPPORTUNITY"
        self._opportunity_reason = (
            f"primary Quest is waiting; this action adds "
            f"about {format_duration(added_delay)} and advances "
            f"{self.parallel_text(row, self._primary_objective)}"
        )
        return row, states

    def current_requirements(
        self,
        row,
        character: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = row["candidate"]
        return {
            "monster": self.monster_name(candidate),
            "zone": candidate.zone_name,
            "hp": as_int(character.get("hp"), 0),
            "hp_max": as_int(
                character.get("hp_max"),
                0,
            ),
            "required_hp": as_int(
                row.get("required_hp"),
                0,
            ),
            "stamina": as_int(
                character.get("stamina"),
                0,
            ),
            "stamina_max": as_int(
                character.get("stamina_max"),
                0,
            ),
            "required_stamina": as_int(
                row.get("stamina_target"),
                0,
            ),
            "mp": as_int(
                character.get("mp"),
                0,
            ),
            "mp_max": as_int(
                character.get("mp_max"),
                0,
            ),
            "estimated_damage": round(
                as_float(
                    row.get("estimate"),
                    candidate.predicted_damage,
                )
            ),
            "state": str(row.get("state") or ""),
        }

    def write_current_plan(
        self,
        *,
        step: str,
        row=None,
        character=None,
        details: str = "",
    ) -> None:
        objective = self._primary_objective
        lines = [
            "ELDORIA BOT CURRENT PLAN",
            "=" * 72,
            f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Live log: {LIVE_LOG_FILE}",
            "",
            "PRIMARY QUEST",
            f"Name: {getattr(objective, 'quest_name', 'None')}",
            f"Type: {getattr(objective, 'quest_type', 'none')}",
            f"Objective: {self.objective_label(objective)}",
            f"Remaining: {getattr(objective, 'remaining', 0)}",
            "",
            "CURRENT STEP",
            f"Step: {step}",
            f"Details: {details or 'none'}",
        ]

        if (
            isinstance(row, dict)
            and isinstance(character, dict)
        ):
            needs = self.current_requirements(
                row,
                character,
            )
            lines.extend(
                [
                    "",
                    "TARGET AND REQUIREMENTS",
                    f"Target: {needs['monster']}",
                    f"Zone: {needs['zone']}",
                    (
                        f"HP: {needs['hp']}/{needs['hp_max']} "
                        f"| required {needs['required_hp']}"
                    ),
                    (
                        f"STM: {needs['stamina']}/{needs['stamina_max']} "
                        f"| required {needs['required_stamina']}"
                    ),
                    (
                        f"MP: {needs['mp']}/{needs['mp_max']}"
                    ),
                    (
                        f"Estimated damage: "
                        f"{needs['estimated_damage']}"
                    ),
                    (
                        "Parallel Quests: "
                        + self.parallel_text(
                            row,
                            objective,
                        )
                    ),
                ]
            )

        lines.extend(
            [
                "",
                "STATE FILES",
                f"Current plan: {CURRENT_PLAN_FILE}",
                f"Full log: {LIVE_LOG_FILE}",
                "",
            ]
        )

        CURRENT_PLAN_FILE.write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    def should_log_plan(
        self,
        signature: str,
        *,
        wait: bool = False,
    ) -> bool:
        now = time.time()
        signature_key = (
            "last_wait_signature"
            if wait
            else "last_plan_signature"
        )
        time_key = (
            "last_wait_at"
            if wait
            else "last_plan_at"
        )
        heartbeat = float(
            self.config["transparent_logs"][
                "status_heartbeat_seconds"
            ]
        )

        if (
            self.director.get(signature_key)
            == signature
            and now
            - as_float(
                self.director.get(time_key),
                0.0,
            )
            < heartbeat
        ):
            return False

        self.director[signature_key] = signature
        self.director[time_key] = now
        self.save_director()
        return True

    def log_action_plan(
        self,
        row,
        character: dict[str, Any],
    ) -> None:
        objective = self._primary_objective
        candidate = row["candidate"]
        needs = self.current_requirements(
            row,
            character,
        )
        parallel = self.parallel_text(
            row,
            objective,
        )
        role = self._selected_role or "QUEST ACTION"

        signature = "|".join(
            [
                role,
                self.primary_key(),
                str(candidate.monster.get("id")),
                str(needs["required_hp"]),
                str(needs["required_stamina"]),
                parallel,
            ]
        )
        if not self.should_log_plan(signature):
            return

        self.logger.info(
            "[MISSION] Primary: %s [%s] | %s | remaining %s.",
            getattr(objective, "quest_name", "No active Quest"),
            str(
                getattr(
                    objective,
                    "quest_type",
                    "none",
                )
            ).upper(),
            self.objective_label(objective),
            getattr(objective, "remaining", 0),
        )
        self.logger.info(
            "[STEP] %s -> %s in %s.",
            role,
            needs["monster"],
            needs["zone"],
        )
        self.logger.info(
            "[NEEDS] HP %s/%s, required %s | "
            "STM %s/%s, required %s | "
            "estimated damage %s.",
            needs["hp"],
            needs["hp_max"],
            needs["required_hp"],
            needs["stamina"],
            needs["stamina_max"],
            needs["required_stamina"],
            needs["estimated_damage"],
        )

        if parallel != "none":
            self.logger.info(
                "[PARALLEL] This action also advances: %s.",
                parallel,
            )
        else:
            self.logger.info(
                "[PARALLEL] No other Quest is advanced by this action."
            )

        if role == "OPPORTUNITY":
            self.logger.info(
                "[OPPORTUNITY] %s.",
                self._opportunity_reason,
            )

        self.write_current_plan(
            step=role,
            row=row,
            character=character,
            details=(
                self._opportunity_reason
                if role == "OPPORTUNITY"
                else f"Fight {needs['monster']}"
            ),
        )

    def log_resource_plan(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        if not isinstance(pending, dict):
            return

        objective = self._primary_objective
        candidate = pending["candidate"]
        required_hp = as_int(
            pending.get("required_hp"),
            0,
        )
        required_stamina = as_int(
            pending.get("stamina_target"),
            0,
        )
        hp = as_int(character.get("hp"), 0)
        stamina = as_int(
            character.get("stamina"),
            0,
        )

        hp_wait = self.hp_wait_seconds(
            character,
            required_hp,
        )
        stamina_wait = self.stamina_wait_seconds(
            character,
            required_stamina,
        )
        total_wait = max(hp_wait, stamina_wait)

        signature = "|".join(
            [
                self.primary_key(),
                str(candidate.monster.get("id")),
                str(pending.get("state")),
                str(required_hp),
                str(required_stamina),
                str(hp // 10),
                str(stamina),
            ]
        )
        if not self.should_log_plan(
            signature,
            wait=True,
        ):
            return

        missing = []
        if hp < required_hp:
            missing.append(
                f"HP +{required_hp - hp}"
            )
        if stamina < required_stamina:
            missing.append(
                f"STM +{required_stamina - stamina}"
            )

        self.logger.info(
            "[MISSION] Primary: %s [%s] | %s | remaining %s.",
            getattr(objective, "quest_name", "No active Quest"),
            str(
                getattr(
                    objective,
                    "quest_type",
                    "none",
                )
            ).upper(),
            self.objective_label(objective),
            getattr(objective, "remaining", 0),
        )
        self.logger.info(
            "[STEP] RESOURCE PREPARATION -> %s.",
            self.monster_name(candidate),
        )
        self.logger.info(
            "[WAIT] Need %s | HP %s/%s | STM %s/%s | "
            "natural ETA about %s.",
            ", ".join(missing) if missing else "re-evaluation",
            hp,
            required_hp,
            stamina,
            required_stamina,
            format_duration(total_wait),
        )
        self.logger.info(
            "[WHILE WAITING] Claims, Daily checks, Craft, "
            "Skills and equipment remain active."
        )

        self.write_current_plan(
            step="RESOURCE PREPARATION",
            row=pending,
            character=character,
            details=(
                f"Waiting for {', '.join(missing)}; "
                f"ETA {format_duration(total_wait)}"
            ),
        )

    def log_no_action(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        if isinstance(pending, dict):
            self.log_resource_plan(
                pending,
                character,
            )
            return

        signature = "|".join(
            [
                self.primary_key(),
                "no-action",
                str(as_int(character.get("hp"), 0) // 20),
                str(as_int(character.get("stamina"), 0)),
            ]
        )
        if not self.should_log_plan(
            signature,
            wait=True,
        ):
            return

        objective = self._primary_objective
        self.logger.info(
            "[MISSION] Primary: %s | %s.",
            getattr(objective, "quest_name", "No active Quest"),
            self.objective_label(objective),
        )
        self.logger.info(
            "[STEP] No safe action is currently available; "
            "the Quest board will be re-evaluated."
        )
        self.write_current_plan(
            step="NO SAFE ACTION",
            character=character,
            details="Waiting for the next safe plan",
        )

    def execute_fight(self, candidate) -> bool:
        row = (
            self._selected_row
            if isinstance(self._selected_row, dict)
            else None
        )
        before = self.get_character()
        hp_before = as_int(before.get("hp"), 0)
        stamina_before = as_int(
            before.get("stamina"),
            0,
        )

        result = super().execute_fight(candidate)

        after = self.get_character()
        hp_after = as_int(after.get("hp"), 0)
        stamina_after = as_int(
            after.get("stamina"),
            0,
        )
        name = self.monster_name(candidate)

        if self._selected_role == "OPPORTUNITY":
            self.director["opportunity_used"] = True
            self.director["opportunity_actions"] = (
                as_int(
                    self.director.get(
                        "opportunity_actions"
                    ),
                    0,
                )
                + 1
            )
            self.save_director()

        signature = "|".join(
            [
                name,
                str(result),
                str(hp_before),
                str(hp_after),
                str(stamina_before),
                str(stamina_after),
            ]
        )
        if (
            signature
            != self.director.get(
                "last_result_signature"
            )
        ):
            self.director[
                "last_result_signature"
            ] = signature
            self.save_director()

            self.logger.info(
                "[RESULT] %s against %s | HP %s -> %s | "
                "STM %s -> %s.",
                "Victory" if result else "Fight failed",
                name,
                hp_before,
                hp_after,
                stamina_before,
                stamina_after,
            )

        return result

    # The inherited run loop is copied intentionally so logging happens
    # immediately before every resource, travel and combat stage.
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
            "[MODE] Transparent Quest Director with one-step "
            "opportunity scheduling."
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
                "transparent_quest_director_state": (
                    self.director
                ),
                "current_plan_file": str(
                    CURRENT_PLAN_FILE
                ),
                "live_log_file": str(LIVE_LOG_FILE),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v2_7_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v2_7_final_"
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
        bot = TransparentQuestDirector(
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
