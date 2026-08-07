from __future__ import annotations

import importlib.util
import logging
import math
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
V36_FILE = SCRIPT_DIR / "eldoria_bot_v3_6_persistent_combat_windows.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_7_sustain_combat_config.json"

if not V36_FILE.exists():
    raise RuntimeError(f"Required V3.6 file is missing: {V36_FILE}")

spec = importlib.util.spec_from_file_location("eldoria_v36_runtime", V36_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("The V3.6 module could not be loaded.")
v36 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v36
spec.loader.exec_module(v36)

v35 = v36.v35
v34 = v36.v34
engine = v36.engine
base = v36.base
v27 = v36.v27

ELDORIA_ROOT = v36.ELDORIA_ROOT
PRIVATE_DIR = v36.PRIVATE_DIR
OUTPUT_DIR = v36.OUTPUT_DIR
PROJECT_DIR = v36.PROJECT_DIR
STATE_DIR = v36.STATE_DIR
LOG_DIR = v36.LOG_DIR
CURRENT_PLAN_FILE = v36.CURRENT_PLAN_FILE
INSTANCE_LOCK_FILE = v36.INSTANCE_LOCK_FILE

for module in [v36, v35, v34, *v34.ALL_MODULES]:
    try:
        module.CONFIG_FILE = CONFIG_FILE
    except Exception:
        pass


def as_int(value: Any, default: int = 0) -> int:
    return v36.as_int(value, default)


def as_float(value: Any, default: float = 0.0) -> float:
    return v36.as_float(value, default)


def normalize(value: Any) -> str:
    return v36.normalize(value)


def deep_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    return v36.deep_defaults(target, defaults)


def prepare_config(config: dict[str, Any]) -> dict[str, Any]:
    config = v36.prepare_config(config)
    deep_defaults(
        config,
        {
            "persistent_combat": {
                "enabled": True,
                "priority_max": 3,
                "boss_enabled": True,
                "maximum_session_age_seconds": 43200,
                "maximum_session_turns": 240,
                "natural_regeneration_inside_session": False,
                "minimum_post_turn_hp_ratio": 0.01,
                "minimum_post_turn_hp_flat": 5,
                "resume_extra_buffer": 0,
                "unknown_turn_attack_multiplier": 1.0,
                "unknown_turn_flat_buffer": 10,
                "unknown_total_damage_fraction": 0.25,
                "turn_history_window": 40,
                "target_audit_heartbeat_seconds": 1800,
            },
            "sustain_combat": {
                "enabled": True,
                "exact_log_damage": True,
                "sample_window": 40,
                "phase_thresholds": [0.75, 0.50, 0.25],
                "unknown_margin": 1.20,
                "unknown_flat_buffer": 8,
                "unknown_reserve_ratio": 0.04,
                "unknown_reserve_flat": 14,
                "warmup_samples": 3,
                "warmup_margin": 1.16,
                "warmup_flat_buffer": 6,
                "warmup_reserve_ratio": 0.025,
                "warmup_reserve_flat": 9,
                "mature_samples": 8,
                "mature_margin": 1.08,
                "mature_flat_buffer": 4,
                "mature_reserve_ratio": 0.012,
                "mature_reserve_flat": 5,
                "stable_cv_threshold": 0.22,
                "spike_ratio": 1.35,
                "spike_margin": 1.20,
                "spike_flat_buffer": 8,
                "boss_margin_floor": 1.12,
                "boss_reserve_flat": 8,
                "phase_unknown_margin_bonus": 0.12,
                "phase_unknown_flat_buffer": 6,
                "absolute_emergency_hp": 3,
                "first_aid_skill_id": 22,
                "defensive_stance_skill_id": 3,
                "healing_skill_id": 10,
                "life_drain_skill_id": 19,
                "mana_font_skill_id": 60,
                "first_aid_missing_ratio": 0.12,
                "healing_missing_ratio": 0.20,
                "life_drain_missing_ratio": 0.10,
                "mana_font_mp_ratio": 0.28,
                "defensive_stance_unknown_or_boss": True,
                "utility_retry_seconds": 45,
                "maximum_utility_wait_seconds": 180,
                "damage_skill_order": [28, 13, 1, 2, 7],
                "preserve_session_when_no_safe_action": True,
            },
        },
    )
    config.setdefault("persistent_combat", {})["priority_max"] = max(
        3, as_int(config.get("persistent_combat", {}).get("priority_max"), 3)
    )
    config.setdefault("persistent_combat", {})[
        "natural_regeneration_inside_session"
    ] = False
    return config


def _logs(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("log"), list):
        return [row for row in data["log"] if isinstance(row, dict)]
    return []


def appended_logs(previous: Any, current: Any) -> list[dict[str, Any]]:
    before = _logs(previous)
    after = _logs(current)
    if len(after) >= len(before) and after[: len(before)] == before:
        return after[len(before) :]
    # If the server returned only the last action logs, use the whole list.
    return after


def exact_monster_damage(previous: Any, current: Any) -> int:
    total = 0
    for row in appended_logs(previous, current):
        actor = normalize(row.get("actor"))
        kind = normalize(row.get("kind"))
        target = normalize(row.get("target"))
        if actor in {"monster", "enemy", "boss"} and kind in {
            "hit", "crit", "critical", "dot", "damage"
        }:
            total += max(0, as_int(row.get("value"), 0))
        elif target in {"you", "tu", "tú", "player", "hero"} and kind in {
            "hit", "crit", "critical", "dot", "damage"
        }:
            total += max(0, as_int(row.get("value"), 0))
    return total


def exact_player_heal(previous: Any, current: Any) -> int:
    total = 0
    for row in appended_logs(previous, current):
        actor = normalize(row.get("actor"))
        kind = normalize(row.get("kind"))
        target = normalize(row.get("target"))
        if kind in {"heal", "healing", "lifesteal", "hp_restore"} and (
            actor in {"player", "hero", "you"}
            or target in {"player", "hero", "you", "tu", "tú"}
        ):
            total += max(0, as_int(row.get("value"), 0))
    return total


def phase_bucket(enemy_hp: int, enemy_hp_max: int) -> str:
    if enemy_hp_max <= 0:
        return "unknown"
    ratio = max(0.0, min(1.0, enemy_hp / enemy_hp_max))
    if ratio > 0.75:
        return "100-75"
    if ratio > 0.50:
        return "75-50"
    if ratio > 0.25:
        return "50-25"
    return "25-0"


class SustainCombatDirector(v36.PersistentCombatDirector):
    VERSION = "3.7.0-leveling-first-sustain-combat-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)
        self.persistent_state.setdefault("schema_version", 2)
        self.persistent_state.setdefault("turn_samples", {})
        self.persistent_state.setdefault("utility_verified", {})
        self.persistent_state.setdefault("utility_failures", {})
        self.persistent_state.setdefault("last_utility_attempt", {})
        self.persistent_state.setdefault("natural_regen_inside_session_verified", False)
        self.save_persistent_state()

    def sustain_cfg(self) -> dict[str, Any]:
        cfg = self.config.get("sustain_combat", {})
        return cfg if isinstance(cfg, dict) else {}

    def persistent_candidate(self, candidate) -> bool:
        cfg = self.persistent_cfg()
        if not cfg.get("enabled", True):
            return False
        if self.is_boss(candidate.monster):
            return bool(cfg.get("boss_enabled", True))
        return as_int(getattr(candidate, "priority", 99), 99) <= as_int(
            cfg.get("priority_max", 3), 3
        )

    def detailed_samples(self, monster_id: int) -> list[dict[str, Any]]:
        mapping = self.persistent_state.get("turn_samples", {})
        rows = mapping.get(str(monster_id), []) if isinstance(mapping, dict) else []
        return [row for row in rows if isinstance(row, dict) and as_int(row.get("damage"), 0) > 0]

    def turn_damage_rows(self, monster_id: int) -> list[float]:
        detailed = self.detailed_samples(monster_id)
        if detailed:
            return [float(as_int(row.get("damage"), 0)) for row in detailed]
        return super().turn_damage_rows(monster_id)

    def record_turn_sample(
        self,
        monster_id: int,
        damage: int,
        *,
        phase: str,
        turn: int,
        action: str,
        boss: bool,
    ) -> None:
        if damage <= 0:
            return
        cfg = self.sustain_cfg()
        window = max(8, as_int(cfg.get("sample_window", 40), 40))
        mapping = self.persistent_state.setdefault("turn_samples", {})
        rows = mapping.setdefault(str(monster_id), [])
        if not isinstance(rows, list):
            rows = []
            mapping[str(monster_id)] = rows
        rows.append(
            {
                "damage": int(damage),
                "phase": str(phase),
                "turn": int(turn),
                "action": str(action),
                "boss": bool(boss),
                "at": time.time(),
            }
        )
        del rows[:-window]
        # Keep the legacy simple history in sync for inherited diagnostics.
        legacy = self.persistent_state.setdefault("turn_damage", {})
        simple = legacy.setdefault(str(monster_id), [])
        if not isinstance(simple, list):
            simple = []
            legacy[str(monster_id)] = simple
        simple.append(int(damage))
        del simple[:-window]
        self.save_persistent_state()

    @staticmethod
    def percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = max(0.0, min(1.0, q)) * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    def dynamic_turn_profile(
        self,
        candidate,
        *,
        hp_max: int,
        enemy_hp: int | None = None,
        enemy_hp_max: int | None = None,
        total_estimate: float | None = None,
    ) -> dict[str, Any]:
        cfg = self.sustain_cfg()
        monster_id = as_int(candidate.monster.get("id"), 0)
        boss = self.is_boss(candidate.monster)
        phase = phase_bucket(as_int(enemy_hp, 0), as_int(enemy_hp_max, 0))
        detailed = self.detailed_samples(monster_id)
        phase_rows = [
            as_float(row.get("damage"), 0.0)
            for row in detailed
            if row.get("phase") == phase and as_float(row.get("damage"), 0.0) > 0
        ]
        all_rows = [
            as_float(row.get("damage"), 0.0)
            for row in detailed
            if as_float(row.get("damage"), 0.0) > 0
        ]
        rows = phase_rows if phase_rows else all_rows
        count = len(rows)
        phase_known = len(phase_rows) >= max(2, as_int(cfg.get("warmup_samples", 3), 3))

        warmup = max(1, as_int(cfg.get("warmup_samples", 3), 3))
        mature = max(warmup + 1, as_int(cfg.get("mature_samples", 8), 8))
        stable_cv = as_float(cfg.get("stable_cv_threshold", 0.22), 0.22)
        mean = statistics.mean(rows) if rows else 0.0
        stdev = statistics.pstdev(rows) if len(rows) >= 2 else 0.0
        cv = stdev / mean if mean > 0 else 999.0
        observed_max = max(rows) if rows else 0.0
        upper_stat = max(
            observed_max,
            self.percentile(rows, 0.95),
            mean + 2.0 * stdev,
        ) if rows else 0.0

        spike = False
        if len(rows) >= 2:
            prior_max = max(rows[:-1]) if rows[:-1] else 0.0
            spike = prior_max > 0 and rows[-1] >= prior_max * as_float(
                cfg.get("spike_ratio", 1.35), 1.35
            )

        if count == 0:
            attack = max(
                as_float(candidate.monster.get("attack"), 0.0),
                as_float(candidate.monster.get("m_atk"), 0.0),
            )
            estimate_fraction = max(0.0, as_float(total_estimate, 0.0)) * as_float(
                self.persistent_cfg().get("unknown_total_damage_fraction", 0.25), 0.25
            )
            raw = max(
                attack * as_float(
                    self.persistent_cfg().get("unknown_turn_attack_multiplier", 1.0), 1.0
                ) + as_float(
                    self.persistent_cfg().get("unknown_turn_flat_buffer", 10), 10
                ),
                estimate_fraction,
                1.0,
            )
            margin = as_float(cfg.get("unknown_margin", 1.20), 1.20)
            flat = as_float(cfg.get("unknown_flat_buffer", 8), 8)
            reserve = max(
                as_int(cfg.get("unknown_reserve_flat", 14), 14),
                math.ceil(hp_max * as_float(cfg.get("unknown_reserve_ratio", 0.04), 0.04)),
            )
            confidence = "unknown"
        elif count < mature or cv > stable_cv:
            raw = max(1.0, upper_stat)
            margin = as_float(cfg.get("warmup_margin", 1.16), 1.16)
            flat = as_float(cfg.get("warmup_flat_buffer", 6), 6)
            reserve = max(
                as_int(cfg.get("warmup_reserve_flat", 9), 9),
                math.ceil(hp_max * as_float(cfg.get("warmup_reserve_ratio", 0.025), 0.025)),
            )
            confidence = "warmup"
        else:
            raw = max(1.0, upper_stat)
            margin = as_float(cfg.get("mature_margin", 1.08), 1.08)
            flat = as_float(cfg.get("mature_flat_buffer", 4), 4)
            reserve = max(
                as_int(cfg.get("mature_reserve_flat", 5), 5),
                math.ceil(hp_max * as_float(cfg.get("mature_reserve_ratio", 0.012), 0.012)),
            )
            confidence = "mature"

        if spike:
            margin = max(margin, as_float(cfg.get("spike_margin", 1.20), 1.20))
            flat = max(flat, as_float(cfg.get("spike_flat_buffer", 8), 8))
            confidence += "+spike"

        if boss:
            margin = max(margin, as_float(cfg.get("boss_margin_floor", 1.12), 1.12))
            reserve = max(reserve, as_int(cfg.get("boss_reserve_flat", 8), 8))

        if detailed and not phase_known:
            margin += as_float(cfg.get("phase_unknown_margin_bonus", 0.12), 0.12)
            flat += as_float(cfg.get("phase_unknown_flat_buffer", 6), 6)
            confidence += "+new-phase"

        bound = max(1, math.ceil(raw * margin + flat))
        emergency = max(1, as_int(cfg.get("absolute_emergency_hp", 3), 3))
        required = min(hp_max + 1, bound + max(reserve, emergency))
        return {
            "bound": bound,
            "reserve": max(reserve, emergency),
            "required_hp": required,
            "samples": count,
            "all_samples": len(all_rows),
            "phase": phase,
            "phase_known": phase_known,
            "mean": round(mean, 3),
            "max": round(observed_max, 3),
            "cv": round(cv, 4) if cv < 900 else None,
            "confidence": confidence,
        }

    def turn_damage_bound(self, candidate, total_estimate: float | None = None) -> int:
        hp_max = max(1, as_int(getattr(self, "_scheduler_character", {}).get("hp_max"), 1))
        return as_int(
            self.dynamic_turn_profile(
                candidate,
                hp_max=hp_max,
                total_estimate=total_estimate,
            )["bound"],
            1,
        )

    def interactive_required_hp(self, candidate, hp_max: int, total_estimate: float) -> tuple[int, int]:
        profile = self.dynamic_turn_profile(
            candidate,
            hp_max=hp_max,
            total_estimate=total_estimate,
        )
        return as_int(profile["required_hp"], hp_max + 1), as_int(profile["bound"], hp_max)

    def combat_assessment(self, candidate, character: dict[str, Any]) -> dict[str, Any]:
        row = super().combat_assessment(candidate, character)
        if not self.persistent_candidate(candidate):
            return row

        hp = max(0, as_int(character.get("hp"), 0))
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        stamina = max(0, as_int(character.get("stamina"), 0))
        stamina_cost = max(1, as_int(candidate.monster.get("stamina_cost"), 1))
        total_estimate = max(
            1.0,
            as_float(row.get("total_fight_estimate"), 0.0),
            as_float(row.get("estimate"), 0.0),
            as_float(candidate.predicted_damage, 1.0),
        )
        profile = self.dynamic_turn_profile(
            candidate,
            hp_max=hp_max,
            enemy_hp=as_int(candidate.monster.get("hp") or candidate.monster.get("hp_max"), 0),
            enemy_hp_max=as_int(candidate.monster.get("hp_max") or candidate.monster.get("hp"), 0),
            total_estimate=total_estimate,
        )
        required_hp = as_int(profile["required_hp"], hp_max + 1)
        if required_hp > hp_max:
            blocked = dict(row)
            blocked.update(
                {
                    "state": "blocked",
                    "reason": "even one conservative turn may be lethal",
                    "required_hp": required_hp,
                    "persistent_combat": True,
                    "no_death_blocked": True,
                    "no_death_reason": "persistent-one-shot-risk",
                    "turn_profile": profile,
                }
            )
            return blocked

        if hp < required_hp:
            state = "heal"
            reason = "waiting for one safe sustain-combat action"
        elif stamina < stamina_cost:
            state = "resource"
            reason = "waiting for interactive-combat stamina"
        else:
            state = "ready"
            reason = "ready for turn-based sustain combat"

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
                # Critical root fix: inherited real-time preflight must use one-turn
                # risk, not the old full-fight damage estimate.
                "total_fight_estimate": total_estimate,
                "estimate": as_int(profile["bound"], 1),
                "minimum_post_hp": as_int(profile["reserve"], 3),
                "turn_damage_bound": as_int(profile["bound"], 1),
                "turn_profile": profile,
                "confidence": f"sustain-{profile['confidence']}",
            }
        )
        return updated

    def execute_fight(self, candidate) -> bool:
        # The legacy chain only enabled interactive combat for priority 0/1 or
        # selected high-risk cases. Quest, loot and material targets can have
        # priorities up to 3, so temporarily promote only the combat mode while
        # preserving the original Quest identity and reason.
        if not self.persistent_candidate(candidate):
            return super().execute_fight(candidate)
        original_priority = getattr(candidate, "priority", 99)
        try:
            candidate.priority = 0
            return super().execute_fight(candidate)
        finally:
            candidate.priority = original_priority

    def skill_by_id(self, state: dict[str, Any], skill_id: int) -> dict[str, Any] | None:
        for row in state.get("skills", []):
            if isinstance(row, dict) and self.skill_id(row) == skill_id:
                return row
        return None

    @staticmethod
    def skill_usable(skill: dict[str, Any] | None, mp: int) -> bool:
        if not isinstance(skill, dict):
            return False
        if skill.get("can_use") is False:
            return False
        if as_int(skill.get("cooldown_remaining"), 0) > 0:
            return False
        return as_int(skill.get("mp_cost"), 0) <= mp

    def has_defense_buff(self, raw_data: Any) -> bool:
        state = v36.combat_state(raw_data)
        player = v36._context_dict(raw_data, {"player", "character", "hero", "self"})
        buffs = player.get("buffs", []) if isinstance(player, dict) else []
        for row in buffs if isinstance(buffs, list) else []:
            text = normalize(row if isinstance(row, str) else row.get("code") or row.get("name") or row)
            if "defense" in text or "defensive" in text or "shield" in text:
                return True
        return False

    def utility_verified(self, key: str) -> bool:
        mapping = self.persistent_state.get("utility_verified", {})
        return bool(mapping.get(key)) if isinstance(mapping, dict) else False

    def mark_utility_verified(self, key: str, value: bool = True) -> None:
        self.persistent_state.setdefault("utility_verified", {})[key] = bool(value)
        self.save_persistent_state()

    def choose_sustain_action(
        self,
        candidate,
        raw_data: Any,
        state: dict[str, Any],
        profile: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        cfg = self.sustain_cfg()
        hp = as_int(state.get("player_hp"), 0)
        hp_max = max(1, as_int(state.get("player_hp_max"), hp))
        mp = as_int(state.get("player_mp"), 0)
        mp_max = max(1, as_int(state.get("player_mp_max"), mp))
        missing_ratio = max(0.0, (hp_max - hp) / hp_max)
        required = as_int(profile.get("required_hp"), hp_max + 1)
        bound = as_int(profile.get("bound"), hp_max)
        emergency = max(1, as_int(cfg.get("absolute_emergency_hp", 3), 3))

        first_aid_id = as_int(cfg.get("first_aid_skill_id", 22), 22)
        first_aid = self.skill_by_id(state, first_aid_id)
        first_aid_safe = hp > bound + emergency or self.utility_verified("first_aid_bonus")
        if (
            self.skill_usable(first_aid, mp)
            and first_aid_safe
            and (
                hp < required
                or missing_ratio >= as_float(cfg.get("first_aid_missing_ratio", 0.12), 0.12)
            )
        ):
            return "first_aid", first_aid

        # When a saved session is resumed, cooldown information may be stale. If
        # First Aid has already been verified as a true bonus action, a rate-limited
        # probe is safer than attacking or fabricating natural HP regeneration.
        if hp <= bound + emergency and isinstance(first_aid, dict) and self.utility_verified("first_aid_bonus"):
            attempts = self.persistent_state.setdefault("last_utility_attempt", {})
            last = as_float(attempts.get("first_aid_probe"), 0.0)
            retry = max(30.0, as_float(cfg.get("utility_retry_seconds", 45), 45.0))
            if time.time() - last >= retry:
                attempts["first_aid_probe"] = time.time()
                self.save_persistent_state()
                return "first_aid_probe", first_aid

        # If the next enemy hit is not survivable, only a verified bonus action is
        # permitted. Never gamble with a turn-consuming heal at lethal HP.
        if hp <= bound + emergency:
            return "unsafe", None

        boss_or_unknown = self.is_boss(candidate.monster) or as_int(profile.get("samples"), 0) == 0
        defensive_id = as_int(cfg.get("defensive_stance_skill_id", 3), 3)
        defensive = self.skill_by_id(state, defensive_id)
        if (
            cfg.get("defensive_stance_unknown_or_boss", True)
            and boss_or_unknown
            and not self.has_defense_buff(raw_data)
            and self.skill_usable(defensive, mp)
        ):
            return "defensive_stance", defensive

        life_id = as_int(cfg.get("life_drain_skill_id", 19), 19)
        life = self.skill_by_id(state, life_id)
        if (
            missing_ratio >= as_float(cfg.get("life_drain_missing_ratio", 0.10), 0.10)
            and self.skill_usable(life, mp)
        ):
            return "life_drain", life

        heal_id = as_int(cfg.get("healing_skill_id", 10), 10)
        heal = self.skill_by_id(state, heal_id)
        if (
            missing_ratio >= as_float(cfg.get("healing_missing_ratio", 0.20), 0.20)
            and self.skill_usable(heal, mp)
        ):
            return "healing", heal

        mana_id = as_int(cfg.get("mana_font_skill_id", 60), 60)
        mana = self.skill_by_id(state, mana_id)
        if mp / mp_max <= as_float(cfg.get("mana_font_mp_ratio", 0.28), 0.28) and self.skill_usable(mana, mp):
            return "mana_font", mana

        order = [
            as_int(value, 0)
            for value in cfg.get("damage_skill_order", [28, 13, 1, 2, 7])
            if as_int(value, 0) > 0
        ]
        for skill_id in order:
            skill = self.skill_by_id(state, skill_id)
            if self.skill_usable(skill, mp):
                return "damage_skill", skill
        return "basic", None

    def save_pending_session(self, session_id: str, candidate, current_data: Any, started_at: float) -> None:
        state = v36.combat_state(current_data)
        player_node = v36._context_dict(current_data, {"player", "character", "hero", "self"})
        state["log"] = _logs(current_data)
        state["player_buffs"] = (
            list(player_node.get("buffs", []))
            if isinstance(player_node, dict) and isinstance(player_node.get("buffs"), list)
            else []
        )
        profile = self.dynamic_turn_profile(
            candidate,
            hp_max=max(1, as_int(state.get("player_hp_max"), 1)),
            enemy_hp=as_int(state.get("enemy_hp"), 0),
            enemy_hp_max=as_int(state.get("enemy_hp_max"), 0),
            total_estimate=as_float(candidate.predicted_damage, 1.0),
        )
        self.persistent_state["pending"] = {
            "session_id": str(session_id),
            "monster_id": as_int(candidate.monster.get("id"), 0),
            "monster_name": self.monster_name(candidate),
            "started_at": started_at,
            "updated_at": time.time(),
            "state": state,
            "turn_profile": profile,
        }
        self.save_persistent_state()

    def pause_open_session(self, session_id: str, candidate, current_data: Any, started_at: float, current_hp: int, target_hp: int) -> int:
        # Live test V2 proved that character/me regeneration did not enter the open
        # combat snapshot: 368 HP, 60s wait, exact 18 monster hit, final 350 HP.
        # Therefore V3.7 never fabricates session HP from public regeneration.
        self.save_pending_session(session_id, candidate, current_data, started_at)
        self.logger.info(
            "[COMBAT HOLD] %s | session HP %s | safe action target %s | "
            "natural HP regeneration is not assumed inside an open session.",
            self.monster_name(candidate),
            current_hp,
            target_hp,
        )
        return current_hp

    def interactive_combat(self, candidate):
        cfg = self.persistent_cfg()
        sustain = self.sustain_cfg()
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
                    "buffs": saved_state.get("player_buffs", []),
                },
                "monster": {
                    "hp": saved_state.get("enemy_hp"),
                    "hp_max": saved_state.get("enemy_hp_max"),
                },
                "skills": saved_state.get("skills", []),
                "log": saved_state.get("log", []),
            }
            self.persistent_state["sessions_resumed"] = as_int(
                self.persistent_state.get("sessions_resumed"), 0
            ) + 1
            self.logger.info("[COMBAT RESUME] Reusing saved session for %s.", self.monster_name(candidate))
        else:
            start = self.client.post(f"world/combat/start/{candidate.monster['id']}", {})
            if not start.ok:
                return start
            session_id = v36.session_id_from_response(start.data)
            if session_id is None:
                return engine.APIResult(False, 200, start.data, "session_id_missing")
            current_data = start.data
            started_at = time.time()
            self.persistent_state["combat_sessions_started"] = as_int(
                self.persistent_state.get("combat_sessions_started"), 0
            ) + 1
            self.save_pending_session(session_id, candidate, current_data, started_at)
            self.logger.info("[COMBAT START] Sustain session opened for %s.", self.monster_name(candidate))

        monster_id = as_int(candidate.monster.get("id"), 0)
        maximum_actions = max(1, as_int(cfg.get("maximum_session_turns", 240), 240))
        actions = 0

        while actions < maximum_actions:
            state = v36.combat_state(current_data)
            if state["finished"]:
                self.clear_pending_session()
                result_text = normalize(state.get("result"))
                victory = result_text in {"victory", "won", "win", "completed", "finished"}
                return engine.APIResult(victory, 200, current_data, None if victory else (result_text or "combat_finished"))

            hp = as_int(state.get("player_hp"), 0)
            hp_max = max(1, as_int(state.get("player_hp_max"), hp))
            profile = self.dynamic_turn_profile(
                candidate,
                hp_max=hp_max,
                enemy_hp=as_int(state.get("enemy_hp"), 0),
                enemy_hp_max=as_int(state.get("enemy_hp_max"), 0),
                total_estimate=as_float(candidate.predicted_damage, 1.0),
            )
            action_kind, skill = self.choose_sustain_action(candidate, current_data, state, profile)

            if action_kind == "unsafe":
                self.save_pending_session(session_id, candidate, current_data, started_at)
                self.logger.info(
                    "[COMBAT HOLD] %s | HP %s/%s | next-hit bound %s | reserve %s | "
                    "no verified safe sustain action is ready; session preserved.",
                    self.monster_name(candidate), hp, hp_max,
                    profile["bound"], profile["reserve"],
                )
                return engine.APIResult(False, 200, current_data, "sustain_action_unavailable")

            previous_data = current_data
            previous_state = state
            utility = action_kind in {
                "first_aid", "first_aid_probe", "defensive_stance", "life_drain", "healing", "mana_font"
            }
            action = self.send_combat_action(session_id, skill=skill)
            if action is None:
                self.save_pending_session(session_id, candidate, current_data, started_at)
                return engine.APIResult(False, 422, current_data, "combat_action_schema_unknown")

            if not action.ok:
                # Utility rejection is never converted into an attack. That old
                # behavior could kill a low-HP hero.
                if utility:
                    self.persistent_state.setdefault("utility_failures", {})[action_kind] = {
                        "at": time.time(), "status": action.status, "error": action.error
                    }
                    self.save_pending_session(session_id, candidate, current_data, started_at)
                    self.save_persistent_state()
                    return engine.APIResult(False, action.status, current_data, f"{action_kind}_rejected:{action.error}")

                if skill is not None and action.status in {400, 405, 422}:
                    # Damage skill rejection may fall back to one basic attack only
                    # because the pre-action HP gate already proved one hit safe.
                    action = self.send_combat_action(session_id, skill=None)
                if action is None or not action.ok:
                    if action is not None and action.status in {404, 409, 410}:
                        self.clear_pending_session()
                    else:
                        self.save_pending_session(session_id, candidate, current_data, started_at)
                    return action or engine.APIResult(False, 422, current_data, "combat_action_failed")

            current_data = action.data
            next_state = v36.combat_state(current_data)
            exact_damage = exact_monster_damage(previous_data, current_data)
            if exact_damage <= 0:
                # Fallback only when the response log omitted the actual hit.
                exact_damage = max(
                    0,
                    as_int(previous_state.get("player_hp"), 0)
                    - as_int(next_state.get("player_hp"), as_int(previous_state.get("player_hp"), 0)),
                )
            phase = phase_bucket(
                as_int(previous_state.get("enemy_hp"), 0),
                as_int(previous_state.get("enemy_hp_max"), 0),
            )
            if exact_damage > 0:
                self.record_turn_sample(
                    monster_id,
                    exact_damage,
                    phase=phase,
                    turn=as_int(next_state.get("turn"), actions + 1),
                    action=action_kind,
                    boss=self.is_boss(candidate.monster),
                )

            heal = exact_player_heal(previous_data, current_data)
            if heal <= 0 and utility:
                # Derive healing from the exact enemy hit and HP delta.
                heal = max(
                    0,
                    as_int(next_state.get("player_hp"), 0)
                    + exact_damage
                    - as_int(previous_state.get("player_hp"), 0),
                )

            if action_kind in {"first_aid", "first_aid_probe"}:
                same_turn = as_int(next_state.get("turn"), -1) == as_int(previous_state.get("turn"), -2)
                if same_turn and exact_damage == 0 and as_int(next_state.get("player_hp"), 0) >= as_int(previous_state.get("player_hp"), 0):
                    self.mark_utility_verified("first_aid_bonus", True)

            actions += 1
            self.logger.info(
                "[COMBAT ACTION] %s | turn %s | %s | HP %s/%s | enemy %s/%s | "
                "enemy hit %s | healed %s | next bound %s + reserve %s | %s.",
                self.monster_name(candidate),
                next_state.get("turn") or actions,
                action_kind if skill is None else f"{action_kind} skill {self.skill_id(skill)}",
                next_state.get("player_hp"), next_state.get("player_hp_max"),
                next_state.get("enemy_hp"), next_state.get("enemy_hp_max"),
                exact_damage, heal, profile["bound"], profile["reserve"], profile["confidence"],
            )
            self.save_pending_session(session_id, candidate, current_data, started_at)
            time.sleep(as_float(self.config.get("automation", {}).get("action_delay_seconds", 1.0), 1.0))

        self.save_pending_session(session_id, candidate, current_data, started_at)
        return engine.APIResult(False, 408, current_data, "maximum_session_actions_reached")


def startup_check() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eldoria_v37_startup_check")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(sys.stdout))
    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
        client = engine.APIClient(config, logger)
        bot = SustainCombatDirector(client, config, logger)
        if v36.session_id_from_response(
            {"id": "abc123", "turn": 1, "monster": {}, "player": {}, "finished": False}
        ) != "abc123":
            raise RuntimeError("Alphanumeric combat session parser failed.")
        print(f"[STARTUP CHECK OK] {SustainCombatDirector.VERSION}")
        print("[STARTUP CHECK OK] APIClient, full Director, sustain policy and session parser constructed.")
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
    return v36.live_read_check()


def main() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        print(f"Configuration file is missing: {CONFIG_FILE}")
        return 2

    if "--startup-check" in sys.argv:
        return startup_check()
    if "--live-read-check" in sys.argv:
        return live_read_check()

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
        logger.info("[START] Eldoria Bot %s", SustainCombatDirector.VERSION)
        logger.info(
            "[MODE] LEVELING_FIRST + exact-hit sustain combat: dynamic near-death gate, "
            "First Aid, Life Drain, Healing, Defense and Mana management."
        )
        logger.info(
            "[SAFETY] Open-session natural regeneration is NOT assumed; actions stop before "
            "the learned next-hit bound."
        )
        client = engine.APIClient(config, logger)
        bot = SustainCombatDirector(client, config, logger)
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
    raise SystemExit(main())
