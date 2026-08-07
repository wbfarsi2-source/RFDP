from __future__ import annotations

import importlib.util
import json
import logging
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
V35_FILE = SCRIPT_DIR / "eldoria_bot_v3_5_leveling_first_windows.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_6_persistent_combat_config.json"

if not V35_FILE.exists():
    raise RuntimeError(f"Required V3.5.1 file is missing: {V35_FILE}")

spec = importlib.util.spec_from_file_location("eldoria_v351_runtime", V35_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("The V3.5.1 module could not be loaded.")
v35 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v35
spec.loader.exec_module(v35)

v34 = v35.v34
engine = v35.engine
base = v35.base
v27 = v35.v27

ELDORIA_ROOT = v35.ELDORIA_ROOT
PRIVATE_DIR = v35.PRIVATE_DIR
OUTPUT_DIR = v35.OUTPUT_DIR
PROJECT_DIR = v35.PROJECT_DIR
STATE_DIR = v35.STATE_DIR
LOG_DIR = v35.LOG_DIR
CURRENT_PLAN_FILE = v35.CURRENT_PLAN_FILE
INSTANCE_LOCK_FILE = v35.INSTANCE_LOCK_FILE

# Every inherited module must read the same active V3.6 configuration.
for module in [v35, v34, *v34.ALL_MODULES]:
    try:
        module.CONFIG_FILE = CONFIG_FILE
    except Exception:
        pass


def as_int(value: Any, default: int = 0) -> int:
    return v35.as_int(value, default)


def as_float(value: Any, default: float = 0.0) -> float:
    return v35.as_float(value, default)


def normalize(value: Any) -> str:
    return v35.normalize(value)


def deep_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    return v34.deep_defaults(target, defaults)


def prepare_config(config: dict[str, Any]) -> dict[str, Any]:
    config = v35.prepare_config(config)
    deep_defaults(
        config,
        {
            "persistent_combat": {
                "enabled": True,
                "priority_max": 0,
                "boss_enabled": True,
                "maximum_session_age_seconds": 43200,
                "maximum_session_turns": 180,
                "pause_poll_seconds": 60,
                "maximum_single_pause_seconds": 21600,
                "minimum_post_turn_hp_ratio": 0.08,
                "minimum_post_turn_hp_flat": 20,
                "resume_extra_buffer": 12,
                "unknown_turn_attack_multiplier": 1.6,
                "unknown_turn_flat_buffer": 20,
                "unknown_total_damage_fraction": 0.35,
                "observed_turn_margin": 1.30,
                "observed_turn_flat_buffer": 8,
                "turn_history_window": 20,
                "state_heartbeat_seconds": 300,
                "target_audit_heartbeat_seconds": 1800,
                "use_first_aid": False,
                "use_mana_font": False,
                "cleanup_foreign_session": True,
            }
        },
    )
    config.setdefault("guaranteed_progress", {})[
        "target_audit_heartbeat_seconds"
    ] = max(
        900,
        as_int(
            config.get("persistent_combat", {}).get(
                "target_audit_heartbeat_seconds", 1800
            ),
            1800,
        ),
    )
    return config


def combat_context(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    keys = {str(key).lower() for key in data}
    return bool(
        keys.intersection(
            {
                "monster", "enemy", "player", "skills", "turn",
                "finished", "result", "combat_log", "stamina_cost",
            }
        )
    )


def session_id_from_response(data: Any) -> str | None:
    """Return the server's real alphanumeric combat token without coercing to int."""
    value = engine.recursive_find(
        data,
        {"session_id", "combat_id", "sessionid", "combatid"},
    )
    if value not in (None, "", "<REDACTED>", "[REDACTED]"):
        return str(value)

    if isinstance(data, dict):
        # Confirmed live schema: top-level {id, turn, monster, player, ...}.
        if combat_context(data):
            value = data.get("id")
            if value not in (None, ""):
                return str(value)
        for key in ("session", "combat", "combat_session", "battle"):
            node = data.get(key)
            if isinstance(node, dict):
                value = (
                    node.get("session_id")
                    or node.get("combat_id")
                    or node.get("id")
                )
            else:
                value = node
            if value not in (None, ""):
                return str(value)
    return None


def _context_dict(data: Any, names: set[str]) -> dict[str, Any]:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names and isinstance(value, dict):
                return value
        for value in data.values():
            found = _context_dict(value, names)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _context_dict(value, names)
            if found:
                return found
    return {}


def _number(data: Any, names: set[str], default: int | None = None) -> int | None:
    value = engine.recursive_find(data, names)
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def combat_state(data: Any) -> dict[str, Any]:
    player = _context_dict(data, {"player", "character", "hero", "self"})
    monster = _context_dict(data, {"monster", "enemy", "target", "boss"})
    finished_value = engine.recursive_find(data, {"finished"})
    result_value = engine.recursive_find(data, {"result", "outcome", "status"})
    result_text = str(result_value or "").strip().lower()
    finished = bool(finished_value) or result_text in {
        "victory", "won", "win", "defeat", "dead", "finished",
        "completed", "escaped", "fled", "flee", "forfeit",
    }
    return {
        "turn": _number(data, {"turn", "turn_number", "round"}),
        "finished": finished,
        "result": result_value,
        "player_hp": _number(player, {"hp", "current_hp", "player_hp"}),
        "player_hp_max": _number(player, {"hp_max", "max_hp", "maximum_hp"}),
        "player_mp": _number(player, {"mp", "current_mp", "player_mp"}),
        "player_mp_max": _number(player, {"mp_max", "max_mp"}),
        "enemy_hp": _number(monster, {"hp", "current_hp", "enemy_hp", "monster_hp"}),
        "enemy_hp_max": _number(monster, {"hp_max", "max_hp", "maximum_hp"}),
        "skills": (
            data.get("skills", [])
            if isinstance(data, dict) and isinstance(data.get("skills"), list)
            else []
        ),
    }


class PersistentCombatDirector(v35.LevelingFirstDirector):
    VERSION = "3.6.0-leveling-first-persistent-combat-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)
        self.persistent_file = STATE_DIR / "persistent_combat_state.json"
        self.persistent_state = engine.load_json(
            self.persistent_file,
            {
                "schema_version": 1,
                "pending": None,
                "turn_damage": {},
                "combat_sessions_started": 0,
                "sessions_resumed": 0,
                "session_expirations": 0,
                "pauses": 0,
                "pause_seconds": 0,
                "last_target_audit_signature": "",
                "last_target_audit_at": 0.0,
                "last_race_item_notice_at": 0.0,
            },
        )
        if not isinstance(self.persistent_state, dict):
            self.persistent_state = {}
        self.persistent_state.setdefault("schema_version", 1)
        self.persistent_state.setdefault("pending", None)
        self.persistent_state.setdefault("turn_damage", {})
        self.save_persistent_state()

    def save_persistent_state(self) -> None:
        engine.save_json(self.persistent_file, self.persistent_state)

    def persistent_cfg(self) -> dict[str, Any]:
        cfg = self.config.get("persistent_combat", {})
        return cfg if isinstance(cfg, dict) else {}

    def persistent_candidate(self, candidate) -> bool:
        cfg = self.persistent_cfg()
        if not cfg.get("enabled", True):
            return False
        if self.is_boss(candidate.monster):
            return bool(cfg.get("boss_enabled", True))
        return as_int(getattr(candidate, "priority", 99), 99) <= as_int(
            cfg.get("priority_max", 0), 0
        )

    def turn_damage_rows(self, monster_id: int) -> list[float]:
        mapping = self.persistent_state.get("turn_damage", {})
        rows = mapping.get(str(monster_id), []) if isinstance(mapping, dict) else []
        return [as_float(value, 0.0) for value in rows if as_float(value, 0.0) > 0]

    def record_turn_damage(self, monster_id: int, damage: int) -> None:
        if damage <= 0:
            return
        cfg = self.persistent_cfg()
        window = max(3, as_int(cfg.get("turn_history_window", 20), 20))
        mapping = self.persistent_state.setdefault("turn_damage", {})
        rows = mapping.setdefault(str(monster_id), [])
        if not isinstance(rows, list):
            rows = []
            mapping[str(monster_id)] = rows
        rows.append(int(damage))
        del rows[:-window]
        self.save_persistent_state()

    def turn_damage_bound(self, candidate, total_estimate: float | None = None) -> int:
        cfg = self.persistent_cfg()
        monster = candidate.monster
        monster_id = as_int(monster.get("id"), 0)
        rows = self.turn_damage_rows(monster_id)
        if rows:
            observed = max(rows)
            average = sum(rows) / len(rows)
            return max(
                1,
                math.ceil(
                    max(observed, average)
                    * as_float(cfg.get("observed_turn_margin", 1.30), 1.30)
                    + as_float(cfg.get("observed_turn_flat_buffer", 8), 8)
                ),
            )

        attack = max(
            0.0,
            as_float(monster.get("attack"), 0.0),
            as_float(monster.get("m_atk"), 0.0),
        )
        attack_bound = (
            attack
            * as_float(cfg.get("unknown_turn_attack_multiplier", 1.6), 1.6)
            + as_float(cfg.get("unknown_turn_flat_buffer", 20), 20)
        )
        fraction_bound = 0.0
        if total_estimate and total_estimate > 0:
            fraction_bound = total_estimate * as_float(
                cfg.get("unknown_total_damage_fraction", 0.35), 0.35
            )
        return max(1, math.ceil(max(attack_bound, fraction_bound)))

    def interactive_required_hp(self, candidate, hp_max: int, total_estimate: float) -> tuple[int, int]:
        cfg = self.persistent_cfg()
        turn_bound = self.turn_damage_bound(candidate, total_estimate)
        post_floor = max(
            as_int(cfg.get("minimum_post_turn_hp_flat", 20), 20),
            math.ceil(
                hp_max
                * as_float(cfg.get("minimum_post_turn_hp_ratio", 0.08), 0.08)
            ),
            as_int(self.config.get("combat", {}).get("interactive_emergency_hp", 20), 20),
        )
        required = math.ceil(
            turn_bound
            + post_floor
            + as_int(cfg.get("resume_extra_buffer", 12), 12)
        )
        return required, turn_bound

    def combat_assessment(self, candidate, character: dict[str, Any]) -> dict[str, Any]:
        row = super().combat_assessment(candidate, character)
        if not self.persistent_candidate(candidate):
            return row

        hp = max(0, as_int(character.get("hp"), 0))
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        stamina = max(0, as_int(character.get("stamina"), 0))
        stamina_cost = max(
            1,
            as_int(
                row.get("stamina_target", candidate.monster.get("stamina_cost")),
                1,
            ),
        )
        total_estimate = max(
            1.0,
            as_float(row.get("estimate"), as_float(candidate.predicted_damage, 1.0)),
        )
        required_hp, turn_bound = self.interactive_required_hp(
            candidate, hp_max, total_estimate
        )

        # Persistent combat is allowed only when one conservative next turn fits.
        if required_hp > hp_max:
            return row

        if hp < required_hp:
            state = "heal"
            reason = "waiting for one safe persistent-combat turn"
        elif stamina < stamina_cost:
            state = "resource"
            reason = "waiting for interactive-combat stamina"
        else:
            state = "ready"
            reason = "ready for persistent interactive combat"

        updated = dict(row)
        updated.update(
            {
                "state": state,
                "reason": reason,
                "required_hp": required_hp,
                "stamina_target": stamina_cost,
                "hp_short": max(0, required_hp - hp),
                "stamina_short": max(0, stamina_cost - stamina),
                "actionable": state == "ready",
                "no_death_blocked": False,
                "no_death_reason": None,
                "persistent_combat": True,
                "turn_damage_bound": turn_bound,
                "confidence": (
                    "persistent-observed-turn"
                    if self.turn_damage_rows(as_int(candidate.monster.get("id"), 0))
                    else "persistent-conservative-turn"
                ),
            }
        )
        return updated

    def skill_schema_ready(self) -> bool:
        if not self.config.get("skills", {}).get("use_mp_skills", True):
            return False
        state = self.final_state.get("interactive", {})
        return time.time() >= as_float(state.get("unavailable_until"), 0.0)

    @staticmethod
    def skill_id(skill: dict[str, Any]) -> int:
        return as_int(skill.get("id") or skill.get("skill_id"), 0)

    def preferred_combat_skill(self, state: dict[str, Any]) -> dict[str, Any] | None:
        skills = [row for row in state.get("skills", []) if isinstance(row, dict)]
        if not skills:
            return None
        mp = as_int(state.get("player_mp"), 0)
        order = [
            as_int(value, 0)
            for value in self.config.get("leveling_first", {}).get(
                "pve_skill_order", [28, 13, 1]
            )
            if as_int(value, 0) > 0
        ]
        by_id = {self.skill_id(row): row for row in skills}
        for skill_id in order:
            skill = by_id.get(skill_id)
            if not skill:
                continue
            if skill.get("can_use") is False:
                continue
            if as_int(skill.get("cooldown_remaining"), 0) > 0:
                continue
            if as_int(skill.get("mp_cost"), 0) > mp:
                continue
            return skill
        return None

    def _action_indexes(self, key: str, count: int) -> list[int]:
        schema = self.runtime.setdefault("combat_action_schema", {})
        index = schema.get(key)
        indexes: list[int] = []
        if isinstance(index, int) and 0 <= index < count:
            indexes.append(index)
        indexes.extend(value for value in range(count) if value not in indexes)
        return indexes

    def send_combat_action(
        self,
        session_id: str,
        *,
        skill: dict[str, Any] | None = None,
        flee: bool = False,
    ):
        if flee:
            key = "flee"
            templates = [
                {"type": "flee"},
                {"action": "flee"},
                {"kind": "flee"},
                {"type": "escape"},
                {"action": "escape"},
            ]
        elif skill is not None:
            key = "skill"
            sid = self.skill_id(skill)
            templates = [
                {"type": "skill", "skill_id": sid},
                {"action": "skill", "skill_id": sid},
                {"action": "use_skill", "skill_id": sid},
            ]
        else:
            key = "attack"
            templates = [
                {"type": "attack"},
                {"action": "attack"},
                {"kind": "attack"},
                {"type": "basic"},
                {"action": "basic"},
            ]

        endpoint = f"world/combat/{quote(str(session_id), safe='')}/action"
        last = None
        for index in self._action_indexes(key, len(templates)):
            result = self.client.post(endpoint, templates[index])
            last = result
            if result.ok:
                self.runtime.setdefault("combat_action_schema", {})[key] = index
                engine.save_json(engine.RUNTIME_STATE_FILE, self.runtime)
                return result
            if result.status is None:
                # Ambiguous write timeout: never send another possible action.
                return result
            if result.status not in {400, 404, 405, 409, 422}:
                return result
        return last

    def save_pending_session(
        self,
        session_id: str,
        candidate,
        current_data: Any,
        started_at: float,
    ) -> None:
        state = combat_state(current_data)
        self.persistent_state["pending"] = {
            "session_id": str(session_id),
            "monster_id": as_int(candidate.monster.get("id"), 0),
            "monster_name": self.monster_name(candidate),
            "started_at": started_at,
            "updated_at": time.time(),
            "state": state,
        }
        self.save_persistent_state()

    def clear_pending_session(self) -> None:
        if self.persistent_state.get("pending") is not None:
            self.persistent_state["pending"] = None
            self.save_persistent_state()

    def pending_session_for(self, candidate) -> tuple[str, Any, float] | None:
        pending = self.persistent_state.get("pending")
        if not isinstance(pending, dict):
            return None
        cfg = self.persistent_cfg()
        age = time.time() - as_float(pending.get("started_at"), 0.0)
        if age > as_float(cfg.get("maximum_session_age_seconds", 43200), 43200.0):
            self.clear_pending_session()
            return None
        if as_int(pending.get("monster_id"), 0) != as_int(candidate.monster.get("id"), 0):
            if cfg.get("cleanup_foreign_session", True):
                sid = str(pending.get("session_id") or "")
                if sid:
                    self.send_combat_action(sid, flee=True)
            self.clear_pending_session()
            return None
        session_id = str(pending.get("session_id") or "")
        if not session_id:
            self.clear_pending_session()
            return None
        return session_id, pending.get("state") or {}, as_float(pending.get("started_at"), time.time())

    def pause_open_session(
        self,
        session_id: str,
        candidate,
        current_data: Any,
        started_at: float,
        current_hp: int,
        target_hp: int,
    ) -> int:
        cfg = self.persistent_cfg()
        character = self.get_character()
        hp_regen = max(0.0, as_float(character.get("hp_regen_per_hour"), 0.0))
        if hp_regen <= 0:
            return current_hp
        missing = max(0, target_hp - current_hp)
        wait_seconds = math.ceil(missing / hp_regen * 3600.0)
        wait_seconds = min(
            wait_seconds,
            max(60, as_int(cfg.get("maximum_single_pause_seconds", 21600), 21600)),
        )
        if wait_seconds <= 0:
            return current_hp

        self.persistent_state["pauses"] = as_int(self.persistent_state.get("pauses"), 0) + 1
        self.persistent_state["pause_seconds"] = as_int(
            self.persistent_state.get("pause_seconds"), 0
        ) + wait_seconds
        self.save_pending_session(session_id, candidate, current_data, started_at)
        self.logger.info(
            "[COMBAT PAUSE] %s | session HP %s/%s | need %s | "
            "regen %.1f HP/h | waiting about %s without attacking.",
            self.monster_name(candidate),
            current_hp,
            as_int(combat_state(current_data).get("player_hp_max"), target_hp),
            target_hp,
            hp_regen,
            v27.format_duration(wait_seconds),
        )

        poll = max(30, as_int(cfg.get("pause_poll_seconds", 60), 60))
        remaining = wait_seconds
        while remaining > 0:
            sleep_for = min(poll, remaining)
            time.sleep(sleep_for)
            remaining -= sleep_for
            # GET only. This keeps authentication/network state observable while
            # the combat action stream remains paused.
            check = self.client.get("character/me")
            if not check.ok and check.status in {401, 403}:
                return current_hp
            if remaining == 0 or remaining % max(poll * 5, 300) == 0:
                self.logger.info(
                    "[COMBAT PAUSE] %s remaining; same session retained.",
                    v27.format_duration(remaining),
                )

        regenerated = math.floor(wait_seconds * hp_regen / 3600.0)
        hp_max = max(target_hp, as_int(combat_state(current_data).get("player_hp_max"), target_hp))
        return min(hp_max, current_hp + regenerated)

    def interactive_combat(self, candidate):
        cfg = self.persistent_cfg()
        pending = self.pending_session_for(candidate)
        if pending is not None:
            session_id, saved_state, started_at = pending
            current_data = {
                "id": session_id,
                "turn": saved_state.get("turn"),
                "finished": saved_state.get("finished", False),
                "result": saved_state.get("result"),
                "player": {
                    "hp": saved_state.get("player_hp"),
                    "hp_max": saved_state.get("player_hp_max"),
                    "mp": saved_state.get("player_mp"),
                    "mp_max": saved_state.get("player_mp_max"),
                },
                "monster": {
                    "hp": saved_state.get("enemy_hp"),
                    "hp_max": saved_state.get("enemy_hp_max"),
                },
                "skills": saved_state.get("skills", []),
            }
            self.persistent_state["sessions_resumed"] = as_int(
                self.persistent_state.get("sessions_resumed"), 0
            ) + 1
            self.logger.info(
                "[COMBAT RESUME] Reusing saved session for %s.",
                self.monster_name(candidate),
            )
        else:
            start = self.client.post(
                f"world/combat/start/{candidate.monster['id']}", {}
            )
            if not start.ok:
                return start
            session_id = session_id_from_response(start.data)
            if session_id is None:
                self.logger.info(
                    "[COMBAT] Session format not recognized; no normal Fight fallback after start."
                )
                return engine.APIResult(False, 200, start.data, "session_id_missing")
            current_data = start.data
            started_at = time.time()
            self.persistent_state["combat_sessions_started"] = as_int(
                self.persistent_state.get("combat_sessions_started"), 0
            ) + 1
            self.save_pending_session(session_id, candidate, current_data, started_at)
            self.logger.info(
                "[COMBAT START] Persistent session opened for %s.",
                self.monster_name(candidate),
            )

        monster_id = as_int(candidate.monster.get("id"), 0)
        maximum_turns = max(
            1,
            min(
                as_int(cfg.get("maximum_session_turns", 180), 180),
                as_int(self.config.get("skills", {}).get("maximum_combat_turns", 180), 180),
            ),
        )
        turns = 0

        while turns < maximum_turns:
            state = combat_state(current_data)
            if state["finished"]:
                self.clear_pending_session()
                result_text = normalize(state.get("result"))
                victory = result_text in {"victory", "won", "win", "completed", "finished"}
                return engine.APIResult(
                    victory,
                    200,
                    current_data,
                    None if victory else (result_text or "combat_finished"),
                )

            current_hp = as_int(state.get("player_hp"), 0)
            hp_max = max(current_hp, as_int(state.get("player_hp_max"), current_hp))
            total_estimate = max(1.0, as_float(candidate.predicted_damage, 1.0))
            required_hp, turn_bound = self.interactive_required_hp(
                candidate, hp_max, total_estimate
            )

            if current_hp < required_hp:
                estimated_hp = self.pause_open_session(
                    session_id,
                    candidate,
                    current_data,
                    started_at,
                    current_hp,
                    required_hp,
                )
                if estimated_hp < required_hp:
                    # Continue waiting inside the same call instead of returning to
                    # housekeeping while a live combat session is open.
                    if estimated_hp <= current_hp:
                        self.save_pending_session(session_id, candidate, current_data, started_at)
                        return engine.APIResult(
                            False,
                            200,
                            current_data,
                            "persistent_combat_no_regeneration",
                        )
                    if isinstance(current_data, dict):
                        player_node = current_data.get("player")
                        if isinstance(player_node, dict):
                            player_node["hp"] = estimated_hp
                    self.save_pending_session(session_id, candidate, current_data, started_at)
                    continue
                # The server applies regeneration when the next action is resolved.
                # Use the estimate only for the pre-action safety decision.
                current_hp = estimated_hp

            skill = self.preferred_combat_skill(state)
            action = self.send_combat_action(session_id, skill=skill)
            if (
                skill is not None
                and action is not None
                and not action.ok
                and action.status in {400, 405, 422}
            ):
                # A rejected skill/schema must not discard a valid session.
                # Fall back to one basic action only after an explicit rejection.
                self.logger.info(
                    "[COMBAT SKILL] Skill %s rejected (%s); trying one basic attack.",
                    self.skill_id(skill),
                    action.error or action.status,
                )
                skill = None
                action = self.send_combat_action(session_id, skill=None)
            if action is None:
                self.save_pending_session(session_id, candidate, current_data, started_at)
                return engine.APIResult(False, 422, current_data, "combat_action_schema_unknown")
            if not action.ok:
                if action.status in {404, 409, 410}:
                    self.persistent_state["session_expirations"] = as_int(
                        self.persistent_state.get("session_expirations"), 0
                    ) + 1
                    self.clear_pending_session()
                else:
                    self.save_pending_session(session_id, candidate, current_data, started_at)
                return action

            next_data = action.data
            next_state = combat_state(next_data)
            next_hp = as_int(next_state.get("player_hp"), current_hp)
            damage = max(0, current_hp - next_hp)
            if damage > 0:
                self.record_turn_damage(monster_id, damage)

            turns += 1
            self.logger.info(
                "[COMBAT TURN] %s | turn %s | action %s | HP %s/%s | enemy HP %s/%s | damage %s.",
                self.monster_name(candidate),
                next_state.get("turn") or turns,
                (
                    f"skill {self.skill_id(skill)}"
                    if skill is not None
                    else "basic attack"
                ),
                next_state.get("player_hp"),
                next_state.get("player_hp_max"),
                next_state.get("enemy_hp"),
                next_state.get("enemy_hp_max"),
                damage,
            )
            current_data = next_data
            self.save_pending_session(session_id, candidate, current_data, started_at)
            time.sleep(as_float(self.config.get("automation", {}).get("action_delay_seconds", 1.0), 1.0))

        self.save_pending_session(session_id, candidate, current_data, started_at)
        return engine.APIResult(False, 408, current_data, "maximum_session_turns_reached")

    def select_target_row(self, objective, rows):
        selected = super().select_target_row(objective, rows)
        if selected is not None and getattr(self, "_target_audit_message", None):
            candidate = selected.get("candidate")
            self._target_audit_signature = "|".join(
                [
                    self.objective_key(objective),
                    str(candidate.monster.get("id") if candidate else ""),
                    str(selected.get("state") or ""),
                    str(as_int(selected.get("required_hp"), 0)),
                ]
            )
        return selected

    def log_target_audit_once(self) -> None:
        message = str(getattr(self, "_target_audit_message", "") or "").strip()
        if not message:
            return
        signature = str(getattr(self, "_target_audit_signature", "") or self.primary_key())
        now = time.time()
        heartbeat = max(
            900.0,
            as_float(
                self.persistent_cfg().get("target_audit_heartbeat_seconds", 1800),
                1800.0,
            ),
        )
        if (
            signature == self.persistent_state.get("last_target_audit_signature")
            and now - as_float(self.persistent_state.get("last_target_audit_at"), 0.0) < heartbeat
        ):
            return
        self.persistent_state["last_target_audit_signature"] = signature
        self.persistent_state["last_target_audit_at"] = now
        self.save_persistent_state()
        self.logger.info("[TARGET AUDIT] %s", message)

    def try_equip_best_race_item(self) -> None:
        cfg = self.config.get("leveling_first", {})
        if not cfg.get("race_equipment_enabled", True):
            return
        payload = super(v35.LevelingFirstDirector, self).get_inventory_payload()
        inventory = payload.get("inventory") if isinstance(payload, dict) else None
        race_equipment = payload.get("race_equipment") if isinstance(payload, dict) else None
        if not isinstance(inventory, list) or not isinstance(race_equipment, list):
            return
        inventory_ids = {
            as_int(row.get("id"), 0)
            for row in inventory
            if isinstance(row, dict) and as_int(row.get("id"), 0) > 0
        }
        valid = []
        for row in race_equipment:
            if not isinstance(row, dict):
                continue
            owned_id = as_int(row.get("owned_id"), 0)
            if owned_id in inventory_ids:
                valid.append(row)
        if valid:
            # Only let the inherited implementation run when the endpoint ID is
            # a real normal-inventory ID. This prevents the confirmed 404 loop.
            return super().try_equip_best_race_item()

        now = time.time()
        if now - as_float(self.persistent_state.get("last_race_item_notice_at"), 0.0) >= 86400:
            self.persistent_state["last_race_item_notice_at"] = now
            self.save_persistent_state()
            self.logger.info(
                "[EQUIP XP-FIRST] Race equipment has no valid normal-inventory ID; "
                "unsafe equip POST skipped."
            )

    def log_resource_plan(self, pending, character: dict[str, Any]) -> None:
        if not isinstance(pending, dict):
            return
        objective = self._primary_objective
        candidate = pending["candidate"]
        required_hp = as_int(pending.get("required_hp"), 0)
        required_stamina = as_int(pending.get("stamina_target"), 0)
        hp = as_int(character.get("hp"), 0)
        hp_max = as_int(character.get("hp_max"), 0)
        stamina = as_int(character.get("stamina"), 0)
        hp_wait = self.hp_wait_seconds(character, required_hp)
        stamina_wait = self.stamina_wait_seconds(character, required_stamina)
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
        if not self.should_log_plan(signature, wait=True):
            return
        missing = []
        if hp < required_hp:
            missing.append(f"HP +{required_hp - hp}")
        if stamina < required_stamina:
            missing.append(f"STM +{required_stamina - stamina}")
        self.logger.info(
            "[MISSION] Primary: %s [%s] | %s | remaining %s.",
            getattr(objective, "quest_name", "No active Quest"),
            str(getattr(objective, "quest_type", "none")).upper(),
            self.objective_label(objective),
            getattr(objective, "remaining", 0),
        )
        self.logger.info(
            "[STEP] RESOURCE PREPARATION -> %s.", self.monster_name(candidate)
        )
        self.logger.info(
            "[WAIT] Need %s | HP %s; safe target %s; max %s | STM %s/%s | "
            "natural ETA about %s.",
            ", ".join(missing) if missing else "re-evaluation",
            hp,
            required_hp,
            hp_max,
            stamina,
            required_stamina,
            v27.format_duration(total_wait),
        )
        self.logger.info(
            "[WHILE WAITING] Claims, Daily checks, Craft, Skills and equipment remain active."
        )
        self.write_current_plan(
            step="RESOURCE PREPARATION",
            row=pending,
            character=character,
            details=(
                f"Waiting for {', '.join(missing)}; target HP {required_hp}/{hp_max}; "
                f"ETA {v27.format_duration(total_wait)}"
            ),
        )


def startup_check() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eldoria_v36_startup_check")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(sys.stdout))
    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
        client = engine.APIClient(config, logger)
        bot = PersistentCombatDirector(client, config, logger)
        if session_id_from_response(
            {"id": "abc123", "turn": 1, "monster": {}, "player": {}, "finished": False}
        ) != "abc123":
            raise RuntimeError("Alphanumeric top-level combat session parser failed.")
        print(f"[STARTUP CHECK OK] {PersistentCombatDirector.VERSION}")
        print("[STARTUP CHECK OK] APIClient, full Director and alphanumeric session parser constructed.")
        print("[STARTUP CHECK SAFETY] No HTTP request or game action was performed.")
        try:
            client.session.close()
        except Exception:
            pass
        return 0
    except Exception as exc:
        print(f"[STARTUP CHECK FAILED] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


def live_read_check() -> int:
    return v35.live_read_check()


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
        logger.error("[INSTANCE] Another Eldoria bot process is already running.")
        return 3

    bot = None
    try:
        logger.info("[START] Eldoria Bot %s", PersistentCombatDirector.VERSION)
        logger.info(
            "[MODE] LEVELING_FIRST + persistent interactive sessions: "
            "pause, regenerate and resume the same combat when needed."
        )
        logger.info(
            "[SAFETY] No-death turn gate, atomic state, single-instance, paid-action block, "
            "redacted logs and forbidden-endpoint guard remain active."
        )
        client = engine.APIClient(config, logger)
        bot = PersistentCombatDirector(client, config, logger)
        bot.run()
        return 0
    except KeyboardInterrupt:
        logger.info("[STOP] Interrupted by user; pending combat session is preserved locally.")
        return 130
    except Exception as exc:
        logger.exception("[FATAL] %s", exc)
        return 1
    finally:
        try:
            if bot is not None:
                bot.flush_progress_state(force=True)
                bot.save_leveling_state()
                bot.save_persistent_state()
        except Exception as exc:
            logger.error("[STATE] Final state flush failed: %s", exc)
        instance_lock.release()


if __name__ == "__main__":
    if "--startup-check" in sys.argv:
        raise SystemExit(startup_check())
    if "--live-read-check" in sys.argv:
        raise SystemExit(live_read_check())
    raise SystemExit(main())
