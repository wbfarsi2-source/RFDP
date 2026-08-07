from __future__ import annotations

import importlib.util
import logging
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
V37_FILE = SCRIPT_DIR / "eldoria_bot_v3_7_sustain_combat_windows.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_8_fast_quest_combat_config.json"

if not V37_FILE.exists():
    raise RuntimeError(f"Required V3.7 file is missing: {V37_FILE}")

spec = importlib.util.spec_from_file_location("eldoria_v37_runtime", V37_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("The V3.7 module could not be loaded.")
v37 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v37
spec.loader.exec_module(v37)

v36 = v37.v36
v35 = v37.v35
v34 = v37.v34
engine = v37.engine
base = v37.base
v27 = v37.v27

ELDORIA_ROOT = v37.ELDORIA_ROOT
PRIVATE_DIR = v37.PRIVATE_DIR
OUTPUT_DIR = v37.OUTPUT_DIR
PROJECT_DIR = v37.PROJECT_DIR
STATE_DIR = v37.STATE_DIR
LOG_DIR = v37.LOG_DIR
CURRENT_PLAN_FILE = v37.CURRENT_PLAN_FILE
INSTANCE_LOCK_FILE = v37.INSTANCE_LOCK_FILE

for module in [v37, v36, v35, v34, *v34.ALL_MODULES]:
    try:
        module.CONFIG_FILE = CONFIG_FILE
    except Exception:
        pass


def as_int(value: Any, default: int = 0) -> int:
    return v37.as_int(value, default)


def as_float(value: Any, default: float = 0.0) -> float:
    return v37.as_float(value, default)


def normalize(value: Any) -> str:
    return v37.normalize(value)


def deep_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    return v37.deep_defaults(target, defaults)


def prepare_config(config: dict[str, Any]) -> dict[str, Any]:
    config = v37.prepare_config(config)
    deep_defaults(
        config,
        {
            "fast_quest_combat": {
                "enabled": True,
                "routine_normal_fight": True,
                "normal_damage_margin": 1.08,
                "normal_minimum_post_hp": 15,
                "normal_max_damage_ratio": 0.72,
                "persistent_for_bosses": True,
                "persistent_when_normal_blocked": True,
                "pending_hold_retry_seconds": 600,
                "hold_log_heartbeat_seconds": 600,
                "hydrate_missing_combat_skills": True,
                "confirmed_live_turn_samples": {
                    "88": [17, 18]
                },
                "confirmed_sample_label": "live-v2-20260802",
                "unknown_effective_attack_margin": 1.50,
                "unknown_effective_attack_flat": 8,
                "unknown_total_fraction": 0.12,
                "unknown_boss_margin": 1.90,
                "unknown_boss_flat": 14,
                "unsupported_utility_retry_turns": 999,
                "clear_legacy_pending_label": "v3.8.1-clear-stale-session",
                "routine_assessment_margin": 1.04,
                "routine_assessment_flat_buffer": 4,
                "routine_minimum_post_hp": 12,
                "exclude_held_targets_from_selection": True,
                "held_target_selection_notice_seconds": 600,
            },
            "persistent_combat": {
                "enabled": True,
                "priority_max": 0,
                "boss_enabled": True,
                "maximum_session_age_seconds": 43200,
                "maximum_session_turns": 240,
                "target_audit_heartbeat_seconds": 1800,
                "natural_regeneration_inside_session": False,
            },
            "server_friendly_pacing": {
                "enabled": True,
                "minimum_request_interval_seconds": 2.5,
                "combat_turn_interval_seconds": 4.5,
                "dungeon_action_interval_seconds": 8.0,
                "dungeon_max_actions_per_cycle": 3,
                "schema_probe_interval_seconds": 2.5,
                "maximum_schema_probes_per_action": 3,
                "maximum_rejected_skills_per_turn": 2,
                "rejected_skill_cooldown_turns": 4,
                "read_backoff_initial_seconds": 8.0,
                "read_backoff_multiplier": 2.0,
                "read_backoff_cap_seconds": 60.0,
                "circuit_breaker_failures": 4,
                "circuit_breaker_seconds": 120,
                "retryable_statuses": [429, 500, 502, 503, 504],
            },
        },
    )
    # Routine quest targets must not all be forced into slow interactive combat.
    config.setdefault("persistent_combat", {})["priority_max"] = 0
    config.setdefault("persistent_combat", {})[
        "natural_regeneration_inside_session"
    ] = False
    config.setdefault("quest_campaign", {})[
        "sticky_until_objective_complete"
    ] = False
    config.setdefault("quest_campaign", {})[
        "prefer_strongest_safe_enemy"
    ] = True
    config.setdefault("smart_combat", {})["xp_weight"] = max(
        8.0, as_float(config.get("smart_combat", {}).get("xp_weight"), 8.0)
    )
    config.setdefault("smart_combat", {})["gold_weight"] = max(
        3.0, as_float(config.get("smart_combat", {}).get("gold_weight"), 3.0)
    )
    return config


class FastQuestCombatDirector(v37.SustainCombatDirector):
    VERSION = "3.8.3-server-friendly-pacing-windows"

    def __init__(self, client, config, logger) -> None:
        self._force_persistent_monster_id: int | None = None
        self._session_rejected_skill_ids: set[int] = set()
        self._session_skill_retry_after_turn: dict[int, int] = {}
        super().__init__(client, config, logger)
        self.persistent_state.setdefault("v38_migrations", {})
        self.persistent_state.setdefault("hold_until", 0.0)
        self.persistent_state.setdefault("hold_monster_id", 0)
        self.persistent_state.setdefault("last_hold_notice_at", 0.0)
        self.clear_legacy_pending_once()
        self.apply_confirmed_live_samples()
        self.save_persistent_state()

    def fast_cfg(self) -> dict[str, Any]:
        row = self.config.get("fast_quest_combat", {})
        return row if isinstance(row, dict) else {}

    def pacing_cfg(self) -> dict[str, Any]:
        row = self.config.get("server_friendly_pacing", {})
        return row if isinstance(row, dict) else {}

    def continue_dungeon(self, run_id: int) -> None:
        """Advance a bounded number of dungeon states without request bursts."""
        cfg = self.pacing_cfg()
        if not cfg.get("enabled", True):
            return super().continue_dungeon(run_id)

        dungeons = self.config.setdefault("dungeons", {})
        automation = self.config.setdefault("automation", {})
        old_limit = dungeons.get("max_actions_per_cycle", 40)
        old_delay = automation.get("action_delay_seconds", 1.0)
        dungeons["max_actions_per_cycle"] = max(
            1,
            min(
                as_int(old_limit, 40),
                as_int(cfg.get("dungeon_max_actions_per_cycle", 3), 3),
            ),
        )
        automation["action_delay_seconds"] = max(
            as_float(old_delay, 1.0),
            as_float(cfg.get("dungeon_action_interval_seconds", 8.0), 8.0),
        )
        try:
            return super().continue_dungeon(run_id)
        finally:
            dungeons["max_actions_per_cycle"] = old_limit
            automation["action_delay_seconds"] = old_delay

    def clear_legacy_pending_once(self) -> None:
        """Drop only the stale pre-hotfix local session marker once.

        V3.7/V3.8 could preserve a low-HP session indefinitely while the public
        character had already regenerated.  Keeping that marker forces every
        scheduler cycle back into the dead session.  The live server is not
        contacted here; this only clears the local resume pointer and hold timer.
        """
        if os.environ.get("ELDORIA_VERIFY_ONLY") == "1":
            return
        cfg = self.fast_cfg()
        label = str(cfg.get("clear_legacy_pending_label") or "v3.8.1-clear-stale-session")
        migrations = self.persistent_state.setdefault("v38_migrations", {})
        if migrations.get("pending_clear_label") == label:
            return
        pending = self.persistent_state.get("pending")
        if isinstance(pending, dict) and pending.get("session_id"):
            self.persistent_state["pending"] = None
            self.persistent_state["hold_until"] = 0.0
            self.persistent_state["hold_monster_id"] = 0
            self.persistent_state["last_hold_notice_at"] = 0.0
            self.logger.info(
                "[HOTFIX] Cleared one stale local combat-resume marker from an older build."
            )
        migrations["pending_clear_label"] = label
        migrations["pending_cleared_at"] = time.time()

    def apply_confirmed_live_samples(self) -> None:
        cfg = self.fast_cfg()
        label = str(cfg.get("confirmed_sample_label") or "confirmed-live")
        migrations = self.persistent_state.setdefault("v38_migrations", {})
        if migrations.get("confirmed_sample_label") == label:
            return

        mapping = cfg.get("confirmed_live_turn_samples", {})
        if not isinstance(mapping, dict):
            mapping = {}
        detailed = self.persistent_state.setdefault("turn_samples", {})
        legacy = self.persistent_state.setdefault("turn_damage", {})

        for monster_key, values in mapping.items():
            monster_id = as_int(monster_key, 0)
            if monster_id <= 0 or not isinstance(values, list):
                continue
            rows = detailed.setdefault(str(monster_id), [])
            simple = legacy.setdefault(str(monster_id), [])
            if not isinstance(rows, list):
                rows = []
                detailed[str(monster_id)] = rows
            if not isinstance(simple, list):
                simple = []
                legacy[str(monster_id)] = simple
            if any(row.get("source") == label for row in rows if isinstance(row, dict)):
                continue
            for index, raw in enumerate(values, start=1):
                damage = as_int(raw, 0)
                if damage <= 0:
                    continue
                rows.append(
                    {
                        "damage": damage,
                        "phase": "unknown",
                        "turn": index,
                        "action": "confirmed-live-basic",
                        "boss": False,
                        "source": label,
                        "at": time.time(),
                    }
                )
                simple.append(damage)
            del rows[:-40]
            del simple[:-40]

        migrations["confirmed_sample_label"] = label
        migrations["confirmed_samples_applied_at"] = time.time()

    def detailed_samples(self, monster_id: int) -> list[dict[str, Any]]:
        rows = super().detailed_samples(monster_id)
        if rows:
            return rows
        # V3.7 ignored the legacy exact per-turn samples. Recover them so old
        # pending sessions are not evaluated with an inflated prediction-only bound.
        mapping = self.persistent_state.get("turn_damage", {})
        values = mapping.get(str(monster_id), []) if isinstance(mapping, dict) else []
        return [
            {
                "damage": as_int(value, 0),
                "phase": "unknown",
                "turn": index,
                "action": "legacy-turn-sample",
                "boss": False,
                "source": "legacy-turn-damage",
            }
            for index, value in enumerate(values, start=1)
            if as_int(value, 0) > 0
        ]

    def _character_defense_values(self) -> tuple[float, float]:
        character = getattr(self, "_scheduler_character", {})
        if not isinstance(character, dict):
            character = {}
        derived = character.get("derived") if isinstance(character.get("derived"), dict) else {}
        defense = max(
            as_float(character.get("defense"), 0.0),
            as_float(derived.get("defense"), 0.0),
        )
        resistance = max(
            as_float(character.get("resistance"), 0.0),
            as_float(character.get("magic_defense"), 0.0),
            as_float(derived.get("resistance"), 0.0),
            as_float(derived.get("magic_defense"), 0.0),
        )
        return defense, resistance

    def dynamic_turn_profile(
        self,
        candidate,
        *,
        hp_max: int,
        enemy_hp: int | None = None,
        enemy_hp_max: int | None = None,
        total_estimate: float | None = None,
    ) -> dict[str, Any]:
        profile = super().dynamic_turn_profile(
            candidate,
            hp_max=hp_max,
            enemy_hp=enemy_hp,
            enemy_hp_max=enemy_hp_max,
            total_estimate=total_estimate,
        )
        if as_int(profile.get("samples"), 0) > 0:
            return profile

        cfg = self.fast_cfg()
        defense, resistance = self._character_defense_values()
        attack = max(0.0, as_float(candidate.monster.get("attack"), 0.0))
        magic_attack = max(0.0, as_float(candidate.monster.get("m_atk"), 0.0))
        physical = max(1.0, attack - defense)
        magical = max(1.0, magic_attack - resistance) if magic_attack > 0 else 1.0
        estimate_fraction = max(0.0, as_float(total_estimate, 0.0)) * as_float(
            cfg.get("unknown_total_fraction", 0.12), 0.12
        )
        raw = max(physical, magical, estimate_fraction, 1.0)
        boss = self.is_boss(candidate.monster)
        if boss:
            margin = as_float(cfg.get("unknown_boss_margin", 1.90), 1.90)
            flat = as_float(cfg.get("unknown_boss_flat", 14), 14)
            reserve = max(14, math.ceil(hp_max * 0.04))
            confidence = "defense-adjusted-unknown-boss"
        else:
            margin = as_float(cfg.get("unknown_effective_attack_margin", 1.50), 1.50)
            flat = as_float(cfg.get("unknown_effective_attack_flat", 8), 8)
            reserve = max(8, math.ceil(hp_max * 0.02))
            confidence = "defense-adjusted-unknown"
        bound = max(1, math.ceil(raw * margin + flat))
        emergency = max(1, as_int(self.sustain_cfg().get("absolute_emergency_hp", 3), 3))
        required = min(hp_max + 1, bound + max(reserve, emergency))
        profile.update(
            {
                "bound": bound,
                "reserve": max(reserve, emergency),
                "required_hp": required,
                "confidence": confidence,
                "effective_physical": round(physical, 3),
                "effective_magical": round(magical, 3),
            }
        )
        return profile

    def _pending_matches(self, candidate) -> bool:
        pending = self.persistent_state.get("pending")
        return (
            isinstance(pending, dict)
            and as_int(pending.get("monster_id"), 0)
            == as_int(candidate.monster.get("id"), 0)
            and bool(pending.get("session_id"))
        )

    def active_hold_monster(self) -> tuple[int, float]:
        """Return the currently held monster and remaining seconds.

        An expired hold is cleared without deleting the pending combat session,
        allowing the same session to be selected and resumed normally afterward.
        """
        monster_id = as_int(self.persistent_state.get("hold_monster_id"), 0)
        hold_until = as_float(self.persistent_state.get("hold_until"), 0.0)
        now = time.time()
        if monster_id <= 0 or hold_until <= now:
            if monster_id > 0 or hold_until > 0:
                self._clear_hold()
                self.save_persistent_state()
            return 0, 0.0
        return monster_id, max(0.0, hold_until - now)

    def select_target_row(self, objective, rows):
        """Exclude a combat-held monster before the scheduler logs travel/action.

        V3.8.1 correctly deferred the combat action itself, but the Quest target
        selector kept returning the same held monster every few seconds.  That
        caused a tight TRAVEL/ACTION loop even though no combat POST was sent.
        Filtering here lets another legal Quest/XP/Gold target win immediately.
        """
        row_list = list(rows or [])
        cfg = self.fast_cfg()
        held_id, remaining = self.active_hold_monster()
        if (
            held_id > 0
            and cfg.get("exclude_held_targets_from_selection", True)
            and row_list
        ):
            held_rows = [
                row
                for row in row_list
                if as_int(row.get("candidate").monster.get("id"), 0) == held_id
                and row.get("candidate") is not None
            ]
            filtered = [
                row
                for row in row_list
                if not (
                    row.get("candidate") is not None
                    and as_int(row.get("candidate").monster.get("id"), 0) == held_id
                )
            ]
            if held_rows:
                held_name = self.monster_name(held_rows[0]["candidate"])
                if not filtered:
                    self._target_audit_message = (
                        f"{held_name} is in combat hold for "
                        f"{v27.format_duration(int(remaining))}; no alternate legal "
                        f"target exists for this objective, so other tasks will be evaluated."
                    )
                    self._target_audit_signature = "|".join(
                        [
                            self.objective_key(objective),
                            "combat-hold-only",
                            str(held_id),
                            str(int(remaining // 60)),
                        ]
                    )
                    return None

                selected = super().select_target_row(objective, filtered)
                if selected is not None:
                    base_message = str(
                        getattr(self, "_target_audit_message", "") or ""
                    ).strip()
                    suffix = (
                        f"{held_name} skipped for "
                        f"{v27.format_duration(int(remaining))} because its combat "
                        f"session is waiting for a safe retry."
                    )
                    self._target_audit_message = (
                        f"{base_message} {suffix}".strip()
                        if base_message
                        else suffix
                    )
                    self._target_audit_signature = "|".join(
                        [
                            str(getattr(self, "_target_audit_signature", "") or self.objective_key(objective)),
                            "held-skip",
                            str(held_id),
                            str(as_int(selected["candidate"].monster.get("id"), 0)),
                        ]
                    )
                return selected

        return super().select_target_row(objective, row_list)

    def persistent_candidate(self, candidate) -> bool:
        if not self.persistent_cfg().get("enabled", True):
            return False
        monster_id = as_int(candidate.monster.get("id"), 0)
        if self._pending_matches(candidate):
            return True
        if self._force_persistent_monster_id == monster_id and monster_id > 0:
            return True
        if self.is_boss(candidate.monster):
            return bool(self.fast_cfg().get("persistent_for_bosses", True))
        return False

    def combat_assessment(self, candidate, character: dict[str, Any]) -> dict[str, Any]:
        """Route routine targets with an immediate-fight floor, otherwise one-turn sustain.

        The inherited no-death gate was designed around a full-fight recovery
        model and could turn a currently survivable second Quest kill into hours
        of waiting.  For non-boss routine monsters we use the calibrated full
        damage plus a small post-fight floor.  If that full fight no longer fits,
        the same target is assessed as a turn-based sustain fight instead of being
        discarded.
        """
        base_row = super().combat_assessment(candidate, character)
        if self.is_boss(candidate.monster) or self._pending_matches(candidate):
            return base_row

        # Respect an explicit death lock from the existing safety system.
        if base_row.get("no_death_reason") == "death-lock":
            return base_row

        hp = max(0, as_int(character.get("hp"), 0))
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        stamina = max(0, as_int(character.get("stamina"), 0))
        stamina_cost = max(1, as_int(candidate.monster.get("stamina_cost"), 1))
        estimate = max(1.0, as_float(base_row.get("estimate"), candidate.predicted_damage))
        cfg = self.fast_cfg()

        full_margin = max(1.0, as_float(cfg.get("routine_assessment_margin", 1.04), 1.04))
        full_flat = max(0, as_int(cfg.get("routine_assessment_flat_buffer", 4), 4))
        post_floor = max(
            as_int(cfg.get("routine_minimum_post_hp", 12), 12),
            as_int(cfg.get("normal_minimum_post_hp", 15), 15),
        )
        full_required = math.ceil(estimate * full_margin + full_flat + post_floor)
        ratio_cap = max(0.1, as_float(cfg.get("normal_max_damage_ratio", 0.72), 0.72))
        full_fight_fits = (
            estimate * full_margin <= hp_max * ratio_cap
            and full_required <= hp_max
        )

        if full_fight_fits and hp >= full_required:
            if stamina < stamina_cost:
                state = "resource"
                reason = "waiting for routine-fight stamina"
            else:
                state = "ready"
                reason = "ready for fast normal Quest combat"
            updated = dict(base_row)
            updated.update(
                {
                    "state": state,
                    "reason": reason,
                    "required_hp": full_required,
                    "stamina_target": stamina_cost,
                    "hp_short": 0,
                    "stamina_short": max(0, stamina_cost - stamina),
                    "actionable": state == "ready",
                    "minimum_post_hp": post_floor,
                    "estimate": estimate,
                    "risk_ratio": estimate / hp_max,
                    "no_death_blocked": False,
                    "no_death_reason": None,
                    "persistent_combat": False,
                    "confidence": "fast-routine-calibrated",
                }
            )
            return updated

        # The full resolved fight either does not fit at all or does not fit the
        # current HP.  Before waiting, test whether one turn is safe and route
        # directly to sustain combat.

        # The total fight is not safe in one resolved request.  Do not create a
        # multi-hour wait if a single learned turn is safe; route it to sustain.
        profile = self.dynamic_turn_profile(
            candidate,
            hp_max=hp_max,
            enemy_hp=as_int(candidate.monster.get("hp") or candidate.monster.get("hp_max"), 0),
            enemy_hp_max=as_int(candidate.monster.get("hp_max") or candidate.monster.get("hp"), 0),
            total_estimate=estimate,
        )
        turn_required = as_int(profile.get("required_hp"), hp_max + 1)
        if turn_required <= hp_max:
            if hp < turn_required:
                state = "heal"
                reason = "waiting for one safe sustain turn"
            elif stamina < stamina_cost:
                state = "resource"
                reason = "waiting for sustain-combat stamina"
            else:
                state = "ready"
                reason = "ready for sustain fallback"
            updated = dict(base_row)
            updated.update(
                {
                    "state": state,
                    "reason": reason,
                    "required_hp": turn_required,
                    "stamina_target": stamina_cost,
                    "hp_short": max(0, turn_required - hp),
                    "stamina_short": max(0, stamina_cost - stamina),
                    "actionable": state == "ready",
                    "estimate": as_int(profile.get("bound"), 1),
                    "minimum_post_hp": as_int(profile.get("reserve"), 3),
                    "risk_ratio": as_float(profile.get("bound"), 1.0) / hp_max,
                    "no_death_blocked": False,
                    "no_death_reason": None,
                    "persistent_combat": True,
                    "turn_profile": profile,
                    "confidence": f"fast-sustain-{profile.get('confidence')}",
                }
            )
            return updated

        return base_row

    def _normal_fight_safe(self, candidate, character: dict[str, Any]) -> bool:
        cfg = self.fast_cfg()
        if not cfg.get("routine_normal_fight", True):
            return False
        if self.is_boss(candidate.monster) or self._pending_matches(candidate):
            return False
        hp = max(0, as_int(character.get("hp"), 0))
        hp_max = max(1, as_int(character.get("hp_max"), 1))
        assessed = super().combat_assessment(candidate, character)
        estimate = max(1.0, as_float(assessed.get("estimate"), candidate.predicted_damage))
        estimate *= max(1.0, as_float(cfg.get("normal_damage_margin", 1.08), 1.08))
        minimum_post = max(
            as_int(cfg.get("normal_minimum_post_hp", 15), 15),
            as_int(self.config.get("combat", {}).get("minimum_hp_after_battle"), 15),
        )
        ratio_cap = max(0.1, as_float(cfg.get("normal_max_damage_ratio", 0.72), 0.72))
        return estimate <= hp_max * ratio_cap and hp - math.ceil(estimate) >= minimum_post

    def execute_fight(self, candidate) -> bool:
        try:
            character = self.get_character()
        except Exception as exc:
            self.logger.info("[FAST FIGHT] Character verification failed: %s", exc)
            return False
        self._scheduler_character = character

        pending = self._pending_matches(candidate)
        hold_until = as_float(self.persistent_state.get("hold_until"), 0.0)
        hold_monster = as_int(self.persistent_state.get("hold_monster_id"), 0)
        monster_id = as_int(candidate.monster.get("id"), 0)
        if pending and hold_monster == monster_id and time.time() < hold_until:
            now = time.time()
            heartbeat = max(60.0, as_float(self.fast_cfg().get("hold_log_heartbeat_seconds", 600), 600.0))
            last = as_float(self.persistent_state.get("last_hold_notice_at"), 0.0)
            if now - last >= heartbeat:
                self.persistent_state["last_hold_notice_at"] = now
                self.save_persistent_state()
                self.logger.info(
                    "[COMBAT HOLD] %s retry deferred for %s; other Quest/Dungeon tasks may continue.",
                    self.monster_name(candidate),
                    v27.format_duration(max(0, int(hold_until - now))),
                )
            return False

        original_priority = getattr(candidate, "priority", 99)
        self._force_persistent_monster_id = None
        try:
            if self._normal_fight_safe(candidate, character):
                # Priority 2 prevents the old engine from activating MP-interactive
                # mode for a routine monster that is already safe as one normal fight.
                candidate.priority = 2
                self.logger.info(
                    "[FAST FIGHT] %s uses normal resolved combat for faster XP/Gold/Quest progress.",
                    self.monster_name(candidate),
                )
                return v36.PersistentCombatDirector.execute_fight(self, candidate)

            if pending or self.is_boss(candidate.monster) or self.fast_cfg().get(
                "persistent_when_normal_blocked", True
            ):
                self._force_persistent_monster_id = monster_id
                candidate.priority = 0
                self.logger.info(
                    "[SUSTAIN FIGHT] %s uses turn-based combat because normal full-fight safety is not satisfied.",
                    self.monster_name(candidate),
                )
                return v36.PersistentCombatDirector.execute_fight(self, candidate)

            candidate.priority = 2
            return v36.PersistentCombatDirector.execute_fight(self, candidate)
        finally:
            candidate.priority = original_priority
            self._force_persistent_monster_id = None

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
        semantic_markers = {
            "cooldown", "not ready", "insufficient", "mana", "mp",
            "stunned", "silenced", "cannot use", "can't use",
            "unavailable", "already used", "dead", "finished",
        }
        schema_markers = {
            "schema", "format", "field", "payload", "body",
            "unsupported action", "invalid action", "unknown action",
        }
        pacing = self.pacing_cfg()
        indexes = self._action_indexes(key, len(templates))
        max_probes = max(
            1,
            min(
                len(indexes),
                as_int(pacing.get("maximum_schema_probes_per_action", 3), 3),
            ),
        )
        probe_delay = max(
            0.0,
            as_float(pacing.get("schema_probe_interval_seconds", 2.5), 2.5),
        )
        for probe_number, index in enumerate(indexes[:max_probes], start=1):
            result = self.client.post(endpoint, templates[index])
            last = result
            if result.ok:
                self.runtime.setdefault("combat_action_schema", {})[key] = index
                engine.save_json(engine.RUNTIME_STATE_FILE, self.runtime)
                return result
            if result.status is None:
                return result
            error_text = normalize(result.error or engine.recursive_find(result.data, {"error", "message"}) or "")
            if any(marker in error_text for marker in semantic_markers):
                return result
            # Probe another body only for a genuine schema/format rejection.
            if result.status in {404, 405} or any(marker in error_text for marker in schema_markers):
                if probe_number < max_probes and probe_delay > 0:
                    time.sleep(probe_delay)
                continue
            return result
        return last

    def hydrate_missing_skills(self, current_data: dict[str, Any]) -> None:
        if not self.fast_cfg().get("hydrate_missing_combat_skills", True):
            return
        state = v36.combat_state(current_data)
        if state.get("skills"):
            return
        result = self.client.get("skills/mine")
        if not result.ok:
            return
        rows = self.skill_rows(result.data)
        hydrated = []
        for row in rows:
            if not isinstance(row, dict) or normalize(row.get("type")) != "active":
                continue
            item = dict(row)
            item.setdefault("cooldown_remaining", 0)
            item.setdefault("can_use", True)
            item.setdefault("mp_cost", as_int(self.skill_mp_cost(item), 0))
            hydrated.append(item)
        if hydrated:
            current_data["skills"] = hydrated
            self.logger.info(
                "[COMBAT RESUME] Restored %s learned skill definitions for an old saved session.",
                len(hydrated),
            )

    def choose_sustain_action(self, candidate, raw_data, state, profile):
        current_turn = as_int(state.get("turn"), 0)
        self._session_skill_retry_after_turn = {
            skill_id: retry_turn
            for skill_id, retry_turn in self._session_skill_retry_after_turn.items()
            if current_turn < retry_turn
        }
        if not self._session_rejected_skill_ids and not self._session_skill_retry_after_turn:
            return super().choose_sustain_action(candidate, raw_data, state, profile)
        shadow = dict(state)
        shadow_skills = []
        for row in state.get("skills", []):
            if not isinstance(row, dict):
                continue
            item = dict(row)
            skill_id = self.skill_id(item)
            if (
                skill_id in self._session_rejected_skill_ids
                or current_turn < self._session_skill_retry_after_turn.get(skill_id, 0)
            ):
                item["can_use"] = False
            shadow_skills.append(item)
        shadow["skills"] = shadow_skills
        return super().choose_sustain_action(candidate, raw_data, shadow, profile)

    def _clear_hold(self) -> None:
        self.persistent_state["hold_until"] = 0.0
        self.persistent_state["hold_monster_id"] = 0
        self.persistent_state["last_hold_notice_at"] = 0.0

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
                    "buffs": saved_state.get("player_buffs", []),
                },
                "monster": {
                    "hp": saved_state.get("enemy_hp"),
                    "hp_max": saved_state.get("enemy_hp_max"),
                },
                "skills": saved_state.get("skills", []),
                "log": saved_state.get("log", []),
            }
            self.hydrate_missing_skills(current_data)
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

        self._session_rejected_skill_ids.clear()
        self._session_skill_retry_after_turn.clear()
        self._clear_hold()
        monster_id = as_int(candidate.monster.get("id"), 0)
        maximum_actions = max(1, as_int(cfg.get("maximum_session_turns", 240), 240))
        actions = 0
        no_turn_rejections = 0

        while actions < maximum_actions:
            state = v36.combat_state(current_data)
            if state["finished"]:
                self.clear_pending_session()
                self._session_skill_retry_after_turn.clear()
                self._clear_hold()
                self.save_persistent_state()
                result_text = normalize(state.get("result"))
                victory = result_text in {"victory", "won", "win", "completed", "finished"}
                return engine.APIResult(
                    victory,
                    200,
                    current_data,
                    None if victory else (result_text or "combat_finished"),
                )

            hp = as_int(state.get("player_hp"), 0)
            hp_max = max(1, as_int(state.get("player_hp_max"), hp))
            profile = self.dynamic_turn_profile(
                candidate,
                hp_max=hp_max,
                enemy_hp=as_int(state.get("enemy_hp"), 0),
                enemy_hp_max=as_int(state.get("enemy_hp_max"), 0),
                total_estimate=as_float(candidate.predicted_damage, 1.0),
            )
            action_kind, skill = self.choose_sustain_action(
                candidate, current_data, state, profile
            )

            if action_kind == "unsafe":
                retry = max(
                    120,
                    as_int(self.fast_cfg().get("pending_hold_retry_seconds", 600), 600),
                )
                self.persistent_state["hold_until"] = time.time() + retry
                self.persistent_state["hold_monster_id"] = monster_id
                self.save_pending_session(session_id, candidate, current_data, started_at)
                self.save_persistent_state()
                self.logger.info(
                    "[COMBAT HOLD] %s | HP %s/%s | learned next-hit bound %s | reserve %s | retry in %s; session preserved.",
                    self.monster_name(candidate),
                    hp,
                    hp_max,
                    profile["bound"],
                    profile["reserve"],
                    v27.format_duration(retry),
                )
                return engine.APIResult(False, 425, current_data, "persistent_hold")

            previous_data = current_data
            previous_state = state
            utility = action_kind in {
                "first_aid",
                "first_aid_probe",
                "defensive_stance",
                "life_drain",
                "healing",
                "mana_font",
            }
            action = self.send_combat_action(session_id, skill=skill)
            if action is None:
                self.save_pending_session(session_id, candidate, current_data, started_at)
                return engine.APIResult(False, 422, current_data, "combat_action_schema_unknown")

            if not action.ok:
                sid = self.skill_id(skill) if isinstance(skill, dict) else 0
                if utility and action.status in {400, 405, 422} and sid > 0:
                    # A rejected utility does not consume an enemy turn. Exclude it
                    # for this unchanged turn and place it on a short turn-based
                    # cooldown so the same rejected write is not repeated every turn.
                    self._session_rejected_skill_ids.add(sid)
                    cooldown_turns = max(
                        1,
                        as_int(
                            self.pacing_cfg().get("rejected_skill_cooldown_turns", 4),
                            4,
                        ),
                    )
                    self._session_skill_retry_after_turn[sid] = (
                        as_int(previous_state.get("turn"), 0) + cooldown_turns
                    )
                    no_turn_rejections += 1
                    self.logger.info(
                        "[COMBAT SKILL SKIP] %s skill %s rejected (%s); cooling it down for %s turns and selecting another safe action.",
                        action_kind,
                        sid,
                        action.error or action.status,
                        cooldown_turns,
                    )
                    rejection_limit = max(
                        1,
                        as_int(
                            self.pacing_cfg().get("maximum_rejected_skills_per_turn", 2),
                            2,
                        ),
                    )
                    if no_turn_rejections <= rejection_limit:
                        retry_pause = max(
                            0.0,
                            as_float(
                                self.pacing_cfg().get("schema_probe_interval_seconds", 2.5),
                                2.5,
                            ),
                        )
                        if retry_pause > 0:
                            time.sleep(retry_pause)
                        continue
                    self.save_pending_session(session_id, candidate, current_data, started_at)
                    return engine.APIResult(False, action.status, current_data, "utility_schema_exhausted")

                if skill is not None and not utility and action.status in {400, 405, 422}:
                    fallback_pause = max(
                        0.0,
                        as_float(
                            self.pacing_cfg().get("schema_probe_interval_seconds", 2.5),
                            2.5,
                        ),
                    )
                    if fallback_pause > 0:
                        time.sleep(fallback_pause)
                    action = self.send_combat_action(session_id, skill=None)
                if action is None or not action.ok:
                    if action is not None and action.status in {404, 409, 410}:
                        self.clear_pending_session()
                    else:
                        self.save_pending_session(session_id, candidate, current_data, started_at)
                    return action or engine.APIResult(False, 422, current_data, "combat_action_failed")

            current_data = action.data
            next_state = v36.combat_state(current_data)
            exact_damage = v37.exact_monster_damage(previous_data, current_data)
            if exact_damage <= 0:
                exact_damage = max(
                    0,
                    as_int(previous_state.get("player_hp"), 0)
                    - as_int(
                        next_state.get("player_hp"),
                        as_int(previous_state.get("player_hp"), 0),
                    ),
                )
            phase = v37.phase_bucket(
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

            heal = v37.exact_player_heal(previous_data, current_data)
            if heal <= 0 and utility:
                heal = max(
                    0,
                    as_int(next_state.get("player_hp"), 0)
                    + exact_damage
                    - as_int(previous_state.get("player_hp"), 0),
                )

            if action_kind in {"first_aid", "first_aid_probe"}:
                same_turn = as_int(next_state.get("turn"), -1) == as_int(
                    previous_state.get("turn"), -2
                )
                if (
                    same_turn
                    and exact_damage == 0
                    and as_int(next_state.get("player_hp"), 0)
                    >= as_int(previous_state.get("player_hp"), 0)
                ):
                    self.mark_utility_verified("first_aid_bonus", True)

            actions += 1
            no_turn_rejections = 0
            self._session_rejected_skill_ids.clear()
            self._clear_hold()
            self.logger.info(
                "[COMBAT ACTION] %s | turn %s | %s | HP %s/%s | enemy %s/%s | enemy hit %s | healed %s | next bound %s + reserve %s | %s.",
                self.monster_name(candidate),
                next_state.get("turn") or actions,
                action_kind if skill is None else f"{action_kind} skill {self.skill_id(skill)}",
                next_state.get("player_hp"),
                next_state.get("player_hp_max"),
                next_state.get("enemy_hp"),
                next_state.get("enemy_hp_max"),
                exact_damage,
                heal,
                profile["bound"],
                profile["reserve"],
                profile["confidence"],
            )
            self.save_pending_session(session_id, candidate, current_data, started_at)
            time.sleep(
                max(
                    as_float(
                        self.config.get("automation", {}).get("action_delay_seconds", 1.0),
                        1.0,
                    ),
                    as_float(
                        self.pacing_cfg().get("combat_turn_interval_seconds", 4.5),
                        4.5,
                    ),
                )
            )

        self.save_pending_session(session_id, candidate, current_data, started_at)
        return engine.APIResult(False, 408, current_data, "maximum_session_actions_reached")


def startup_check() -> int:
    for directory in (ELDORIA_ROOT, PRIVATE_DIR, OUTPUT_DIR, PROJECT_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eldoria_v38_startup_check")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(sys.stdout))
    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
        client = engine.APIClient(config, logger)
        bot = FastQuestCombatDirector(client, config, logger)
        if v36.session_id_from_response(
            {"id": "abc123", "turn": 1, "monster": {}, "player": {}, "finished": False}
        ) != "abc123":
            raise RuntimeError("Alphanumeric combat session parser failed.")
        print(f"[STARTUP CHECK OK] {FastQuestCombatDirector.VERSION}")
        print("[STARTUP CHECK OK] APIClient, Director, fast normal-fight router and sustain fallback constructed.")
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
    return v37.live_read_check()


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
        logger.info("[START] Eldoria Bot %s", FastQuestCombatDirector.VERSION)
        account_name = os.environ.get("ELDORIA_ACCOUNT_NAME", "").strip() or ELDORIA_ROOT.name
        logger.info("[ACCOUNT] %s | isolated runtime=%s", account_name, ELDORIA_ROOT)
        logger.info(
            "[MODE] FAST QUEST/XP/GOLD HOLD ROUTER: routine kills chain immediately; held combat targets are skipped until their retry time."
        )
        logger.info(
            "[FIX] Combat-hold targets are excluded before travel/action selection, preventing retry spam while alternate Quest/XP/Gold work continues."
        )
        client = engine.APIClient(config, logger)
        bot = FastQuestCombatDirector(client, config, logger)
        bot.run()
        return 0
    except KeyboardInterrupt:
        logger.info("[STOP] Interrupted by user; current state was preserved.")
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
