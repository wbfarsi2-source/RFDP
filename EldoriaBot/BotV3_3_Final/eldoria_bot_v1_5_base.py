from __future__ import annotations

import importlib.util
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PROJECT_DIR = ELDORIA_ROOT / "BotV1_5"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

if not ENGINE_FILE.exists():
    raise RuntimeError(f"Engine file is missing: {ENGINE_FILE}")

spec = importlib.util.spec_from_file_location(
    "eldoria_engine_v1_5",
    ENGINE_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria engine could not be loaded.")

engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)

# Redirect all engine storage to the Windows V1.5 project.
engine.SCRIPT_DIR = SCRIPT_DIR
engine.DESKTOP = DESKTOP
engine.ELDORIA_ROOT = ELDORIA_ROOT
engine.PRIVATE_DIR = PRIVATE_DIR
engine.OUTPUT_DIR = OUTPUT_DIR
engine.PROJECT_DIR = PROJECT_DIR
engine.STATE_DIR = STATE_DIR
engine.LOG_DIR = LOG_DIR
engine.COOKIE_FILE = PRIVATE_DIR / "cookie.txt"
engine.TOKEN_FILE = PRIVATE_DIR / "token.txt"
engine.CONFIG_FILE = CONFIG_FILE
engine.COMBAT_HISTORY_FILE = STATE_DIR / "combat_history.json"
engine.RUNTIME_STATE_FILE = STATE_DIR / "runtime_state.json"
engine.LAST_REPORT_FILE = OUTPUT_DIR / "eldoria_bot_v1_5_last_report.json"
engine.LOG_COPY_FILE = OUTPUT_DIR / "eldoria_bot_v1_5.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def first_list(data: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [
                    row
                    for row in value
                    if isinstance(row, dict)
                ]

    return []


def first_dict(data: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value

    return None


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


def text_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False).lower()
    except Exception:
        return str(value).lower()


def configure_quiet_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import logging

    logger = logging.getLogger("eldoria_bot_v1_5")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v1_5.log",
        OUTPUT_DIR / "eldoria_bot_v1_5.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class AdvancedEldoriaBot(engine.EldoriaBot):
    VERSION = "1.5-windows-autopilot"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.achievements_claimed = 0
        self.skills_learned = 0
        self.skill_loadout_updates = 0
        self.skill_tree_allocations = 0
        self.dungeon_actions = 0
        self.world_boss_attacks = 0

        self.farm_history_file = STATE_DIR / "farm_history.json"
        self.farm_history = engine.load_json(
            self.farm_history_file,
            {},
        )

        self.special_state_file = STATE_DIR / "special_state.json"
        self.special_state = engine.load_json(
            self.special_state_file,
            {
                "dungeon_attempts": {},
                "world_boss_attacks": {},
            },
        )

    # ------------------------------------------------------------------
    # Quiet reward and progression systems
    # ------------------------------------------------------------------

    def claim_achievements(self) -> None:
        if not self.config["achievements"]["enabled"]:
            return

        result = self.client.get("achievements/list")
        if not result.ok:
            return

        rows = first_list(
            result.data,
            ("achievements", "items", "rows", "data"),
        )

        for row in rows:
            achievement_id = (
                row.get("id")
                or row.get("achievement_id")
            )
            if achievement_id is None:
                continue

            status = str(row.get("status", "")).lower()
            can_claim = bool(
                row.get("can_claim")
                or row.get("claimable")
                or (
                    row.get("completed")
                    and not row.get("claimed")
                )
                or status in {"completed", "claimable", "ready"}
            )

            if not can_claim:
                continue

            claim = self.client.post(
                f"achievements/claim/{achievement_id}"
            )

            self.record(
                "claim_achievement",
                claim.ok,
                {
                    "achievement_id": achievement_id,
                    "name": (
                        row.get("name_en")
                        or row.get("name")
                        or row.get("code")
                    ),
                    "status": claim.status,
                    "error": claim.error,
                    "response": claim.data,
                },
            )

            if claim.ok:
                self.achievements_claimed += 1
                gold = int(
                    engine.deep_find_number(
                        claim.data,
                        {"gold", "gold_gained", "reward_gold"},
                    )
                    or 0
                )
                self.total_gold_gained += gold
                self.logger.info(
                    "[ACHIEVEMENT] Claimed: %s%s",
                    (
                        row.get("name_en")
                        or row.get("name")
                        or row.get("code")
                    ),
                    f" | +{gold} Gold" if gold else "",
                )

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

    @staticmethod
    def skill_rows(data: Any) -> list[dict[str, Any]]:
        return first_list(
            data,
            (
                "skills",
                "catalog",
                "learned",
                "mine",
                "items",
                "rows",
                "data",
            ),
        )

    @staticmethod
    def skill_id(skill: dict[str, Any]) -> int | None:
        value = skill.get("id") or skill.get("skill_id")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def skill_point_cost(skill: dict[str, Any]) -> int:
        for key in (
            "skill_point_cost",
            "point_cost",
            "points_cost",
            "cost_points",
            "cost",
        ):
            value = skill.get(key)
            if isinstance(value, (int, float)):
                return max(1, int(value))

        return 1

    def advanced_skill_score(
        self,
        skill: dict[str, Any],
        race: str,
    ) -> float:
        blob = text_blob(skill)
        score = float(self.skill_score(skill))

        skill_type = str(skill.get("type", "")).lower()
        if skill_type == "active":
            score += 100
        elif skill_type == "passive":
            score += 40

        if race == "drakkar":
            if "strength" in blob or "physical" in blob:
                score += 60
            if "attack" in blob or "damage" in blob:
                score += 45

        if "heal" in blob or "lifesteal" in blob:
            score += 35
        if "defense" in blob or "shield" in blob:
            score += 25
        if "gold" in blob:
            score += 80
        if "stamina" in blob:
            score += 35

        mp_cost = max(1, self.skill_mp_cost(skill))
        score -= mp_cost * 0.35

        return score

    def optimize_skills(self) -> None:
        if not self.config["skills_advanced"]["enabled"]:
            return

        catalog_result = self.client.get("skills/catalog")
        mine_result = self.client.get("skills/mine")

        if not catalog_result.ok or not mine_result.ok:
            return

        catalog = self.skill_rows(catalog_result.data)
        learned = self.skill_rows(mine_result.data)

        character = self.get_character()
        level = int(character.get("level") or 1)
        points = int(character.get("skill_points") or 0)
        race = str(character.get("race") or "").lower()

        learned_ids = {
            skill_id
            for skill in learned
            if (skill_id := self.skill_id(skill)) is not None
        }

        candidates = []

        for skill in catalog:
            skill_id = self.skill_id(skill)
            if skill_id is None or skill_id in learned_ids:
                continue

            required_level = as_int(
                skill.get("level_req")
                or skill.get("required_level")
                or skill.get("min_level"),
                1,
            )
            if required_level > level:
                continue

            gem_cost = as_int(
                skill.get("gem_cost")
                or skill.get("gems_cost"),
                0,
            )
            if gem_cost > 0:
                continue

            if skill.get("can_learn") is False:
                continue

            cost = self.skill_point_cost(skill)
            if cost > points:
                continue

            candidates.append(
                (
                    self.advanced_skill_score(skill, race),
                    cost,
                    skill,
                )
            )

        candidates.sort(
            key=lambda row: (
                -row[0],
                row[1],
            )
        )

        max_learns = int(
            self.config["skills_advanced"][
                "max_skills_learned_per_cycle"
            ]
        )

        learned_this_cycle = 0

        for score, cost, skill in candidates:
            if learned_this_cycle >= max_learns:
                break
            if cost > points:
                continue

            skill_id = self.skill_id(skill)
            if skill_id is None:
                continue

            result = self.client.post(f"skills/learn/{skill_id}")

            self.record(
                "learn_skill",
                result.ok,
                {
                    "skill_id": skill_id,
                    "skill": (
                        skill.get("name_en")
                        or skill.get("name")
                        or skill.get("code")
                    ),
                    "score": round(score, 2),
                    "point_cost": cost,
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                points -= cost
                learned_this_cycle += 1
                self.skills_learned += 1
                self.logger.info(
                    "[SKILL] Learned: %s",
                    (
                        skill.get("name_en")
                        or skill.get("name")
                        or skill.get("code")
                    ),
                )

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

        # Refresh learned skills and create the strongest PvE loadout.
        refreshed = self.client.get("skills/mine")
        if not refreshed.ok:
            return

        learned = self.skill_rows(refreshed.data)
        active = [
            row
            for row in learned
            if str(row.get("type", "")).lower() == "active"
            and self.skill_id(row) is not None
        ]

        if not active:
            return

        active.sort(
            key=lambda row: self.advanced_skill_score(
                row,
                race,
            ),
            reverse=True,
        )

        options = self.client.get("dungeons/loadout-options")
        max_pick = 3
        if options.ok:
            max_pick = as_int(
                engine.recursive_find(
                    options.data,
                    {"max_pick", "max_skills", "slots"},
                ),
                3,
            )

        order = [
            self.skill_id(row)
            for row in active[:max(1, max_pick)]
        ]
        order = [
            skill_id
            for skill_id in order
            if skill_id is not None
        ]

        if not order:
            return

        current = self.client.get("skills/loadout")
        current_blob = text_blob(current.data) if current.ok else ""

        if all(str(skill_id) in current_blob for skill_id in order):
            return

        modes = self.config["skills_advanced"]["loadout_modes"]

        for mode in modes:
            result = self.client.post(
                "skills/loadout",
                {
                    "mode": mode,
                    "order": order,
                },
            )

            if result.ok:
                self.skill_loadout_updates += 1
                self.logger.info(
                    "[SKILL] PvE loadout updated: %s",
                    ", ".join(map(str, order)),
                )
                self.record(
                    "set_skill_loadout",
                    True,
                    {
                        "mode": mode,
                        "order": order,
                        "response": result.data,
                    },
                )
                break

            if result.status not in {400, 404, 422}:
                break

    def skill_tree_score(
        self,
        node: dict[str, Any],
    ) -> float:
        blob = text_blob(node)
        score = 0.0

        keywords = {
            "gold": 120,
            "damage": 80,
            "attack": 75,
            "strength": 70,
            "lifesteal": 65,
            "stamina": 60,
            "hp": 45,
            "vitality": 45,
            "defense": 40,
            "resistance": 35,
            "crit": 35,
            "dodge": 25,
            "mana": 15,
        }

        for keyword, value in keywords.items():
            if keyword in blob:
                score += value

        level = as_int(
            node.get("level")
            or node.get("current_level"),
            0,
        )
        score -= level * 5

        return score

    def optimize_skill_tree(self) -> None:
        if not self.config["skill_tree"]["enabled"]:
            return

        catalog_result = self.client.get("skill-tree/catalog")
        mine_result = self.client.get("skill-tree/mine")

        if not catalog_result.ok or not mine_result.ok:
            return

        catalog = first_list(
            catalog_result.data,
            ("nodes", "catalog", "items", "rows", "data"),
        )
        mine_rows = first_list(
            mine_result.data,
            ("nodes", "mine", "items", "rows", "data"),
        )

        character = self.get_character()
        points = int(
            character.get("skill_tree_points") or 0
        )

        if points <= 0:
            return

        current_by_code = {
            str(
                row.get("code")
                or row.get("node_code")
                or ""
            ): row
            for row in mine_rows
        }

        candidates = []

        for node in catalog:
            code = str(
                node.get("code")
                or node.get("node_code")
                or ""
            )
            if not code:
                continue

            current = current_by_code.get(code, {})
            can_allocate = (
                node.get("can_allocate")
                if "can_allocate" in node
                else current.get("can_allocate")
            )

            if can_allocate is not True:
                continue

            cost = as_int(
                node.get("point_cost")
                or node.get("cost")
                or current.get("point_cost"),
                1,
            )

            if cost > points:
                continue

            max_level = as_int(
                node.get("max_level"),
                1,
            )
            current_level = as_int(
                current.get("level")
                or current.get("current_level"),
                0,
            )

            if current_level >= max_level:
                continue

            candidates.append(
                (
                    self.skill_tree_score(
                        {**node, **current}
                    ),
                    cost,
                    code,
                    node,
                )
            )

        candidates.sort(
            key=lambda row: (-row[0], row[1])
        )

        limit = int(
            self.config["skill_tree"][
                "max_allocations_per_cycle"
            ]
        )
        allocated = 0

        for score, cost, code, node in candidates:
            if allocated >= limit or cost > points:
                break

            result = self.client.post(
                f"skill-tree/allocate/{code}"
            )

            if (
                not result.ok
                and result.status in {400, 422}
                and node.get("can_allocate_path")
            ):
                result = self.client.post(
                    f"skill-tree/allocate-path/{code}"
                )

            self.record(
                "allocate_skill_tree",
                result.ok,
                {
                    "code": code,
                    "score": round(score, 2),
                    "point_cost": cost,
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                points -= cost
                allocated += 1
                self.skill_tree_allocations += 1
                self.logger.info(
                    "[TREE] Allocated: %s",
                    node.get("name_en")
                    or node.get("name")
                    or code,
                )

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

    # ------------------------------------------------------------------
    # Real observed Gold/STM learning
    # ------------------------------------------------------------------

    def update_farm_history(
        self,
        monster_id: int,
        gold: int,
        xp: int,
        stamina: int,
        duration_seconds: float,
    ) -> None:
        key = str(monster_id)
        row = self.farm_history.setdefault(
            key,
            {
                "count": 0,
                "gold": 0,
                "xp": 0,
                "stamina": 0,
                "seconds": 0.0,
            },
        )

        row["count"] = as_int(row.get("count")) + 1
        row["gold"] = as_int(row.get("gold")) + max(0, gold)
        row["xp"] = as_int(row.get("xp")) + max(0, xp)
        row["stamina"] = (
            as_int(row.get("stamina"))
            + max(0, stamina)
        )
        row["seconds"] = (
            as_float(row.get("seconds"))
            + max(0.01, duration_seconds)
        )

        engine.save_json(
            self.farm_history_file,
            self.farm_history,
        )

    def observed_gold_per_stamina(
        self,
        monster_id: int,
    ) -> float | None:
        row = self.farm_history.get(str(monster_id))

        if not isinstance(row, dict):
            return None

        count = as_int(row.get("count"))
        stamina = as_int(row.get("stamina"))

        if (
            count
            < int(
                self.config["farm_learning"][
                    "minimum_samples"
                ]
            )
            or stamina <= 0
        ):
            return None

        return as_float(row.get("gold")) / stamina

    def execute_fight(
        self,
        candidate,
    ) -> bool:
        started = time.monotonic()
        before = self.get_character()
        before_stamina = as_int(before.get("stamina"))

        success = super().execute_fight(candidate)

        if not success:
            return False

        after = self.get_character()
        after_stamina = as_int(after.get("stamina"))
        elapsed = time.monotonic() - started

        monster_id = as_int(
            candidate.monster.get("id")
        )
        stamina_used = max(
            0,
            before_stamina - after_stamina,
        )

        latest_action = (
            self.actions[-1]
            if self.actions
            else {}
        )
        response = (
            latest_action.get("details", {}).get("response")
            if isinstance(latest_action, dict)
            else {}
        )

        gold = int(
            engine.deep_find_number(
                response,
                {"gold_gained", "gold_reward"},
            )
            or 0
        )
        xp = int(
            engine.deep_find_number(
                response,
                {"xp_gained", "xp_reward"},
            )
            or 0
        )

        self.update_farm_history(
            monster_id=monster_id,
            gold=gold,
            xp=xp,
            stamina=stamina_used,
            duration_seconds=elapsed,
        )

        return True

    def build_farm_candidates(
        self,
        character,
        objectives,
        material_needs,
    ):
        candidates = super().build_farm_candidates(
            character,
            objectives,
            material_needs,
        )

        for candidate in candidates:
            monster_id = as_int(
                candidate.monster.get("id")
            )
            learned = self.observed_gold_per_stamina(
                monster_id
            )

            if learned is not None:
                candidate.gold_per_stamina = learned

        candidates.sort(
            key=lambda row: (
                row.priority,
                row.predicted_damage,
                row.required_hp,
                -row.material_score,
                -row.gold_per_stamina,
                -row.xp_per_stamina,
                as_int(row.monster.get("level")),
            )
        )

        return candidates

    # ------------------------------------------------------------------
    # Dynamic resource planning
    # ------------------------------------------------------------------

    def dynamic_stamina_target(
        self,
        candidate,
    ) -> int:
        monster_cost = max(
            1,
            as_int(candidate.monster.get("stamina_cost"), 1),
        )
        maximum = max(
            1,
            as_int(self.get_character().get("stamina_max"), 50),
        )
        reserve = int(
            self.config["dynamic_resources"][
                "emergency_stamina_reserve"
            ]
        )

        if candidate.priority == 0:
            repetitions = int(
                self.config["dynamic_resources"][
                    "specific_quest_fights"
                ]
            )
        elif candidate.priority == 1:
            repetitions = int(
                self.config["dynamic_resources"][
                    "material_farm_fights"
                ]
            )
        elif candidate.priority <= 3:
            repetitions = int(
                self.config["dynamic_resources"][
                    "general_quest_fights"
                ]
            )
        else:
            repetitions = 1

        target = monster_cost * repetitions + reserve

        return min(maximum, max(monster_cost + reserve, target))

    def dynamic_mp_target(
        self,
        candidate,
    ) -> int:
        if candidate.priority > 1:
            return 0

        skill = self.best_learned_skill()
        if skill is None:
            return 0

        cost = self.skill_mp_cost(skill)
        casts = int(
            self.config["dynamic_resources"][
                "skill_casts_for_priority_fight"
            ]
        )

        return cost * casts

    def wait_for_dynamic_targets(
        self,
        hp_target: int,
        stamina_target: int,
        mp_target: int,
        priority_label: str,
        allow_stamina_potion: bool,
    ) -> None:
        announced = False
        poll = int(
            self.config["continuous"]["poll_seconds"]
        )

        while True:
            character = self.get_character()

            hp = as_int(character.get("hp"))
            stamina = as_int(character.get("stamina"))
            mp = as_int(character.get("mp"))

            if (
                allow_stamina_potion
                and stamina < stamina_target
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

            hp_ready = hp >= hp_target
            stamina_ready = stamina >= stamina_target
            mp_ready = mp >= mp_target

            if hp_ready and stamina_ready and mp_ready:
                self.logger.info(
                    "[READY] %s | HP %s | STM %s | MP %s",
                    priority_label,
                    hp,
                    stamina,
                    mp,
                )
                return

            if not announced:
                missing = []

                if not hp_ready:
                    missing.append(f"HP {hp}/{hp_target}")
                if not stamina_ready:
                    missing.append(
                        f"STM {stamina}/{stamina_target}"
                    )
                if not mp_ready:
                    missing.append(f"MP {mp}/{mp_target}")

                self.logger.info(
                    "[WAIT] %s | %s",
                    priority_label,
                    ", ".join(missing),
                )
                announced = True

            time.sleep(poll)
            self.total_wait_seconds += poll

    # ------------------------------------------------------------------
    # Dungeon and World Boss autopilot
    # ------------------------------------------------------------------

    @staticmethod
    def extract_run_id(data: Any) -> int | None:
        value = engine.recursive_find(
            data,
            {
                "run_id",
                "dungeon_run_id",
                "runid",
            },
        )

        try:
            return int(value)
        except (TypeError, ValueError):
            pass

        run = first_dict(
            data,
            ("active_run", "run", "dungeon_run"),
        )

        if run:
            try:
                return int(run.get("id"))
            except (TypeError, ValueError):
                return None

        return None

    def dungeon_skill_ids(self) -> list[int]:
        result = self.client.get(
            "dungeons/loadout-options"
        )

        if not result.ok:
            return []

        rows = first_list(
            result.data,
            ("skills", "items", "rows", "data"),
        )
        max_pick = as_int(
            engine.recursive_find(
                result.data,
                {"max_pick", "max_skills", "slots"},
            ),
            3,
        )

        character = self.get_character()
        race = str(character.get("race") or "").lower()

        rows.sort(
            key=lambda row: self.advanced_skill_score(
                row,
                race,
            ),
            reverse=True,
        )

        output = []

        for row in rows[:max(1, max_pick)]:
            skill_id = self.skill_id(row)
            if skill_id is not None:
                output.append(skill_id)

        return output

    def dungeon_attempt_allowed(
        self,
        zone_id: int,
    ) -> bool:
        attempts = self.special_state.setdefault(
            "dungeon_attempts",
            {},
        )
        last = as_float(attempts.get(str(zone_id)))

        cooldown = float(
            self.config["dungeons"][
                "minimum_hours_between_attempts"
            ]
        ) * 3600

        return time.time() - last >= cooldown

    def mark_dungeon_attempt(
        self,
        zone_id: int,
    ) -> None:
        attempts = self.special_state.setdefault(
            "dungeon_attempts",
            {},
        )
        attempts[str(zone_id)] = time.time()
        engine.save_json(
            self.special_state_file,
            self.special_state,
        )

    def choose_dungeon(
        self,
        dungeons: list[dict[str, Any]],
        has_urgent_quests: bool,
    ) -> dict[str, Any] | None:
        eligible = []

        for dungeon in dungeons:
            if not dungeon.get("can_enter"):
                continue

            zone_id = as_int(dungeon.get("zone_id"))
            if zone_id <= 0:
                continue

            if not self.dungeon_attempt_allowed(zone_id):
                continue

            is_infinite = bool(dungeon.get("is_infinite"))

            if (
                is_infinite
                and has_urgent_quests
                and self.config["dungeons"][
                    "infinite_only_when_no_urgent_quests"
                ]
            ):
                continue

            preview = self.client.get(
                f"dungeons/preview/{zone_id}"
            )
            if not preview.ok:
                continue

            gold_max = int(
                engine.deep_find_number(
                    preview.data,
                    {"gold_max", "reward_gold_max"},
                )
                or 0
            )
            stamina_loot = (
                "potion_stam" in text_blob(preview.data)
            )

            if (
                gold_max <= 0
                and not stamina_loot
                and not self.config["dungeons"][
                    "allow_progression_only_runs"
                ]
            ):
                continue

            eligible.append(
                (
                    0 if gold_max > 0 else 1,
                    -gold_max,
                    zone_id,
                    dungeon,
                )
            )

        if not eligible:
            return None

        eligible.sort(key=lambda row: row[:3])
        return eligible[0][3]

    def dungeon_resource_targets(
        self,
    ) -> tuple[int, int, int]:
        character = self.get_character()

        hp_max = as_int(character.get("hp_max"), 1)
        stamina_max = as_int(
            character.get("stamina_max"),
            1,
        )
        mp_max = as_int(character.get("mp_max"), 1)

        return (
            math.ceil(
                hp_max
                * float(
                    self.config["dungeons"][
                        "required_hp_percent"
                    ]
                )
                / 100
            ),
            math.ceil(
                stamina_max
                * float(
                    self.config["dungeons"][
                        "required_stamina_percent"
                    ]
                )
                / 100
            ),
            math.ceil(
                mp_max
                * float(
                    self.config["dungeons"][
                        "required_mp_percent"
                    ]
                )
                / 100
            ),
        )

    def continue_dungeon(
        self,
        run_id: int,
    ) -> None:
        action_limit = int(
            self.config["dungeons"][
                "max_actions_per_cycle"
            ]
        )

        for _ in range(action_limit):
            state = self.client.get(
                f"dungeons/run/{run_id}"
            )

            if not state.ok:
                return

            blob = text_blob(state.data)
            status = str(
                engine.recursive_find(
                    state.data,
                    {"status", "phase", "state"},
                )
                or ""
            ).lower()

            if any(
                word in status
                for word in (
                    "completed",
                    "finished",
                    "victory",
                    "boss_defeated",
                    "awaiting_finalize",
                )
            ) or "finalize" in blob:
                result = self.client.post(
                    f"dungeons/run/{run_id}/finalize-boss"
                )

                if result.ok:
                    self.dungeon_actions += 1
                    self.logger.info(
                        "[DUNGEON] Run finalized."
                    )
                return

            boss_decision = bool(
                engine.recursive_find(
                    state.data,
                    {
                        "awaiting_boss_decision",
                        "boss_decision_required",
                    },
                )
            ) or (
                "decide_boss" in status
                or "boss_decision" in status
            )

            if boss_decision:
                character = self.get_character()
                hp_ratio = (
                    as_int(character.get("hp"))
                    / max(1, as_int(character.get("hp_max"), 1))
                )
                mp_ratio = (
                    as_int(character.get("mp"))
                    / max(1, as_int(character.get("mp_max"), 1))
                )

                if (
                    hp_ratio
                    < float(
                        self.config["dungeons"][
                            "boss_minimum_hp_ratio"
                        ]
                    )
                    or mp_ratio
                    < float(
                        self.config["dungeons"][
                            "boss_minimum_mp_ratio"
                        ]
                    )
                ):
                    self.logger.info(
                        "[DUNGEON] Boss resources are not ready; run preserved."
                    )
                    return

                result = self.client.post(
                    f"dungeons/run/{run_id}/decide-boss",
                    {"choice": "fight"},
                )

                if not result.ok:
                    return

                self.dungeon_actions += 1
                self.logger.info(
                    "[DUNGEON] Boss fight accepted."
                )
                time.sleep(
                    float(
                        self.config["automation"][
                            "action_delay_seconds"
                        ]
                    )
                )
                continue

            floor = as_int(
                engine.recursive_find(
                    state.data,
                    {
                        "current_floor",
                        "floor",
                        "floor_number",
                    },
                ),
                0,
            )

            result = self.client.post(
                f"dungeons/run/{run_id}/next-floor",
                {"expected_floor": floor},
            )

            self.record(
                "dungeon_next_floor",
                result.ok,
                {
                    "run_id": run_id,
                    "expected_floor": floor,
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if not result.ok:
                return

            self.dungeon_actions += 1
            next_floor = as_int(
                engine.recursive_find(
                    result.data,
                    {
                        "current_floor",
                        "floor",
                        "floor_number",
                    },
                ),
                floor + 1,
            )
            self.logger.info(
                "[DUNGEON] Floor %s completed.",
                next_floor,
            )

            time.sleep(
                float(
                    self.config["automation"][
                        "action_delay_seconds"
                    ]
                )
            )

    def run_dungeon_autopilot(
        self,
        has_urgent_quests: bool,
    ) -> bool:
        if not self.config["dungeons"]["enabled"]:
            return False

        listing = self.client.get("dungeons/list")
        if not listing.ok:
            return False

        active_run = first_dict(
            listing.data,
            ("active_run", "run"),
        )

        if active_run:
            run_id = self.extract_run_id(
                {"active_run": active_run}
            )
            if run_id:
                self.continue_dungeon(run_id)
                return True

        dungeons = first_list(
            listing.data,
            ("dungeons", "items", "rows", "data"),
        )
        chosen = self.choose_dungeon(
            dungeons,
            has_urgent_quests=has_urgent_quests,
        )

        if chosen is None:
            return False

        hp_target, stamina_target, mp_target = (
            self.dungeon_resource_targets()
        )

        self.wait_for_dynamic_targets(
            hp_target=hp_target,
            stamina_target=stamina_target,
            mp_target=mp_target,
            priority_label=(
                chosen.get("name_en")
                or chosen.get("name")
                or "Dungeon"
            ),
            allow_stamina_potion=True,
        )

        zone_id = as_int(chosen.get("zone_id"))
        skill_ids = self.dungeon_skill_ids()

        result = self.client.post(
            f"dungeons/enter/{zone_id}",
            {"skill_ids": skill_ids},
        )

        self.record(
            "dungeon_enter",
            result.ok,
            {
                "zone_id": zone_id,
                "skill_ids": skill_ids,
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        if not result.ok:
            return False

        self.mark_dungeon_attempt(zone_id)
        self.dungeon_actions += 1
        self.logger.info(
            "[DUNGEON] Entered: %s",
            chosen.get("name_en")
            or chosen.get("name")
            or zone_id,
        )

        run_id = self.extract_run_id(result.data)

        if run_id:
            self.continue_dungeon(run_id)

        return True

    def world_boss_attack_allowed(
        self,
        boss_id: int,
    ) -> bool:
        attacks = self.special_state.setdefault(
            "world_boss_attacks",
            {},
        )
        rows = attacks.setdefault(str(boss_id), [])

        if not isinstance(rows, list):
            rows = []
            attacks[str(boss_id)] = rows

        now = time.time()
        rows[:] = [
            as_float(timestamp)
            for timestamp in rows
            if now - as_float(timestamp) < 3600
        ]

        return len(rows) < int(
            self.config["world_boss"][
                "maximum_attacks_per_hour"
            ]
        )

    def mark_world_boss_attack(
        self,
        boss_id: int,
    ) -> None:
        attacks = self.special_state.setdefault(
            "world_boss_attacks",
            {},
        )
        rows = attacks.setdefault(str(boss_id), [])
        rows.append(time.time())
        engine.save_json(
            self.special_state_file,
            self.special_state,
        )

    def active_world_boss(
        self,
        objectives,
    ) -> dict[str, Any] | None:
        if not self.config["world_boss"]["enabled"]:
            return None

        result = self.client.get("world-boss/active")
        if not result.ok:
            return None

        bosses = first_list(
            result.data,
            ("bosses", "active", "items", "rows", "data"),
        )

        if not bosses and isinstance(result.data, dict):
            possible = first_dict(
                result.data,
                ("boss", "world_boss"),
            )
            if possible:
                bosses = [possible]

        quest_blob = " ".join(
            f"{row.quest_code} {row.target} {row.quest_name}"
            for row in objectives
        ).lower()

        for boss in bosses:
            boss_id = as_int(
                boss.get("id")
                or boss.get("boss_id")
            )
            if boss_id <= 0:
                continue
            if boss.get("can_attack") is False:
                continue
            if not self.world_boss_attack_allowed(boss_id):
                continue

            stamina_cost = int(
                engine.deep_find_number(
                    boss,
                    {
                        "stamina_cost",
                        "attack_stamina_cost",
                    },
                )
                or 0
            )
            gold_reward = int(
                engine.deep_find_number(
                    boss,
                    {
                        "gold_reward",
                        "gold_max",
                        "reward_gold",
                    },
                )
                or 0
            )

            boss_code = str(
                boss.get("code")
                or boss.get("name_en")
                or boss.get("name")
                or ""
            ).lower()
            quest_relevant = (
                boss_code
                and boss_code in quest_blob
            ) or "world_boss" in quest_blob

            if stamina_cost <= 0:
                continue

            if (
                gold_reward <= 0
                and not quest_relevant
                and not self.config["world_boss"][
                    "allow_progression_only_attacks"
                ]
            ):
                continue

            return boss

        return None

    def run_world_boss(
        self,
        boss: dict[str, Any],
    ) -> bool:
        boss_id = as_int(
            boss.get("id")
            or boss.get("boss_id")
        )
        stamina_cost = int(
            engine.deep_find_number(
                boss,
                {
                    "stamina_cost",
                    "attack_stamina_cost",
                },
            )
            or 0
        )

        character = self.get_character()
        hp_max = as_int(character.get("hp_max"), 1)
        stamina_max = as_int(
            character.get("stamina_max"),
            1,
        )
        mp_max = as_int(character.get("mp_max"), 1)

        hp_target = math.ceil(
            hp_max
            * float(
                self.config["world_boss"][
                    "required_hp_percent"
                ]
            )
            / 100
        )
        stamina_target = min(
            stamina_max,
            max(
                stamina_cost
                + int(
                    self.config["dynamic_resources"][
                        "emergency_stamina_reserve"
                    ]
                ),
                math.ceil(
                    stamina_max
                    * float(
                        self.config["world_boss"][
                            "required_stamina_percent"
                        ]
                    )
                    / 100
                ),
            ),
        )
        mp_target = math.ceil(
            mp_max
            * float(
                self.config["world_boss"][
                    "required_mp_percent"
                ]
            )
            / 100
        )

        label = (
            boss.get("name_en")
            or boss.get("name")
            or "World Boss"
        )

        self.wait_for_dynamic_targets(
            hp_target=hp_target,
            stamina_target=stamina_target,
            mp_target=mp_target,
            priority_label=label,
            allow_stamina_potion=True,
        )

        result = self.client.post(
            f"world-boss/{boss_id}/attack"
        )

        self.record(
            "world_boss_attack",
            result.ok,
            {
                "boss_id": boss_id,
                "boss": label,
                "stamina_cost": stamina_cost,
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        if result.ok:
            self.world_boss_attacks += 1
            self.mark_world_boss_attack(boss_id)
            gold = int(
                engine.deep_find_number(
                    result.data,
                    {"gold_gained", "gold_reward"},
                )
                or 0
            )
            self.total_gold_gained += gold
            self.logger.info(
                "[BOSS] Attacked: %s%s",
                label,
                f" | +{gold} Gold" if gold else "",
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Dynamic farming and main planner
    # ------------------------------------------------------------------

    def run_farming_batch(
        self,
        material_needs,
    ) -> None:
        maximum_battles = int(
            self.config["continuous"][
                "max_battles_per_batch"
            ]
        )
        reserve = int(
            self.config["dynamic_resources"][
                "emergency_stamina_reserve"
            ]
        )
        completed = 0

        while completed < maximum_battles:
            character = self.get_character()

            if str(character.get("status", "")).lower() != "alive":
                self.logger.info(
                    "[STOP] Character is not alive."
                )
                return

            objectives = self.objective_rows()
            candidates = self.build_farm_candidates(
                character,
                objectives,
                material_needs,
            )

            if not candidates:
                return

            useful = candidates[0]
            hp = as_int(character.get("hp"))
            stamina = as_int(character.get("stamina"))
            mp = as_int(character.get("mp"))

            stamina_target = self.dynamic_stamina_target(
                useful
            )
            mp_target = self.dynamic_mp_target(useful)
            hp_target = useful.required_hp

            fight_cost = max(
                1,
                as_int(
                    useful.monster.get("stamina_cost"),
                    1,
                ),
            )

            high_priority = useful.priority <= 1

            if hp < hp_target:
                if self.use_hp_potions_until_safe(
                    hp_target,
                    high_priority=high_priority,
                ):
                    continue
                return

            if stamina < fight_cost + reserve:
                if self.use_stamina_potion_if_worthwhile(
                    character,
                    has_priority_tasks=useful.priority <= 3,
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

            # When an important task is selected, build enough resources for a
            # useful batch rather than waking for a single hit.
            if (
                useful.priority <= 3
                and (
                    stamina < stamina_target
                    or mp < mp_target
                )
            ):
                return

            travelled = self.travel_to(
                character,
                useful.zone_id,
            )

            if travelled is None:
                return

            if not self.execute_fight(useful):
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
                useful.material_score > 0
                and self.total_battles % interval == 0
            ):
                material_needs.update(
                    self.complete_craft_quests()
                )

    def regular_cycle(self) -> None:
        self.claim_free_rewards()
        self.claim_achievements()
        self.start_all_free_quests()

        self.optimize_skills()
        self.optimize_skill_tree()
        self.optimize_progression()

        material_needs = self.complete_craft_quests()
        self.run_farming_batch(material_needs)

        self.claim_free_rewards()
        self.claim_achievements()
        self.complete_craft_quests()
        self.optimize_progression()

    def next_regular_targets(
        self,
    ) -> tuple[int, int, int, str, bool]:
        character = self.get_character()
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
                as_int(character.get("stamina")),
                0,
                "No farm target",
                False,
            )

        candidate = candidates[0]

        return (
            candidate.required_hp,
            self.dynamic_stamina_target(candidate),
            self.dynamic_mp_target(candidate),
            candidate.reason,
            candidate.priority <= 3,
        )

    def advanced_report(self) -> dict[str, Any]:
        base_report = self.report()
        base_report.update(
            {
                "version": self.VERSION,
                "achievements_claimed": self.achievements_claimed,
                "skills_learned": self.skills_learned,
                "skill_loadout_updates": self.skill_loadout_updates,
                "skill_tree_allocations": self.skill_tree_allocations,
                "dungeon_actions": self.dungeon_actions,
                "world_boss_attacks": self.world_boss_attacks,
            }
        )

        engine.save_json(
            OUTPUT_DIR / "eldoria_bot_v1_5_last_report.json",
            base_report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v1_5_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".json"
            ),
            base_report,
        )

        return base_report

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
            "[MODE] Quests -> progression -> Gold farm -> Dungeon/Boss when ready."
        )
        self.log_status("START", self.initial_character)

        try:
            while True:
                objectives = self.objective_rows()
                has_urgent_quests = any(
                    row.objective_type in {
                        "kill",
                        "craft",
                        "loot",
                    }
                    for row in objectives
                )

                # Active or profitable World Boss takes priority only when its
                # explicit cost and relevance are known.
                boss = self.active_world_boss(objectives)
                if boss is not None:
                    self.run_world_boss(boss)
                    continue

                # Dungeons preserve resources dynamically. Infinite Dungeon is
                # delayed while urgent quests remain.
                if self.run_dungeon_autopilot(
                    has_urgent_quests=has_urgent_quests,
                ):
                    continue

                self.regular_cycle()

                if not self.config["continuous"]["enabled"]:
                    break

                (
                    hp_target,
                    stamina_target,
                    mp_target,
                    label,
                    priority,
                ) = self.next_regular_targets()

                self.wait_for_dynamic_targets(
                    hp_target=hp_target,
                    stamina_target=stamina_target,
                    mp_target=mp_target,
                    priority_label=label,
                    allow_stamina_potion=priority,
                )

        finally:
            self.advanced_report()


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
    logger = configure_quiet_logging()

    try:
        client = engine.APIClient(config, logger)
        bot = AdvancedEldoriaBot(
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
