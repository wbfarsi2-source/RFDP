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
V29_FILE = SCRIPT_DIR / "eldoria_bot_v2_9_base.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_0_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV3_0_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v3_0_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

if not V29_FILE.exists():
    raise RuntimeError(f"Required file is missing: {V29_FILE}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v29_base",
    V29_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V2.9 base could not be loaded.")

v29 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v29
spec.loader.exec_module(v29)

v281 = v29.v281
v271 = v29.v271
v27 = v29.v27
v26 = v29.v26
v25 = v29.v25
v24 = v29.v24
v232 = v29.v232
v22 = v29.v22
v21 = v29.v21
v161 = v29.v161
base = v29.base
engine = v29.engine

for module in (
    v29, v281, v271, v27, v26, v25, v24,
    v232, v22, v21, v161, base, engine,
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
        OUTPUT_DIR / "eldoria_bot_v3_0_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v29, v281, v271, v27, v26, v25,
    v24, v232, v22, v21, v161, base,
):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE

for module in (v27, v271, v281, v29):
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

    logger = logging.getLogger("eldoria_bot_v3_0_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v3_0_final.log",
        LIVE_LOG_FILE,
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


class AdaptiveRecoveryCampaign(v29.GuaranteedProgressQuestDirector):
    VERSION = "3.0-final-adaptive-recovery-campaign-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.recovery_file = (
            STATE_DIR / "adaptive_recovery_campaign_state.json"
        )
        self.recovery = engine.load_json(
            self.recovery_file,
            {
                "schema_version": 1,
                "recovery_focus": False,
                "last_survival_optimization_at": 0.0,
                "last_survival_level": 0,
                "last_server_limit_signature": "",
                "last_server_limit_at": 0.0,
                "recipe_cache": {},
                "recipe_cache_at": 0.0,
                "material_wait_key": "",
                "material_actions": 0,
                "material_fights": 0,
                "material_successes": 0,
                "survival_optimizations": 0,
            },
        )
        if not isinstance(self.recovery, dict):
            self.recovery = {}

        defaults = {
            "schema_version": 1,
            "recovery_focus": False,
            "last_survival_optimization_at": 0.0,
            "last_survival_level": 0,
            "last_server_limit_signature": "",
            "last_server_limit_at": 0.0,
            "recipe_cache": {},
            "recipe_cache_at": 0.0,
            "material_wait_key": "",
            "material_actions": 0,
            "material_fights": 0,
            "material_successes": 0,
            "survival_optimizations": 0,
        }
        for key, default in defaults.items():
            self.recovery.setdefault(key, default)

        self._recovery_focus_active = False
        self._recovery_material_plan = None
        self._recovery_primary_pending = None
        self._recovery_material_before = None
        self.save_recovery()

    def save_recovery(self) -> None:
        engine.save_json(self.recovery_file, self.recovery)

    # Honest ETA: overlap helps value, not server regeneration speed.
    def objective_expected_seconds(
        self,
        objective,
        states,
        character: dict[str, Any],
    ) -> tuple[float, Any | None, float]:
        if objective.objective_type == "craft":
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

        rows = self.matching_rows(objective, states)
        best_total = float("inf")
        best_row = None
        best_rate = 0.0

        for row in rows:
            if row.get("state") == "strengthen":
                continue

            rate = self.progress_per_fight(objective, row)
            if rate <= 0:
                continue

            fights = max(1, math.ceil(objective.remaining / rate))
            first_wait, repeat_cycle = self.row_cycle_seconds(
                row,
                character,
            )
            total = first_wait + max(0, fights - 1) * repeat_cycle

            if total < best_total:
                best_total = total
                best_row = row
                best_rate = rate

        return best_total, best_row, best_rate

    # Long waits switch every inherited attribute/equipment/Forge decision
    # toward survival.
    def active_training_focus(self) -> str:
        if self._recovery_focus_active:
            return "survival"
        return super().active_training_focus()

    def pending_wait_seconds(
        self,
        pending,
        character: dict[str, Any],
    ) -> float:
        if not isinstance(pending, dict):
            return 0.0
        return max(
            self.hp_wait_seconds(
                character,
                as_int(pending.get("required_hp"), 0),
            ),
            self.stamina_wait_seconds(
                character,
                as_int(pending.get("stamina_target"), 0),
            ),
        )

    def run_survival_optimization(
        self,
        pending,
        character: dict[str, Any],
    ) -> bool:
        wait_seconds = self.pending_wait_seconds(pending, character)
        threshold = float(
            self.config["adaptive_recovery"][
                "survival_focus_wait_seconds"
            ]
        )
        self._recovery_focus_active = wait_seconds >= threshold
        self.recovery["recovery_focus"] = self._recovery_focus_active
        self.save_recovery()

        if not self._recovery_focus_active:
            return False

        now = time.time()
        level = as_int(character.get("level"), 1)
        cooldown = float(
            self.config["adaptive_recovery"][
                "survival_optimization_cooldown_seconds"
            ]
        )
        if (
            now
            - as_float(
                self.recovery.get("last_survival_optimization_at"),
                0.0,
            )
            < cooldown
            and level
            == as_int(
                self.recovery.get("last_survival_level"),
                0,
            )
        ):
            return False

        before_hp_max = as_int(character.get("hp_max"), 0)
        self.logger.info(
            "[RECOVERY OPTIMIZER] Wait %s | prioritizing Vitality, "
            "Resistance, defensive gear and efficient Forge.",
            v27.format_duration(wait_seconds),
        )
        self.safe_step("Recovery Skills", self.optimize_skills)
        self.safe_step("Recovery Skill Tree", self.optimize_skill_tree)
        self.safe_step(
            "Recovery Survival Progression",
            self.optimize_progression,
        )

        self.recovery["last_survival_optimization_at"] = now
        self.recovery["last_survival_level"] = level
        self.recovery["survival_optimizations"] = (
            as_int(self.recovery.get("survival_optimizations"), 0) + 1
        )
        self.save_recovery()

        try:
            after = self.get_character()
            after_hp_max = as_int(after.get("hp_max"), 0)
            if after_hp_max != before_hp_max:
                self.logger.info(
                    "[RECOVERY UPGRADE] HP Max %s -> %s.",
                    before_hp_max,
                    after_hp_max,
                )
        except Exception:
            pass

        return True

    @staticmethod
    def ingredient_code(row: dict[str, Any]) -> str:
        for key in (
            "code",
            "item_code",
            "material_code",
            "ingredient_code",
        ):
            value = str(row.get(key) or "").strip()
            if value:
                return normalize(value)

        item = row.get("item")
        if isinstance(item, dict):
            value = str(
                item.get("code") or item.get("item_code") or ""
            ).strip()
            if value:
                return normalize(value)
        return ""

    @staticmethod
    def drop_code(row: dict[str, Any]) -> str:
        for key in (
            "code",
            "item_code",
            "drop_code",
            "material_code",
        ):
            value = str(row.get(key) or "").strip()
            if value:
                return normalize(value)

        item = row.get("item")
        if isinstance(item, dict):
            return normalize(
                item.get("code") or item.get("item_code") or ""
            )
        if isinstance(item, str):
            return normalize(item)
        return ""

    @staticmethod
    def normalized_chance(value: Any, guaranteed: bool) -> float:
        if guaranteed:
            return 1.0
        chance = max(0.0, as_float(value, 0.0))
        if chance > 1.0:
            chance /= 100.0
        return min(1.0, chance)

    def output_heal(self, recipe: dict[str, Any]) -> int:
        output = recipe.get("output")
        if not isinstance(output, dict):
            output = {}

        effects = output.get("effects")
        if not isinstance(effects, dict):
            effects = engine.parse_json_field(effects, {})
        if not isinstance(effects, dict):
            effects = {}

        heal = effects.get("heal")
        if heal == "max":
            current = getattr(self, "_scheduler_character", {})
            return as_int(current.get("hp_max"), 0)

        parsed = as_int(heal, 0)
        if parsed > 0:
            return parsed

        return int(
            self.config["adaptive_recovery"][
                "unknown_hp_potion_heal"
            ]
        )

    def hp_recipe_plan(self, force: bool = False):
        now = time.time()
        cache_seconds = float(
            self.config["adaptive_recovery"]["recipe_cache_seconds"]
        )
        cached = self.recovery.get("recipe_cache")

        if (
            not force
            and isinstance(cached, dict)
            and cached
            and now
            - as_float(self.recovery.get("recipe_cache_at"), 0.0)
            < cache_seconds
        ):
            return cached

        try:
            recipes = self.common_potion_recipes()
        except Exception:
            return None

        plans = []
        for recipe in recipes:
            if str(recipe.get("category") or "").lower() != "potion_hp":
                continue

            shortages = {}
            total = 0
            ingredients = recipe.get("ingredients", [])
            if not isinstance(ingredients, list):
                ingredients = []

            for ingredient in ingredients:
                if not isinstance(ingredient, dict):
                    continue
                code = self.ingredient_code(ingredient)
                qty = max(0, as_int(ingredient.get("qty"), 0))
                have = max(0, as_int(ingredient.get("have"), 0))
                shortage = max(0, qty - have)
                if code and shortage > 0:
                    shortages[code] = shortage
                    total += shortage

            plans.append(
                {
                    "recipe_id": recipe.get("id"),
                    "recipe_name": (
                        recipe.get("name")
                        or recipe.get("code")
                        or "HP Potion"
                    ),
                    "shortages": shortages,
                    "total_shortage": total,
                    "heal": self.output_heal(recipe),
                    "gold_cost": as_int(recipe.get("gold_cost"), 0),
                }
            )

        if not plans:
            return None

        plans.sort(
            key=lambda row: (
                row["total_shortage"],
                row["gold_cost"],
                -row["heal"],
            )
        )
        selected = plans[0]
        self.recovery["recipe_cache"] = selected
        self.recovery["recipe_cache_at"] = now
        self.save_recovery()
        return selected

    def expected_material_progress(
        self,
        monster: dict[str, Any],
        shortages: dict[str, int],
    ) -> float:
        if not shortages:
            return 0.0

        expected = {code: 0.0 for code in shortages}

        for list_key, guaranteed in (
            ("guaranteed_drops", True),
            ("chance_drops", False),
            ("drops", False),
        ):
            drops = monster.get(list_key)
            if not isinstance(drops, list):
                continue

            for drop in drops:
                if not isinstance(drop, dict):
                    continue
                code = self.drop_code(drop)
                if code not in expected:
                    continue
                expected[code] += (
                    self.normalized_chance(
                        drop.get("chance"),
                        guaranteed,
                    )
                    * max(1.0, as_float(drop.get("qty"), 1.0))
                )

        fractions = []
        for code, shortage in shortages.items():
            amount = expected.get(code, 0.0)
            if amount > 0:
                fractions.append(min(1.0, amount / max(1, shortage)))

        if not fractions:
            return 0.0

        coverage = len(fractions) / max(1, len(shortages))
        return sum(fractions) / len(fractions) * coverage

    def reset_material_window(self, pending) -> None:
        key = self.pending_wait_key(pending)
        if key != self.recovery.get("material_wait_key"):
            self.recovery["material_wait_key"] = key
            self.recovery["material_actions"] = 0
            self.save_recovery()

    def find_recovery_material_action(
        self,
        pending,
        states,
        character: dict[str, Any],
    ):
        if not isinstance(pending, dict):
            return None

        wait_seconds = self.pending_wait_seconds(pending, character)
        if wait_seconds < float(
            self.config["adaptive_recovery"][
                "material_plan_minimum_wait_seconds"
            ]
        ):
            return None

        self.reset_material_window(pending)
        if as_int(self.recovery.get("material_actions"), 0) >= int(
            self.config["adaptive_recovery"][
                "maximum_material_actions_per_wait"
            ]
        ):
            return None

        recipe = self.hp_recipe_plan()
        if not isinstance(recipe, dict) or not recipe.get("shortages"):
            return None

        hp_regen = as_float(character.get("hp_regen_per_hour"), 0.0)
        if hp_regen <= 0:
            return None

        primary_candidate = pending.get("candidate")
        primary_id = (
            as_int(primary_candidate.monster.get("id"), 0)
            if primary_candidate is not None
            else 0
        )
        choices = []

        for row in states:
            if row.get("state") != "ready":
                continue

            candidate = row.get("candidate")
            if candidate is None:
                continue

            monster = candidate.monster
            monster_id = as_int(monster.get("id"), 0)
            if (
                monster_id <= 0
                or monster_id == primary_id
                or self.is_boss(monster)
            ):
                continue

            risk = as_float(row.get("risk_ratio"), 999.0)
            if risk > float(
                self.config["adaptive_recovery"][
                    "maximum_material_fight_risk"
                ]
            ):
                continue

            progress = self.expected_material_progress(
                monster,
                recipe["shortages"],
            )
            if progress <= 0:
                continue

            damage = max(
                0.0,
                as_float(
                    row.get("estimate"),
                    candidate.predicted_damage,
                ),
            )
            fight_recovery = damage / hp_regen * 3600.0
            expected_saved = (
                recipe["heal"] * progress / hp_regen * 3600.0
            )
            added_delay = self.added_primary_delay(
                pending,
                row,
                character,
            )
            allowed_delay = min(
                float(
                    self.config["adaptive_recovery"][
                        "maximum_material_added_delay_seconds"
                    ]
                ),
                wait_seconds
                * float(
                    self.config["adaptive_recovery"][
                        "maximum_material_delay_ratio"
                    ]
                ),
            )
            if (
                not math.isfinite(added_delay)
                or added_delay > allowed_delay
            ):
                continue

            required_ratio = float(
                self.config["adaptive_recovery"][
                    "minimum_material_time_gain_ratio"
                ]
            )
            if expected_saved <= fight_recovery * required_ratio:
                continue

            net = (
                expected_saved
                - fight_recovery
                - added_delay
                + as_int(
                    getattr(candidate, "quest_overlap", 0),
                    0,
                )
                * 300.0
                + candidate.xp_per_stamina * 10.0
            )
            choices.append(
                (
                    net,
                    row,
                    progress,
                    expected_saved,
                    fight_recovery,
                    recipe,
                )
            )

        if not choices:
            return None

        choices.sort(key=lambda item: -item[0])
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

        pending = (
            self._primary_pending
            if isinstance(self._primary_pending, dict)
            else None
        )
        self._recovery_primary_pending = pending
        self._recovery_material_plan = None

        if pending is not None:
            self.run_survival_optimization(pending, character)
        else:
            self._recovery_focus_active = False

        if selected is not None or pending is None:
            return selected, states

        material = self.find_recovery_material_action(
            pending,
            states,
            character,
        )
        if material is None:
            self.log_server_limit_once(pending, character)
            return selected, states

        _, row, progress, saved, cost, recipe = material
        self._selected_row = row
        self._selected_role = "RECOVERY MATERIAL"
        self._recovery_material_plan = {
            "recipe": recipe,
            "expected_progress": progress,
            "expected_saved_seconds": saved,
            "fight_recovery_seconds": cost,
        }
        self._recovery_material_before = dict(recipe)

        self.logger.info(
            "[RECOVERY MATERIAL] %s may supply %s materials | "
            "expected recipe progress %.0f%% | expected saved time %s.",
            self.monster_name(row["candidate"]),
            recipe["recipe_name"],
            progress * 100.0,
            v27.format_duration(saved),
        )
        return row, states

    def log_server_limit_once(
        self,
        pending,
        character: dict[str, Any],
    ) -> None:
        wait_seconds = self.pending_wait_seconds(pending, character)
        if wait_seconds <= 0:
            return

        candidate = pending.get("candidate")
        name = (
            self.monster_name(candidate)
            if candidate is not None
            else "current target"
        )
        signature = "|".join(
            [
                self.primary_key(),
                str(
                    candidate.monster.get("id")
                    if candidate is not None
                    else ""
                ),
                str(as_int(pending.get("required_hp"), 0)),
            ]
        )
        now = time.time()
        heartbeat = float(
            self.config["adaptive_recovery"][
                "server_limit_log_seconds"
            ]
        )
        if (
            signature
            == self.recovery.get("last_server_limit_signature")
            and now
            - as_float(
                self.recovery.get("last_server_limit_at"),
                0.0,
            )
            < heartbeat
        ):
            return

        self.recovery["last_server_limit_signature"] = signature
        self.recovery["last_server_limit_at"] = now
        self.save_recovery()
        self.logger.info(
            "[SERVER LIMIT] No safe Quest, useful Potion-material Fight "
            "or available recovery item is faster. Natural HP for %s "
            "is currently the fastest safe legal path (%s).",
            name,
            v27.format_duration(wait_seconds),
        )

    def execute_fight(self, candidate) -> bool:
        if self._selected_role != "RECOVERY MATERIAL":
            return super().execute_fight(candidate)

        objective = self._primary_objective
        campaign_remaining = self.campaign.get("active_remaining")
        self._primary_objective = None

        try:
            result = super().execute_fight(candidate)
        finally:
            self._primary_objective = objective
            self.campaign["active_remaining"] = campaign_remaining
            self.save_campaign()

        self.recovery["material_actions"] = (
            as_int(self.recovery.get("material_actions"), 0) + 1
        )
        if result:
            self.recovery["material_fights"] = (
                as_int(self.recovery.get("material_fights"), 0) + 1
            )
        self.recovery["recipe_cache"] = {}
        self.recovery["recipe_cache_at"] = 0.0
        self.save_recovery()

        if not result:
            return result

        before = (
            self._recovery_material_before
            if isinstance(self._recovery_material_before, dict)
            else {}
        )
        after = self.hp_recipe_plan(force=True)

        before_shortage = as_int(before.get("total_shortage"), 0)
        after_shortage = (
            as_int(after.get("total_shortage"), before_shortage)
            if isinstance(after, dict)
            else before_shortage
        )

        if after_shortage < before_shortage:
            self.recovery["material_successes"] = (
                as_int(self.recovery.get("material_successes"), 0) + 1
            )
            self.save_recovery()
            self.logger.info(
                "[RECOVERY MATERIAL RESULT] Missing ingredients %s -> %s.",
                before_shortage,
                after_shortage,
            )

        crafted = self.safe_step(
            "Immediate recovery Potion craft",
            lambda: self.craft_emergency_hp_potions(requested=1),
            0,
        )
        if crafted and isinstance(self._recovery_primary_pending, dict):
            required_hp = as_int(
                self._recovery_primary_pending.get("required_hp"),
                0,
            )
            self.safe_step(
                "Immediate recovery Potion use",
                lambda: self.use_hp_potions_until_safe(
                    required_hp,
                    high_priority=True,
                ),
                False,
            )
        return result

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
            "ADAPTIVE RECOVERY CAMPAIGN",
            (
                "Recovery focus: SURVIVAL"
                if self._recovery_focus_active
                else "Recovery focus: NORMAL"
            ),
        ]
        if isinstance(self._recovery_material_plan, dict):
            recipe = self._recovery_material_plan["recipe"]
            lines.extend(
                [
                    f"Planned Potion: {recipe['recipe_name']}",
                    (
                        "Missing materials: "
                        + json.dumps(
                            recipe["shortages"],
                            ensure_ascii=False,
                        )
                    ),
                ]
            )
        else:
            lines.append(
                "Recovery material target: none currently profitable"
            )

        with CURRENT_PLAN_FILE.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def final_report(self) -> dict[str, Any]:
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "adaptive_recovery_campaign_state": self.recovery,
            }
        )
        engine.save_json(
            OUTPUT_DIR / "eldoria_bot_v3_0_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v3_0_final_"
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
        bot = AdaptiveRecoveryCampaign(client, config, logger)
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
