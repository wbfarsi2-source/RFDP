from __future__ import annotations

import ast
import importlib.util
import json
import logging
import math
import os
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
V34_FILE = SCRIPT_DIR / "eldoria_bot_v3_3_final_windows.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_5_leveling_first_config.json"

if not V34_FILE.exists():
    raise RuntimeError(f"Required V3.4 wrapper is missing: {V34_FILE}")

spec = importlib.util.spec_from_file_location("eldoria_v34_root_hardened", V34_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("The V3.4 root-hardened wrapper could not be loaded.")
v34 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v34
spec.loader.exec_module(v34)

# Reuse V3.4's hardened paths, logging, atomic state and endpoint guard.
ELDORIA_ROOT = v34.ELDORIA_ROOT
PRIVATE_DIR = v34.PRIVATE_DIR
OUTPUT_DIR = v34.OUTPUT_DIR
PROJECT_DIR = v34.PROJECT_DIR
STATE_DIR = v34.STATE_DIR
LOG_DIR = v34.LOG_DIR
CURRENT_PLAN_FILE = v34.CURRENT_PLAN_FILE
INSTANCE_LOCK_FILE = v34.INSTANCE_LOCK_FILE

engine = v34.engine
base = v34.base
v25 = v34.v25
v27 = v34.v27

for module in v34.ALL_MODULES:
    module.CONFIG_FILE = CONFIG_FILE
v34.CONFIG_FILE = CONFIG_FILE


def as_int(value: Any, default: int = 0) -> int:
    return v34.as_int(value, default)


def as_float(value: Any, default: float = 0.0) -> float:
    return v34.as_float(value, default)


def normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def first_list(data: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def safe_formula_value(expression: Any, variables: dict[str, float]) -> float:
    """Evaluate only numeric arithmetic used by server skill formulas."""
    if not isinstance(expression, str) or not expression.strip():
        return 0.0
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return 0.0

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            return float(variables.get(node.id.lower(), 0.0))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div) and right != 0:
                return left / right
        raise ValueError("unsupported formula")

    try:
        result = visit(tree)
        return result if math.isfinite(result) else 0.0
    except Exception:
        return 0.0


def prepare_config(config: dict[str, Any]) -> dict[str, Any]:
    config = v34.prepare_config(config)
    v34.deep_defaults(
        config,
        {
            "leveling_first": {
                "enabled": True,
                "xp_weight": 1.0,
                "gold_to_xp": 0.12,
                "quest_overlap_value": 180.0,
                "material_value": 45.0,
                "main_quest_value_multiplier": 1.65,
                "daily_value_multiplier": 1.45,
                "weekly_value_multiplier": 0.72,
                "side_value_multiplier": 1.0,
                "broad_weekly_grind_penalty": 0.42,
                "ready_now_bonus": 1.12,
                "boss_farm_requires_history": True,
                "dungeon_preempts_campaign": True,
                "dungeon_only_when_ready": True,
                "race_equipment_enabled": True,
                "race_equipment_failure_cooldown_seconds": 21600,
                "state_heartbeat_seconds": 900,
                "skill_tree_plan": [
                    {"code": "a_xp1", "target": 5},
                    {"code": "a_xp2", "target": 5},
                    {"code": "a_xp3", "target": 3},
                    {"code": "a_stam1", "target": 3},
                    {"code": "a_stam2", "target": 2}
                ],
                "pve_skill_order": [4, 28, 13, 1, 2],
                "dungeon_skill_order": [22, 28, 60, 3, 13, 1],
                "max_pve_skills": 3,
                "max_tree_allocations_per_cycle": 30
            }
        },
    )
    return config


class LevelingFirstDirector(v34.ProgressFirstSafetyDirector):
    VERSION = "3.5.1-leveling-first-runtime-verified-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)
        self.leveling_file = STATE_DIR / "leveling_first_state.json"
        self.leveling_state = engine.load_json(
            self.leveling_file,
            {
                "schema_version": 1,
                "tree_allocations": 0,
                "loadout_updates": 0,
                "race_equipment_attempts": 0,
                "race_equipment_retry_at": 0.0,
                "last_leveling_signature": "",
                "last_leveling_log_at": 0.0,
                "normalized_zone_objectives": 0,
                "dungeon_campaign_bypasses": 0,
            },
        )
        if not isinstance(self.leveling_state, dict):
            self.leveling_state = {}
        self.leveling_state.setdefault("schema_version", 1)
        self.save_leveling_state()

    def save_leveling_state(self) -> None:
        engine.save_json(self.leveling_file, self.leveling_state)

    # ------------------------------------------------------------------
    # Actual server schema: kill_in_zone objectives are ordinary kill
    # objectives constrained by zone code. Older versions ignored them.
    # ------------------------------------------------------------------
    def objective_rows(self):
        rows = super().objective_rows()
        normalized_count = 0
        for objective in rows:
            if normalize(getattr(objective, "objective_type", "")) == "kill_in_zone":
                zone_code = str(getattr(objective, "target", "") or "").strip()
                objective.objective_type = "kill"
                objective.zone_code = zone_code
                objective.target = "any"
                normalized_count += 1
        if normalized_count and as_int(
            self.leveling_state.get("normalized_zone_objectives"), -1
        ) != normalized_count:
            self.leveling_state["normalized_zone_objectives"] = normalized_count
            self.save_leveling_state()
        return rows

    # ------------------------------------------------------------------
    # Skill tree: parse the real {points_available, allocations} schema and
    # spend points on XP gain first, then max stamina. No allocate-path call
    # is used, so only the explicit configured nodes can consume points.
    # ------------------------------------------------------------------
    def optimize_skill_tree(self) -> None:
        if not self.config.get("skill_tree", {}).get("enabled", True):
            return
        catalog_result = self.client.get("skill-tree/catalog")
        mine_result = self.client.get("skill-tree/mine")
        if not catalog_result.ok or not mine_result.ok:
            return

        catalog = first_list(catalog_result.data, ("nodes", "items", "rows", "data"))
        mine = mine_result.data if isinstance(mine_result.data, dict) else {}
        allocations = mine.get("allocations", {})
        if not isinstance(allocations, dict):
            allocations = {}
        points = as_int(mine.get("points_available"), 0)
        if points <= 0:
            character = self.get_character()
            points = as_int(character.get("skill_tree_points"), 0)
        if points <= 0:
            return

        by_code = {str(row.get("code") or ""): row for row in catalog if row.get("code")}
        plan = self.config.get("leveling_first", {}).get("skill_tree_plan", [])
        max_actions = max(
            1,
            as_int(
                self.config.get("leveling_first", {}).get(
                    "max_tree_allocations_per_cycle", 30
                ),
                30,
            ),
        )
        actions = 0

        for step in plan:
            if actions >= max_actions or points <= 0:
                break
            if not isinstance(step, dict):
                continue
            code = str(step.get("code") or "")
            target = max(0, as_int(step.get("target"), 0))
            node = by_code.get(code)
            if not node or target <= 0:
                continue
            target = min(target, max(1, as_int(node.get("max_level"), target)))

            while as_int(allocations.get(code), 0) < target and points > 0 and actions < max_actions:
                prereq = node.get("prereq")
                if isinstance(prereq, dict):
                    prereq_code = str(prereq.get("code") or "")
                    prereq_level = as_int(prereq.get("level"), 0)
                    if as_int(allocations.get(prereq_code), 0) < prereq_level:
                        self.logger.info(
                            "[TREE] %s waits for prerequisite %s level %s.",
                            code,
                            prereq_code,
                            prereq_level,
                        )
                        break

                previous_level = as_int(allocations.get(code), 0)
                result = self.client.post(f"skill-tree/allocate/{code}")
                verified = False
                verified_payload = None
                if result.ok:
                    time.sleep(float(self.config["automation"]["action_delay_seconds"]))
                    verification = self.client.get("skill-tree/mine")
                    if verification.ok and isinstance(verification.data, dict):
                        verified_payload = verification.data
                        server_allocations = verification.data.get("allocations", {})
                        if isinstance(server_allocations, dict):
                            server_level = as_int(server_allocations.get(code), 0)
                            if server_level >= previous_level + 1:
                                verified = True
                                allocations = dict(server_allocations)
                                points = as_int(
                                    verification.data.get("points_available"),
                                    max(0, points - 1),
                                )

                self.record(
                    "leveling_first_tree_allocate",
                    bool(result.ok and verified),
                    {
                        "code": code,
                        "target": target,
                        "status": result.status,
                        "error": result.error,
                        "post_response": result.data,
                        "verified": verified,
                        "verification": verified_payload,
                    },
                )
                if not result.ok or not verified:
                    self.logger.info(
                        "[TREE] Allocation stopped at %s | status %s | verified=%s | %s.",
                        code,
                        result.status,
                        verified,
                        result.error or "allocation was not confirmed by the server",
                    )
                    break

                actions += 1
                self.skill_tree_allocations += 1
                self.leveling_state["tree_allocations"] = (
                    as_int(self.leveling_state.get("tree_allocations"), 0) + 1
                )
                effect = node.get("effect") if isinstance(node.get("effect"), dict) else {}
                self.logger.info(
                    "[TREE XP-FIRST] %s -> level %s | %s +%s.",
                    node.get("name_en") or node.get("name") or code,
                    allocations[code],
                    effect.get("type") or "effect",
                    effect.get("amount") or 0,
                )
                self.save_leveling_state()

        if actions:
            self.logger.info(
                "[TREE XP-FIRST] %s point(s) allocated; %s point(s) remain.",
                actions,
                points,
            )

    # ------------------------------------------------------------------
    # Skills: use real damage_formula values and force a physical Drakkar
    # PvE order. Healing/First Aid remain reserved for turn-based dungeons.
    # ------------------------------------------------------------------
    def skill_formula_damage(self, skill: dict[str, Any], character: dict[str, Any]) -> float:
        derived = character.get("derived") if isinstance(character.get("derived"), dict) else {}
        variables = {
            "atk": as_float(derived.get("attack"), as_float(character.get("attack"), 0)),
            "attack": as_float(derived.get("attack"), as_float(character.get("attack"), 0)),
            "str": as_float(derived.get("str"), as_float(character.get("strength"), 0)),
            "strength": as_float(derived.get("str"), as_float(character.get("strength"), 0)),
            "agi": as_float(derived.get("agi"), as_float(character.get("agility"), 0)),
            "agility": as_float(derived.get("agi"), as_float(character.get("agility"), 0)),
            "int": as_float(derived.get("int"), as_float(character.get("intelligence"), 0)),
            "intelligence": as_float(derived.get("int"), as_float(character.get("intelligence"), 0)),
        }
        return safe_formula_value(skill.get("damage_formula"), variables)

    def best_learned_skill(self) -> dict[str, Any] | None:
        result = self.client.get("skills/mine")
        if not result.ok:
            return super().best_learned_skill()
        rows = self.skill_rows(result.data)
        character = self.get_character()
        current_mp = as_float(character.get("mp"), 0)
        scored = []
        for skill in rows:
            if normalize(skill.get("type")) != "active":
                continue
            cost = max(0.0, as_float(self.skill_mp_cost(skill), 0.0))
            if cost > current_mp:
                continue
            damage = self.skill_formula_damage(skill, character)
            if damage <= 0:
                continue
            efficiency = damage / max(cost, 5.0)
            scored.append((damage * 0.72 + efficiency * 28.0, damage, -cost, skill))
        if not scored:
            return super().best_learned_skill()
        scored.sort(key=lambda row: row[:3], reverse=True)
        return scored[0][3]


    def learned_active_skills(self) -> list[dict[str, Any]]:
        """Return the actual live-combat skill order used by the turn engine."""
        result = self.client.get("skills/mine")
        if not result.ok:
            return super().learned_active_skills()

        character = self.get_character()
        learned = [
            row for row in self.skill_rows(result.data)
            if normalize(row.get("type")) == "active"
            and self.skill_id(row) is not None
        ]
        if not learned:
            return super().learned_active_skills()

        configured = [
            as_int(value) for value in self.config.get("leveling_first", {}).get(
                "pve_skill_order", [28, 13, 1, 2]
            )
            if as_int(value) > 0
        ]
        order_index = {skill_id: index for index, skill_id in enumerate(configured)}

        def score(skill: dict[str, Any]):
            skill_id = as_int(self.skill_id(skill), 0)
            formula_damage = self.skill_formula_damage(skill, character)
            mp_cost = max(0.0, as_float(self.skill_mp_cost(skill), 0.0))
            configured_rank = order_index.get(skill_id, len(configured) + 100)
            # Configured order is authoritative for the first combat rotation;
            # formula damage and MP efficiency resolve any unlisted skills.
            return (
                configured_rank,
                -formula_damage,
                -(formula_damage / max(mp_cost, 5.0)),
                mp_cost,
                skill_id,
            )

        learned.sort(key=score)
        max_pick = max(
            1,
            as_int(
                self.config.get("leveling_first", {}).get("max_pve_skills", 3),
                3,
            ),
        )
        return learned[:max_pick]

    def enforce_pve_loadout(self) -> None:
        mine_result = self.client.get("skills/mine")
        current_result = self.client.get("skills/loadout")
        if not mine_result.ok:
            return
        learned = self.skill_rows(mine_result.data)
        learned_ids = {
            skill_id for row in learned
            if (skill_id := self.skill_id(row)) is not None
        }
        configured = self.config.get("leveling_first", {}).get(
            "pve_skill_order", [4, 28, 13, 1, 2]
        )
        max_pick = max(1, as_int(self.config.get("leveling_first", {}).get("max_pve_skills", 3), 3))
        order = [as_int(skill_id) for skill_id in configured if as_int(skill_id) in learned_ids][:max_pick]
        if not order:
            return

        current_order: list[int] = []
        if current_result.ok and isinstance(current_result.data, dict):
            loadout = current_result.data.get("loadout", current_result.data)
            if isinstance(loadout, dict) and isinstance(loadout.get("pve"), list):
                current_order = [as_int(value) for value in loadout["pve"] if as_int(value) > 0][:max_pick]
        if current_order == order:
            return

        result = self.client.post("skills/loadout", {"mode": "pve", "order": order})
        self.record(
            "leveling_first_pve_loadout",
            result.ok,
            {"order": order, "status": result.status, "error": result.error, "response": result.data},
        )
        if result.ok:
            self.skill_loadout_updates += 1
            self.leveling_state["loadout_updates"] = (
                as_int(self.leveling_state.get("loadout_updates"), 0) + 1
            )
            self.save_leveling_state()
            self.logger.info("[SKILL XP-FIRST] PvE loadout: %s.", ", ".join(map(str, order)))

    def optimize_skills(self) -> None:
        # Retain free skill learning but prevent the older keyword scorer from
        # writing a competing loadout before the formula-aware V3.5 order.
        section = self.config.get("skills_advanced", {})
        original_modes = list(section.get("loadout_modes", []))
        section["loadout_modes"] = []
        try:
            super().optimize_skills()
        finally:
            section["loadout_modes"] = original_modes
        self.enforce_pve_loadout()

    def dungeon_skill_ids(self) -> list[int]:
        result = self.client.get("dungeons/loadout-options")
        if not result.ok:
            return super().dungeon_skill_ids()
        rows = first_list(result.data, ("skills", "items", "rows", "data"))
        available = {
            as_int(row.get("id")): row for row in rows if as_int(row.get("id")) > 0
        }
        max_pick = max(1, as_int(engine.recursive_find(result.data, {"max_pick", "max_skills", "slots"}), 3))
        configured = self.config.get("leveling_first", {}).get(
            "dungeon_skill_order", [22, 28, 60, 3, 13, 1]
        )
        chosen = [as_int(skill_id) for skill_id in configured if as_int(skill_id) in available][:max_pick]
        if chosen:
            self.logger.info("[DUNGEON LOADOUT] %s.", ", ".join(map(str, chosen)))
            return chosen
        return super().dungeon_skill_ids()

    # ------------------------------------------------------------------
    # Race equipment is returned separately by the server. Merge it into
    # the normal inventory candidate pool so the standard score/equip code
    # can use already-owned race gear without buying anything.
    # ------------------------------------------------------------------
    def get_inventory_payload(self) -> dict[str, Any]:
        # Normal equipment optimization receives the normal inventory. Race
        # equipment is evaluated separately so a rejected equip request gets
        # a cooldown instead of being retried every scheduler cycle.
        return super().get_inventory_payload()

    def try_equip_best_race_item(self) -> None:
        cfg = self.config.get("leveling_first", {})
        if not cfg.get("race_equipment_enabled", True):
            return
        now = time.time()
        if now < as_float(self.leveling_state.get("race_equipment_retry_at"), 0.0):
            return

        payload = super().get_inventory_payload()
        inventory = payload.get("inventory")
        equipment = payload.get("equipment")
        race_equipment = payload.get("race_equipment")
        if not isinstance(inventory, list) or not isinstance(equipment, list) or not isinstance(race_equipment, list):
            return
        by_id = {as_int(item.get("id")): item for item in inventory if isinstance(item, dict)}
        current_by_slot = {}
        for row in equipment:
            if not isinstance(row, dict):
                continue
            current_by_slot[normalize(row.get("slot"))] = by_id.get(as_int(row.get("inventory_id")))

        candidates = []
        for raw in race_equipment:
            if not isinstance(raw, dict):
                continue
            candidate = dict(raw)
            candidate["id"] = as_int(candidate.get("owned_id"), as_int(candidate.get("id")))
            slot = normalize(candidate.get("slot"))
            if not slot or candidate["id"] <= 0:
                continue
            candidate["type"] = "ring" if slot.startswith("ring") else slot
            current = current_by_slot.get(slot)
            gain = self.item_score(candidate) - self.item_score(current)
            candidates.append((gain, slot, candidate, current))
        if not candidates:
            return
        candidates.sort(key=lambda row: row[0], reverse=True)
        gain, slot, best, current = candidates[0]
        minimum_gain = as_float(self.config.get("equipment", {}).get("minimum_score_gain"), 0.25)
        if gain < minimum_gain:
            return

        body = {"slot": slot} if slot.startswith("ring") else None
        result = self.client.post(f"inventory/equip/{best['id']}", body)
        self.leveling_state["race_equipment_attempts"] = (
            as_int(self.leveling_state.get("race_equipment_attempts"), 0) + 1
        )
        self.record(
            "leveling_first_race_equip",
            result.ok,
            {
                "slot": slot,
                "item": best.get("name_en") or best.get("name") or best.get("code"),
                "old_score": round(self.item_score(current), 2),
                "new_score": round(self.item_score(best), 2),
                "status": result.status,
                "error": result.error,
            },
        )
        if result.ok:
            self.leveling_state["race_equipment_retry_at"] = 0.0
            self.equipment_changes += 1
            self.logger.info(
                "[EQUIP XP-FIRST] %s: %s | score %.1f -> %.1f.",
                slot,
                best.get("name_en") or best.get("name") or best.get("code"),
                self.item_score(current),
                self.item_score(best),
            )
        else:
            self.leveling_state["race_equipment_retry_at"] = now + as_float(
                cfg.get("race_equipment_failure_cooldown_seconds"), 21600.0
            )
            self.logger.info(
                "[EQUIP XP-FIRST] Race equipment attempt deferred | status %s | %s.",
                result.status,
                result.error or "server rejected request",
            )
        self.save_leveling_state()

    def auto_equip_best(self) -> None:
        super().auto_equip_best()
        self.try_equip_best_race_item()

    # ------------------------------------------------------------------
    # Value rate instead of raw completion time. Quest reward, monster XP,
    # Gold, overlap and materials are all divided by real recovery time.
    # ------------------------------------------------------------------
    def candidate_base_rewards(self, candidate) -> tuple[float, float]:
        monster = candidate.monster
        xp = as_float(monster.get("xp_reward"), 0.0)
        gold = (as_float(monster.get("gold_min"), 0.0) + as_float(monster.get("gold_max"), 0.0)) / 2.0
        return xp, gold

    def quest_value_multiplier(self, objective) -> float:
        quest_type = normalize(getattr(objective, "quest_type", "side"))
        cfg = self.config.get("leveling_first", {})
        return {
            "main": as_float(cfg.get("main_quest_value_multiplier"), 1.65),
            "daily": as_float(cfg.get("daily_value_multiplier"), 1.45),
            "weekly": as_float(cfg.get("weekly_value_multiplier"), 0.72),
            "side": as_float(cfg.get("side_value_multiplier"), 1.0),
        }.get(quest_type, 1.0)

    def priority_score(self, record: dict[str, Any]) -> float:
        objective = record["objective"]
        expected = as_float(record.get("expected"), float("inf"))
        if not math.isfinite(expected) or expected <= 0:
            record["root_priority_score"] = float("inf")
            return float("inf")

        cfg = self.config.get("leveling_first", {})
        xp_weight = as_float(cfg.get("xp_weight"), 1.0)
        gold_to_xp = as_float(cfg.get("gold_to_xp"), 0.12)
        reward_value = (
            as_float(getattr(objective, "reward_xp", 0), 0.0) * xp_weight
            + as_float(getattr(objective, "reward_gold", 0), 0.0) * gold_to_xp
        )

        row = record.get("best_row")
        fight_value = 0.0
        overlap = 0
        if isinstance(row, dict) and row.get("candidate") is not None:
            candidate = row["candidate"]
            xp, gold = self.candidate_base_rewards(candidate)
            rate = max(0.01, as_float(record.get("rate"), 1.0))
            expected_fights = max(1.0, as_float(getattr(objective, "remaining", 1), 1.0) / rate)
            fight_value = expected_fights * (xp * xp_weight + gold * gold_to_xp)
            overlap = max(0, as_int(getattr(candidate, "quest_overlap", 0), 0) - 1)
            fight_value += overlap * as_float(cfg.get("quest_overlap_value"), 180.0)
            fight_value += as_float(candidate.material_score, 0.0) * as_float(cfg.get("material_value"), 45.0)

        total_value = max(1.0, (reward_value + fight_value) * self.quest_value_multiplier(objective))
        if (
            normalize(getattr(objective, "quest_type", "")) == "weekly"
            and normalize(getattr(objective, "objective_type", "")) == "kill"
            and normalize(getattr(objective, "target", "")) in {"", "any", "*"}
            and as_int(getattr(objective, "remaining", 0), 0) >= 50
        ):
            total_value *= as_float(cfg.get("broad_weekly_grind_penalty"), 0.42)

        deadline = self.objective_deadline_remaining(objective)
        if deadline is not None and 0 < deadline <= 24 * 3600:
            total_value *= 1.8
        if (
            normalize(getattr(objective, "objective_type", "")) != "craft"
            and not self.record_is_viable(record)
        ):
            total_value *= 0.20

        # Lower is better: seconds required per unit of combined progression value.
        score = expected / total_value
        record["leveling_value"] = total_value
        record["leveling_value_per_hour"] = total_value / expected * 3600.0
        record["deadline_remaining"] = deadline
        record["root_priority_score"] = score
        return score

    def row_leveling_metrics(self, row: dict[str, Any], character: dict[str, Any]) -> dict[str, float]:
        candidate = row["candidate"]
        first_wait, cycle, _ = self.row_recovery_cost(row, character)
        xp, gold = self.candidate_base_rewards(candidate)
        cfg = self.config.get("leveling_first", {})
        value = xp * as_float(cfg.get("xp_weight"), 1.0)
        value += gold * as_float(cfg.get("gold_to_xp"), 0.12)
        value += as_int(getattr(candidate, "quest_overlap", 0), 0) * as_float(cfg.get("quest_overlap_value"), 180.0)
        value += as_float(candidate.material_score, 0.0) * as_float(cfg.get("material_value"), 45.0)
        effective_cycle = max(10.0, cycle + first_wait * 0.20)
        rate = value / effective_cycle * 3600.0
        if row.get("state") == "ready":
            rate *= as_float(cfg.get("ready_now_bonus"), 1.12)
        return {
            "rate": rate,
            "xp_hour": xp / max(10.0, cycle) * 3600.0,
            "gold_hour": gold / max(10.0, cycle) * 3600.0,
            "first_wait": first_wait,
            "cycle": cycle,
        }

    def select_target_row(self, objective, rows):
        if not rows:
            return None
        if not self.broad_kill_objective(objective, rows):
            return super().select_target_row(objective, rows)

        character = self._scheduler_character if isinstance(getattr(self, "_scheduler_character", None), dict) else {}
        cfg = self.config.get("leveling_first", {})
        usable = []
        for row in rows:
            if row.get("state") not in {"ready", "heal", "resource"} or row.get("no_death_blocked"):
                continue
            candidate = row["candidate"]
            monster_id = as_int(candidate.monster.get("id"), 0)
            if (
                cfg.get("boss_farm_requires_history", True)
                and self.is_boss(candidate.monster)
                and not self.combat_sample_rows(monster_id)
            ):
                continue
            usable.append(row)
        if not usable:
            return super().select_target_row(objective, rows)

        ranked = [(self.row_leveling_metrics(row, character), row) for row in usable]
        ranked.sort(
            key=lambda item: (
                -item[0]["rate"],
                item[1].get("risk_ratio", 999.0),
                item[0]["first_wait"],
            )
        )
        metrics, selected = ranked[0]
        self._target_audit_message = (
            f"{len(usable)} safe Kill-any targets ranked by XP+Gold+Quest value; "
            f"{self.monster_name(selected['candidate'])} selected | "
            f"XP/h~{metrics['xp_hour']:.1f} | Gold/h~{metrics['gold_hour']:.1f} | "
            f"value/h~{metrics['rate']:.1f} | cycle {v27.format_duration(metrics['cycle'])}."
        )
        self._target_audit_signature = "|".join(
            [
                self.objective_key(objective),
                str(selected["candidate"].monster.get("id")),
                str(round(metrics["rate"], 2)),
                str(selected.get("state")),
            ]
        )
        self._efficiency_audit_message = self._target_audit_message
        self._efficiency_audit_signature = self._target_audit_signature
        return selected

    def choose_no_quest_progression(self, states, character: dict[str, Any]):
        usable = [
            row for row in states
            if row.get("state") in {"ready", "heal", "resource"}
            and not row.get("no_death_blocked")
            and not self.is_boss(row["candidate"].monster)
        ]
        if not usable:
            return super().choose_no_quest_progression(states, character)
        usable.sort(key=lambda row: self.row_leveling_metrics(row, character)["rate"], reverse=True)
        self.campaign["mode"] = "leveling-first"
        self.save_campaign()
        return usable[0]

    # ------------------------------------------------------------------
    # Dungeon was previously disabled whenever any Quest campaign existed.
    # V3.5 allows a ready Infinite Dungeon run, but never blocks for hours:
    # it returns to normal Quest/leveling work until resources are ready.
    # ------------------------------------------------------------------
    def run_dungeon_autopilot(self, has_urgent_quests: bool) -> bool:
        cfg = self.config.get("leveling_first", {})
        if not cfg.get("dungeon_preempts_campaign", True):
            return super().run_dungeon_autopilot(has_urgent_quests)
        if not self.config.get("dungeons", {}).get("enabled", True):
            return False

        listing = self.client.get("dungeons/list")
        if not listing.ok:
            return False
        active_run = v34.base.first_dict(listing.data, ("active_run", "run"))
        if active_run:
            run_id = self.extract_run_id({"active_run": active_run})
            if run_id:
                self.continue_dungeon(run_id)
                return True

        character = self.get_character()
        hp_target, stamina_target, mp_target = self.dungeon_resource_targets()
        if cfg.get("dungeon_only_when_ready", True):
            if (
                as_int(character.get("hp"), 0) < hp_target
                or as_int(character.get("stamina"), 0) < stamina_target
                or as_int(character.get("mp"), 0) < mp_target
            ):
                return False

        self.leveling_state["dungeon_campaign_bypasses"] = (
            as_int(self.leveling_state.get("dungeon_campaign_bypasses"), 0) + 1
        )
        self.save_leveling_state()
        # Direct call bypasses V2.6's blanket campaign block while retaining
        # all dungeon cooldown, resource and server verification logic.
        return v34.base.AdvancedEldoriaBot.run_dungeon_autopilot(
            self,
            has_urgent_quests=False,
        )

    def write_current_plan(self, *, step: str, row=None, character=None, details: str = "") -> None:
        super().write_current_plan(step=step, row=row, character=character, details=details)
        with CURRENT_PLAN_FILE.open("a", encoding="utf-8") as handle:
            handle.write(
                "\nLEVELING-FIRST V3.5\n"
                "Targets are ranked by real XP, Gold, Quest overlap and recovery time.\n"
                "kill_in_zone Quests, XP skill-tree spending and ready Dungeons are enabled.\n"
                "No-death blocking and paid-action blocking remain active.\n"
            )

    def final_report(self):
        self.save_leveling_state()
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "leveling_first_state": self.leveling_state,
                "leveling_first_features": {
                    "xp_gold_value_rate_targeting": True,
                    "kill_in_zone_normalization": True,
                    "real_skill_tree_schema": True,
                    "xp_first_tree_plan": True,
                    "formula_aware_skills": True,
                    "physical_drakkar_pve_loadout": True,
                    "sustain_dungeon_loadout": True,
                    "dungeon_campaign_bypass": True,
                    "race_equipment_candidate_merge": True,
                    "no_death_guard_retained": True,
                    "paid_actions_remain_blocked": True,
                },
            }
        )
        engine.save_json(OUTPUT_DIR / "eldoria_bot_v3_5_leveling_first_last_report.json", report)
        engine.save_json(
            OUTPUT_DIR / ("eldoria_bot_v3_5_leveling_first_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"),
            report,
        )
        return report



def startup_check() -> int:
    """Build the real startup objects without sending any server request."""
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        print(f"[STARTUP CHECK ERROR] Configuration file is missing: {CONFIG_FILE}")
        return 2

    logger = logging.getLogger("eldoria_v3_5_1_startup_check")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    client = None
    try:
        v34.install_atomic_json_saving()
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
        if not isinstance(config, dict) or not config:
            raise RuntimeError("Configuration did not load as a non-empty JSON object.")

        # This is the exact constructor used by the live bot. It reads the
        # existing cookie/token files but performs no HTTP request.
        client = engine.APIClient(config, logger)
        if not callable(getattr(client, "get", None)):
            raise RuntimeError("APIClient.get is missing.")
        if not callable(getattr(client, "post", None)):
            raise RuntimeError("APIClient.post is missing.")
        if not callable(getattr(client, "_load_secret", None)):
            raise RuntimeError("APIClient._load_secret is missing.")

        cookie_header = str(client.session.headers.get("Cookie") or "").strip()
        authorization = str(client.session.headers.get("Authorization") or "").strip()
        if not cookie_header:
            raise RuntimeError("Cookie header was not constructed.")
        if not authorization.startswith("Bearer ") or len(authorization) <= len("Bearer "):
            raise RuntimeError("Authorization header was not constructed.")

        # Construct the complete live director hierarchy. This catches broken
        # inherited __init__ methods and missing runtime attributes.
        bot = LevelingFirstDirector(client, config, logger)
        required_methods = (
            "run", "objective_rows", "optimize_skill_tree", "optimize_skills",
            "enforce_pve_loadout", "dungeon_skill_ids", "auto_equip_best",
            "run_dungeon_autopilot", "final_report",
        )
        missing = [name for name in required_methods if not callable(getattr(bot, name, None))]
        if missing:
            raise RuntimeError("Director methods are missing: " + ", ".join(missing))

        print(f"[STARTUP CHECK OK] {LevelingFirstDirector.VERSION}")
        print("[STARTUP CHECK OK] APIClient and full Director hierarchy constructed.")
        print("[STARTUP CHECK SAFETY] No HTTP request or game action was performed.")
        return 0
    except Exception as exc:
        print(f"[STARTUP CHECK FAILED] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        try:
            if client is not None and getattr(client, "session", None) is not None:
                client.session.close()
        except Exception:
            pass


def live_read_check() -> int:
    """Read essential live schemas with GET only; never executes a game action."""
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_v3_5_1_live_read_check")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    client = None
    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
        client = engine.APIClient(config, logger)
        required = (
            ("auth/me", ("user", "characters")),
            ("character/me", ("character",)),
            ("skills/mine", ("skills",)),
            ("skill-tree/mine", ("allocations", "points_available")),
            ("quests/mine", ("quests",)),
            ("world/zones", ("zones",)),
        )
        failures: list[str] = []
        for path, expected_keys in required:
            result = client.get(path)
            if not result.ok:
                failures.append(
                    f"{path}: status={result.status} error={result.error or 'read failed'}"
                )
                continue
            if not isinstance(result.data, dict):
                failures.append(f"{path}: expected JSON object, got {type(result.data).__name__}")
                continue
            if not any(key in result.data for key in expected_keys):
                failures.append(
                    f"{path}: expected one of {', '.join(expected_keys)}; "
                    f"received keys {', '.join(map(str, result.data.keys()))}"
                )
                continue
            print(f"[LIVE READ OK] {path}")

        if failures:
            for failure in failures:
                print(f"[LIVE READ FAILED] {failure}")
            return 1

        print("[LIVE READ OK] Authentication and essential server schemas are readable.")
        print("[LIVE READ SAFETY] GET requests only; no POST or game action was performed.")
        return 0
    except Exception as exc:
        print(f"[LIVE READ FAILED] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        try:
            if client is not None and getattr(client, "session", None) is not None:
                client.session.close()
        except Exception:
            pass

def main() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        print(f"Configuration file is missing: {CONFIG_FILE}")
        return 2

    v34.install_atomic_json_saving()
    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
    except Exception as exc:
        print(f"Invalid configuration: {exc}")
        return 2

    logger = v34.configure_logging(config)
    v34.install_forbidden_endpoint_guard(logger)
    instance_lock = v34.SingleInstanceLock(INSTANCE_LOCK_FILE)
    if not instance_lock.acquire():
        logger.error("[INSTANCE] Another Leveling-First bot process is already running.")
        return 3

    bot = None
    try:
        logger.info("[START] Eldoria Bot %s", LevelingFirstDirector.VERSION)
        logger.info(
            "[MODE] LEVELING_FIRST: XP/hour + Gold/hour + Quest overlap; "
            "Skill Tree, PvE Skills and ready Dungeons are active."
        )
        logger.info(
            "[SAFETY] No-death, atomic state, single-instance, paid-action block, "
            "redacted logs and forbidden-endpoint guard remain active."
        )
        client = engine.APIClient(config, logger)
        bot = LevelingFirstDirector(client, config, logger)
        bot.run()
        return 0
    except KeyboardInterrupt:
        logger.info("[STOP] Interrupted by user.")
        return 130
    except Exception as exc:
        logger.exception("[FATAL] %s", exc)
        return 1
    finally:
        try:
            if bot is not None:
                bot.flush_progress_state(force=True)
                bot.save_leveling_state()
        except Exception as exc:
            logger.error("[STATE] Final state flush failed: %s", exc)
        instance_lock.release()


if __name__ == "__main__":
    if "--startup-check" in sys.argv:
        raise SystemExit(startup_check())
    if "--live-read-check" in sys.argv:
        raise SystemExit(live_read_check())
    raise SystemExit(main())
