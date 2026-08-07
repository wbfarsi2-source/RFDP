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
V30_FILE = SCRIPT_DIR / "eldoria_bot_v3_0_base.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_1_final_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV3_1_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"
LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v3_1_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"

if not V30_FILE.exists():
    raise RuntimeError(f"Required file is missing: {V30_FILE}")

spec = importlib.util.spec_from_file_location("eldoria_v30_base", V30_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V3.0 base could not be loaded.")

v30 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v30
spec.loader.exec_module(v30)

v29 = v30.v29
v281 = v30.v281
v271 = v30.v271
v27 = v30.v27
v26 = v30.v26
v25 = v30.v25
v24 = v30.v24
v232 = v30.v232
v22 = v30.v22
v21 = v30.v21
v161 = v30.v161
base = v30.base
engine = v30.engine

for module in (
    v30, v29, v281, v271, v27, v26, v25, v24,
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
    module.LAST_REPORT_FILE = OUTPUT_DIR / "eldoria_bot_v3_1_final_last_report.json"
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v30, v29, v281, v271, v27, v26, v25, v24,
    v232, v22, v21, v161, base,
):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE

for module in (v27, v271, v281, v29, v30):
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
    logger = logging.getLogger("eldoria_bot_v3_1_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    for target in (LOG_DIR / "eldoria_bot_v3_1_final.log", LIVE_LOG_FILE):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


class StrictCraftQuestDirector(v30.AdaptiveRecoveryCampaign):
    VERSION = "3.1-final-strict-craft-quest-director-windows"
    GENERIC_POTION_TARGETS = {
        "", "any", "star", "anypotion", "potionany", "anypotions",
    }

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)
        self.strict_file = STATE_DIR / "strict_craft_director_state.json"
        self.strict = engine.load_json(
            self.strict_file,
            {
                "schema_version": 1,
                "deferred": {},
                "active_plan": {},
                "material_attempts": {},
                "material_blacklist": {},
                "last_manager_at": 0.0,
                "force_manager": True,
                "last_plan_signature": "",
                "last_defer_signature": "",
                "direct_api_crafts": 0,
                "verified_quest_crafts": 0,
                "material_fights": 0,
                "material_drops": 0,
            },
        )
        if not isinstance(self.strict, dict):
            self.strict = {}
        defaults = {
            "schema_version": 1,
            "deferred": {},
            "active_plan": {},
            "material_attempts": {},
            "material_blacklist": {},
            "last_manager_at": 0.0,
            "force_manager": True,
            "last_plan_signature": "",
            "last_defer_signature": "",
            "direct_api_crafts": 0,
            "verified_quest_crafts": 0,
            "material_fights": 0,
            "material_drops": 0,
        }
        for key, default in defaults.items():
            self.strict.setdefault(key, default)
        for key in ("deferred", "material_attempts", "material_blacklist"):
            if not isinstance(self.strict.get(key), dict):
                self.strict[key] = {}
        self._strict_material_action = None
        self._strict_before_plan = None
        self.save_strict()

    def save_strict(self) -> None:
        engine.save_json(self.strict_file, self.strict)

    # Craft Quests are never combat campaigns. They are completed only by
    # verified Craft API calls in complete_craft_quests().
    def supported_campaign_objectives(self, objectives):
        return [
            objective
            for objective in super().supported_campaign_objectives(objectives)
            if objective.objective_type != "craft"
        ]

    @staticmethod
    def output_code(recipe: dict[str, Any]) -> str:
        output = recipe.get("output")
        if isinstance(output, dict):
            for key in ("code", "item_code", "slug"):
                value = str(output.get(key) or "").strip()
                if value:
                    return normalize(value)
        for key in ("output_code", "code"):
            value = str(recipe.get(key) or "").strip()
            if value:
                return normalize(value)
        return ""

    @staticmethod
    def ingredient_code(ingredient: dict[str, Any]) -> str:
        for key in ("code", "item_code", "material_code", "ingredient_code"):
            value = str(ingredient.get(key) or "").strip()
            if value:
                return normalize(value)
        item = ingredient.get("item")
        if isinstance(item, dict):
            return normalize(item.get("code") or item.get("item_code") or "")
        if isinstance(item, str):
            return normalize(item)
        return ""

    @staticmethod
    def drop_code(drop: dict[str, Any]) -> str:
        for key in ("code", "item_code", "drop_code", "material_code"):
            value = str(drop.get(key) or "").strip()
            if value:
                return normalize(value)
        item = drop.get("item")
        if isinstance(item, dict):
            return normalize(item.get("code") or item.get("item_code") or "")
        if isinstance(item, str):
            return normalize(item)
        return ""

    @staticmethod
    def drop_chance(drop: dict[str, Any], guaranteed: bool) -> float:
        if guaranteed:
            return 1.0
        chance = max(0.0, as_float(drop.get("chance"), 0.0))
        if chance > 1.0:
            chance /= 100.0
        return min(1.0, chance)

    def objective_deferred(self, objective) -> bool:
        key = self.objective_key(objective)
        record = self.strict["deferred"].get(key)
        if not isinstance(record, dict):
            return False
        retry_at = as_float(record.get("retry_at"), 0.0)
        if retry_at > time.time():
            return True
        self.strict["deferred"].pop(key, None)
        self.save_strict()
        return False

    def defer_craft(self, objective, reason: str, seconds: float) -> None:
        key = self.objective_key(objective)
        retry_at = time.time() + max(300.0, seconds)
        self.strict["deferred"][key] = {
            "quest_name": objective.quest_name,
            "reason": reason,
            "retry_at": retry_at,
        }
        signature = f"{key}|{reason}"
        if signature != self.strict.get("last_defer_signature"):
            self.strict["last_defer_signature"] = signature
            self.logger.info(
                "[CRAFT DEFER] %s | %s | retry in %s.",
                objective.quest_name,
                reason,
                v27.format_duration(seconds),
            )
        self.save_strict()

    def clear_craft_defer(self, objective) -> None:
        self.strict["deferred"].pop(self.objective_key(objective), None)
        self.save_strict()

    def matching_objective_remaining(self, objective, rows) -> int | None:
        key = self.objective_key(objective)
        for row in rows:
            if self.objective_key(row) == key:
                return row.remaining
        return None

    def resolve_recipes(self, objective, recipes):
        target = normalize(objective.target)
        generic = target in self.GENERIC_POTION_TARGETS
        result = []
        for recipe in recipes:
            if not isinstance(recipe, dict) or not recipe.get("id"):
                continue
            category = str(recipe.get("category") or "").lower()
            code = self.output_code(recipe)
            if generic:
                if category not in {"potion_hp", "potion_mp"}:
                    continue
            elif code != target:
                continue
            result.append(recipe)
        return result

    def recipe_plan(self, objective, recipe, character):
        ingredients = recipe.get("ingredients", [])
        if not isinstance(ingredients, list):
            ingredients = []
        shortages = {}
        capacity = max(1, objective.remaining)
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue
            code = self.ingredient_code(ingredient)
            qty = max(0, as_int(ingredient.get("qty"), 0))
            have = max(0, as_int(ingredient.get("have"), 0))
            if qty <= 0:
                continue
            capacity = min(capacity, have // qty)
            shortage = max(0, qty - have)
            if code and shortage > 0:
                shortages[code] = shortage
        gold = as_int(character.get("gold"), 0)
        reserve = max(
            as_int(self.config["economy"]["absolute_minimum_gold"], 0),
            int(gold * float(self.config["strict_craft"]["gold_reserve_ratio"])),
        )
        cost = max(0, as_int(recipe.get("gold_cost"), 0))
        if cost > 0:
            capacity = min(capacity, max(0, (gold - reserve) // cost))
        return {
            "objective_key": self.objective_key(objective),
            "quest_name": objective.quest_name,
            "quest_type": objective.quest_type,
            "target": objective.target,
            "remaining": objective.remaining,
            "recipe_id": recipe.get("id"),
            "recipe_name": (
                recipe.get("name")
                or (recipe.get("output") or {}).get("name")
                or self.output_code(recipe)
                or "Recipe"
            ),
            "output_code": self.output_code(recipe),
            "gold_cost": cost,
            "capacity": max(0, capacity),
            "shortages": shortages,
            "total_shortage": sum(shortages.values()),
        }

    def plan_signature(self, plan) -> str:
        shortages = ",".join(
            f"{key}:{value}"
            for key, value in sorted(plan.get("shortages", {}).items())
        )
        return (
            f"{plan.get('objective_key')}|{plan.get('recipe_id')}|{shortages}"
        )

    def log_craft_plan(self, plan) -> None:
        signature = self.plan_signature(plan)
        if signature == self.strict.get("last_plan_signature"):
            return
        self.strict["last_plan_signature"] = signature
        needs = ", ".join(
            f"{code} x{qty}"
            for code, qty in sorted(plan.get("shortages", {}).items())
        ) or "none"
        self.logger.info(
            "[CRAFT PLAN] %s | recipe %s | next Craft needs: %s.",
            plan.get("quest_name"),
            plan.get("recipe_name"),
            needs,
        )
        self.save_strict()

    def complete_craft_quests(self) -> dict[str, int]:
        now = time.time()
        interval = float(self.config["strict_craft"]["manager_interval_seconds"])
        if (
            not self.strict.get("force_manager")
            and now - as_float(self.strict.get("last_manager_at"), 0.0) < interval
        ):
            return {}
        self.strict["force_manager"] = False
        self.strict["last_manager_at"] = now
        self.strict["active_plan"] = {}
        self.save_strict()

        objectives = [
            row for row in self.objective_rows()
            if row.objective_type == "craft"
        ]
        if not objectives:
            return {}

        try:
            recipes = self.recipe_rows()
            character = self.get_character()
        except Exception as exc:
            self.logger.info("[CRAFT MANAGER] Server read failed; retry later: %s", exc)
            return {}

        material_plans = []
        for objective in objectives:
            if self.objective_deferred(objective):
                continue
            candidates = self.resolve_recipes(objective, recipes)
            if not candidates:
                self.defer_craft(
                    objective,
                    "no matching server Recipe was found",
                    float(self.config["strict_craft"]["no_recipe_defer_seconds"]),
                )
                continue

            plans = [self.recipe_plan(objective, recipe, character) for recipe in candidates]
            plans.sort(
                key=lambda row: (
                    row["capacity"] <= 0,
                    row["total_shortage"],
                    row["gold_cost"],
                )
            )
            plan = plans[0]

            if plan["capacity"] > 0:
                count = min(
                    objective.remaining,
                    plan["capacity"],
                    int(self.config["strict_craft"]["max_direct_crafts_per_cycle"]),
                )
                before = objective.remaining
                api_success = 0
                self.logger.info(
                    "[CRAFT ACTION] %s | crafting %s x%s.",
                    objective.quest_name,
                    plan["recipe_name"],
                    count,
                )
                for _ in range(count):
                    result = self.client.post(
                        f"crafting/table/craft/{plan['recipe_id']}"
                    )
                    if not result.ok:
                        self.logger.info(
                            "[CRAFT API] %s failed | status=%s error=%s.",
                            objective.quest_name,
                            result.status,
                            result.error,
                        )
                        break
                    api_success += 1
                    self.strict["direct_api_crafts"] = (
                        as_int(self.strict.get("direct_api_crafts"), 0) + 1
                    )
                    time.sleep(float(self.config["automation"]["action_delay_seconds"]))

                if api_success <= 0:
                    self.defer_craft(
                        objective,
                        "Craft API did not accept the Recipe",
                        float(self.config["strict_craft"]["api_failure_defer_seconds"]),
                    )
                    continue

                self.invalidate_quest_cache()
                time.sleep(float(self.config["strict_craft"]["verification_delay_seconds"]))
                try:
                    self.get_quests(force=True)
                    refreshed = self.objective_rows()
                    after = self.matching_objective_remaining(objective, refreshed)
                except Exception as exc:
                    self.logger.info(
                        "[CRAFT VERIFY] Network delayed verification for %s: %s",
                        objective.quest_name,
                        exc,
                    )
                    self.strict["force_manager"] = True
                    self.save_strict()
                    continue

                if after is None or after < before:
                    self.strict["verified_quest_crafts"] = (
                        as_int(self.strict.get("verified_quest_crafts"), 0)
                        + (before if after is None else before - after)
                    )
                    self.clear_craft_defer(objective)
                    self.logger.info(
                        "[CRAFT PROGRESS] %s | %s -> %s.",
                        objective.quest_name,
                        before,
                        "completed" if after is None else after,
                    )
                    self.strict["force_manager"] = True
                    self.save_strict()
                else:
                    self.defer_craft(
                        objective,
                        "Craft API succeeded but the Quest counter did not change",
                        float(self.config["strict_craft"]["incompatible_recipe_defer_seconds"]),
                    )
                continue

            if not plan["shortages"]:
                self.defer_craft(
                    objective,
                    "Recipe is blocked by the Gold safety reserve",
                    float(self.config["strict_craft"]["gold_defer_seconds"]),
                )
                continue

            material_plans.append(plan)

        if material_plans:
            material_plans.sort(
                key=lambda row: (
                    self.QUEST_TYPE_RANK.get(row["quest_type"], 9),
                    row["total_shortage"],
                    row["remaining"],
                    row["gold_cost"],
                )
            )
            chosen = material_plans[0]
            self.strict["active_plan"] = chosen
            self.log_craft_plan(chosen)
            self.save_strict()
        return {}

    def expected_material_units(self, monster, shortages) -> float:
        expected = 0.0
        matched = set()
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
                if code not in shortages:
                    continue
                matched.add(code)
                expected += (
                    self.drop_chance(drop, guaranteed)
                    * max(1.0, as_float(drop.get("qty"), 1.0))
                )
        if not matched:
            return 0.0
        coverage = len(matched) / max(1, len(shortages))
        return expected * coverage

    def blacklist_key(self, plan, monster_id: int) -> str:
        return f"{self.plan_signature(plan)}|monster:{monster_id}"

    def material_blacklisted(self, plan, monster_id: int) -> bool:
        key = self.blacklist_key(plan, monster_id)
        until = as_float(self.strict["material_blacklist"].get(key), 0.0)
        if until > time.time():
            return True
        self.strict["material_blacklist"].pop(key, None)
        return False

    def find_strict_material_row(self, states, character, pending):
        plan = self.strict.get("active_plan")
        if not isinstance(plan, dict) or not plan.get("shortages"):
            return None
        signature = self.plan_signature(plan)
        if as_int(self.strict["material_attempts"].get(signature), 0) >= int(
            self.config["strict_craft"]["max_material_fights_per_plan"]
        ):
            return None

        hp = as_int(character.get("hp"), 0)
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        minimum_after = max(
            int(self.config["combat"]["minimum_hp_after_battle"]),
            math.ceil(hp_max * float(self.config["strict_craft"]["minimum_hp_after_ratio"])),
        )
        choices = []
        for row in states:
            if row.get("state") != "ready":
                continue
            candidate = row.get("candidate")
            if candidate is None or self.is_boss(candidate.monster):
                continue
            monster_id = as_int(candidate.monster.get("id"), 0)
            if monster_id <= 0 or self.material_blacklisted(plan, monster_id):
                continue
            risk = as_float(row.get("risk_ratio"), 999.0)
            if risk > float(self.config["strict_craft"]["maximum_material_risk_ratio"]):
                continue
            damage = max(0.0, as_float(row.get("estimate"), candidate.predicted_damage))
            if hp - math.ceil(damage) < minimum_after:
                continue
            expected = self.expected_material_units(candidate.monster, plan["shortages"])
            if expected < float(self.config["strict_craft"]["minimum_expected_material_units"]):
                continue
            added_delay = 0.0
            if isinstance(pending, dict):
                added_delay = self.added_primary_delay(pending, row, character)
                current_wait = self.pending_wait_seconds(pending, character)
                allowed = min(
                    float(self.config["strict_craft"]["maximum_added_delay_seconds"]),
                    current_wait * float(self.config["strict_craft"]["maximum_added_delay_ratio"]),
                )
                if not math.isfinite(added_delay) or added_delay > allowed:
                    continue
            score = (
                expected * 1000.0
                - damage * 4.0
                - added_delay / 60.0 * 10.0
                + as_int(getattr(candidate, "quest_overlap", 0), 0) * 100.0
            )
            choices.append((score, row, expected, added_delay, plan))
        if not choices:
            return None
        choices.sort(key=lambda item: -item[0])
        return choices[0]

    def choose_action(self, character, objectives, material_needs):
        # Never pass broad inherited Craft needs into the generic monster
        # selector. Strict material farming is handled below with exact drops.
        selected, states = super().choose_action(character, objectives, {})
        self._strict_material_action = None
        if selected is not None:
            return selected, states

        pending = self._primary_pending if isinstance(self._primary_pending, dict) else None
        choice = self.find_strict_material_row(states, character, pending)
        if choice is None:
            return selected, states

        _, row, expected, added_delay, plan = choice
        self._selected_row = row
        self._selected_role = "STRICT CRAFT MATERIAL"
        self._strict_material_action = {
            "plan": dict(plan),
            "expected_units": expected,
            "added_delay": added_delay,
        }
        self._strict_before_plan = dict(plan)
        self.logger.info(
            "[STRICT CRAFT MATERIAL] %s -> %s | exact needed drops %s | "
            "expected %.2f item/fight | added primary delay %s.",
            self.monster_name(row["candidate"]),
            plan.get("recipe_name"),
            ", ".join(sorted(plan.get("shortages", {}))),
            expected,
            v27.format_duration(added_delay),
        )
        return row, states

    def execute_fight(self, candidate) -> bool:
        if self._selected_role != "STRICT CRAFT MATERIAL":
            return super().execute_fight(candidate)

        plan = self._strict_before_plan if isinstance(self._strict_before_plan, dict) else {}
        signature = self.plan_signature(plan)
        monster_id = as_int(candidate.monster.get("id"), 0)
        before_shortage = as_int(plan.get("total_shortage"), 0)
        objective = self._primary_objective
        campaign_remaining = self.campaign.get("active_remaining")
        self._primary_objective = None
        try:
            result = super().execute_fight(candidate)
        finally:
            self._primary_objective = objective
            self.campaign["active_remaining"] = campaign_remaining
            self.save_campaign()

        self.strict["material_attempts"][signature] = (
            as_int(self.strict["material_attempts"].get(signature), 0) + 1
        )
        if result:
            self.strict["material_fights"] = as_int(self.strict.get("material_fights"), 0) + 1
        self.strict["force_manager"] = True
        self.save_strict()
        if not result:
            return result

        self.complete_craft_quests()
        after_plan = self.strict.get("active_plan")
        after_shortage = (
            as_int(after_plan.get("total_shortage"), before_shortage)
            if isinstance(after_plan, dict)
            and after_plan.get("objective_key") == plan.get("objective_key")
            else 0
        )
        if after_shortage < before_shortage:
            self.strict["material_drops"] = as_int(self.strict.get("material_drops"), 0) + 1
            self.strict["material_attempts"].pop(signature, None)
            self.logger.info(
                "[CRAFT MATERIAL PROGRESS] %s | missing materials %s -> %s.",
                plan.get("quest_name"),
                before_shortage,
                after_shortage,
            )
        else:
            attempts = as_int(self.strict["material_attempts"].get(signature), 0)
            self.logger.info(
                "[CRAFT MATERIAL CHECK] %s dropped no verified needed material | %s/%s.",
                self.monster_name(candidate),
                attempts,
                int(self.config["strict_craft"]["no_drop_blacklist_attempts"]),
            )
            if attempts >= int(self.config["strict_craft"]["no_drop_blacklist_attempts"]):
                self.strict["material_blacklist"][self.blacklist_key(plan, monster_id)] = (
                    time.time()
                    + float(self.config["strict_craft"]["material_blacklist_seconds"])
                )
                self.strict["material_attempts"].pop(signature, None)
                self.logger.info(
                    "[CRAFT MATERIAL BLACKLIST] %s is paused for this Recipe; "
                    "another exact source will be tested.",
                    self.monster_name(candidate),
                )
        self.save_strict()
        return result

    def write_current_plan(self, *, step: str, row=None, character=None, details: str = "") -> None:
        super().write_current_plan(
            step=step,
            row=row,
            character=character,
            details=details,
        )
        plan = self.strict.get("active_plan")
        lines = ["", "STRICT CRAFT DIRECTOR", "Craft Quests are never combat campaigns."]
        if isinstance(plan, dict) and plan:
            lines.extend(
                [
                    f"Background Craft Quest: {plan.get('quest_name')}",
                    f"Verified Recipe: {plan.get('recipe_name')}",
                    "Exact shortages: " + json.dumps(plan.get("shortages", {}), ensure_ascii=False),
                ]
            )
        else:
            lines.append("Background Craft plan: none currently actionable")
        with CURRENT_PLAN_FILE.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def final_report(self):
        report = super().final_report()
        report.update({"version": self.VERSION, "strict_craft_state": self.strict})
        engine.save_json(OUTPUT_DIR / "eldoria_bot_v3_1_final_last_report.json", report)
        engine.save_json(
            OUTPUT_DIR / ("eldoria_bot_v3_1_final_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"),
            report,
        )
        return report


def main() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        print(f"Configuration file is missing: {CONFIG_FILE}")
        return 2
    config = engine.load_json(CONFIG_FILE, {})
    logger = configure_logging()
    try:
        client = engine.APIClient(config, logger)
        bot = StrictCraftQuestDirector(client, config, logger)
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
