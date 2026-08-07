from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_FILE = SCRIPT_DIR / "eldoria_bot_v1_5_base.py"
ENGINE_FILE = SCRIPT_DIR / "eldoria_bot_engine_v1_5.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v1_6_1_config.json"

DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV1_6_1"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

for required in (BASE_FILE, ENGINE_FILE):
    if not required.exists():
        raise RuntimeError(f"Required file is missing: {required}")

spec = importlib.util.spec_from_file_location(
    "eldoria_base_v1_5",
    BASE_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria base module could not be loaded.")

base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)
engine = base.engine

for module in (base, engine):
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
    module.LAST_REPORT_FILE = OUTPUT_DIR / "eldoria_bot_v1_6_1_last_report.json"
    module.LOG_COPY_FILE = OUTPUT_DIR / "eldoria_bot_v1_6_1.log"

base.STATE_DIR = STATE_DIR
base.OUTPUT_DIR = OUTPUT_DIR
base.LOG_DIR = LOG_DIR
base.CONFIG_FILE = CONFIG_FILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_number(value: Any, names: set[str]) -> int | None:
    number = engine.deep_find_number(value, names)
    if number is None:
        return None
    return int(number)


def configure_quiet_logging():
    import logging

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v1_6_1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    for target in (
        LOG_DIR / "eldoria_bot_v1_6_1.log",
        OUTPUT_DIR / "eldoria_bot_v1_6_1.log",
    ):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


class FinalEldoriaBot(base.AdvancedEldoriaBot):
    VERSION = "1.6.1-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.final_state_file = STATE_DIR / "final_runtime_state.json"
        self.final_state = engine.load_json(
            self.final_state_file,
            {
                "danger_blocks": {},
                "interactive": {
                    "basic_schema": None,
                    "skill_schema": None,
                    "unavailable_until": 0,
                    "last_debug_at": 0,
                },
                "death": {
                    "last_detected_at": 0,
                    "respawns": 0,
                },
            },
        )

        self.respawns_completed = 0
        self.dangerous_targets_blocked = 0
        self.interactive_victories = 0
        self.interactive_schema_file = (
            OUTPUT_DIR / "eldoria_combat_schema_debug.json"
        )

    def save_final_state(self) -> None:
        engine.save_json(self.final_state_file, self.final_state)

    @staticmethod
    def is_alive(character: dict[str, Any]) -> bool:
        return (
            str(character.get("status", "")).lower() == "alive"
            and as_int(character.get("hp")) > 0
        )

    def server_respawn_wait(self, payload: Any) -> int | None:
        seconds = first_number(
            payload,
            {
                "respawn_in",
                "respawn_in_seconds",
                "cooldown_remaining",
                "cooldown_seconds",
                "remaining_seconds",
                "retry_after",
            },
        )

        if seconds is not None and 0 < seconds <= 3600:
            return seconds

        text = text_blob(payload)
        if any(word in text for word in ("cooldown", "wait", "remaining")):
            numbers = [
                int(value)
                for value in re.findall(r"\b(\d{1,4})\b", text)
            ]
            valid = [value for value in numbers if 0 < value <= 3600]
            if valid:
                return min(valid)

        return None

    def ensure_alive(self) -> dict[str, Any]:
        character = self.get_character()

        if self.is_alive(character):
            return character

        death_state = self.final_state.setdefault("death", {})
        detected_at = as_float(death_state.get("last_detected_at"), 0)
        now = time.time()

        if detected_at <= 0 or now - detected_at > 3600:
            detected_at = now
            death_state["last_detected_at"] = detected_at
            self.save_final_state()
            self.logger.info("[DEATH] One-minute server timeout started.")

        minimum_timeout = int(
            self.config["death_recovery"]["minimum_timeout_seconds"]
        )
        elapsed = time.time() - detected_at
        remaining = max(0, minimum_timeout - elapsed)

        if remaining > 0:
            time.sleep(remaining)

        retry_seconds = int(
            self.config["death_recovery"]["respawn_retry_seconds"]
        )

        while True:
            character = self.get_character()

            if self.is_alive(character):
                death_state["last_detected_at"] = 0
                self.save_final_state()
                return character

            result = self.client.post("character/respawn")

            self.record(
                "respawn",
                result.ok,
                {
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                for _ in range(
                    int(
                        self.config["death_recovery"][
                            "verification_attempts"
                        ]
                    )
                ):
                    time.sleep(
                        float(
                            self.config["death_recovery"][
                                "verification_delay_seconds"
                            ]
                        )
                    )
                    character = self.get_character()

                    if self.is_alive(character):
                        self.respawns_completed += 1
                        death_state["last_detected_at"] = 0
                        death_state["respawns"] = (
                            as_int(death_state.get("respawns")) + 1
                        )
                        self.save_final_state()
                        self.logger.info(
                            "[RESPAWN] Character returned. Farming will continue."
                        )
                        return character

            wait_from_server = self.server_respawn_wait(
                {"error": result.error, "data": result.data}
            )
            sleep_for = max(retry_seconds, wait_from_server or 0)

            self.logger.info(
                "[DEATH] Respawn is not ready; checking again in %ss.",
                sleep_for,
            )
            time.sleep(sleep_for)

    @staticmethod
    def combat_power(character: dict[str, Any]) -> float:
        derived = character.get("derived")
        if not isinstance(derived, dict):
            derived = {}

        attack = as_float(
            derived.get("attack")
            or character.get("attack")
            or character.get("strength"),
            1,
        )
        defense = as_float(
            derived.get("defense")
            or character.get("defense")
            or character.get("resistance"),
            0,
        )
        hp_max = as_float(character.get("hp_max"), 1)

        return attack * 10 + defense * 8 + hp_max

    def block_dangerous_target(
        self,
        monster: dict[str, Any],
        damage_taken: int,
        character_before: dict[str, Any],
        reason: str,
    ) -> None:
        monster_id = as_int(monster.get("id"))
        if monster_id <= 0:
            return

        power = self.combat_power(character_before)
        hp_max = as_int(character_before.get("hp_max"), 1)

        required_hp = math.ceil(
            max(
                damage_taken
                * float(
                    self.config["danger_learning"][
                        "damage_safety_multiplier"
                    ]
                ),
                hp_max
                * float(
                    self.config["danger_learning"][
                        "minimum_future_hp_multiplier"
                    ]
                ),
            )
        )
        required_power = math.ceil(
            power
            * float(
                self.config["danger_learning"][
                    "required_power_growth_multiplier"
                ]
            )
        )

        blocks = self.final_state.setdefault("danger_blocks", {})
        previous = blocks.get(str(monster_id))

        blocks[str(monster_id)] = {
            "monster_code": monster.get("code"),
            "monster_name": monster.get("name_en") or monster.get("name"),
            "blocked_at": utc_now(),
            "damage_taken": damage_taken,
            "required_hp_max": required_hp,
            "required_power": required_power,
            "reason": reason,
        }

        self.save_final_state()

        if previous is None:
            self.dangerous_targets_blocked += 1
            self.logger.info(
                "[BLOCKED] %s postponed until stronger | required HP~%s.",
                (
                    monster.get("name_en")
                    or monster.get("name")
                    or monster.get("code")
                ),
                required_hp,
            )

    def target_is_blocked(
        self,
        monster: dict[str, Any],
        character: dict[str, Any],
    ) -> bool:
        monster_id = as_int(monster.get("id"))
        block = self.final_state.get(
            "danger_blocks", {}
        ).get(str(monster_id))

        if not isinstance(block, dict):
            return False

        hp_max = as_int(character.get("hp_max"), 1)
        power = self.combat_power(character)

        hp_ready = hp_max >= as_int(
            block.get("required_hp_max"), 10**9
        )
        power_ready = power >= as_float(
            block.get("required_power"), float("inf")
        )

        if hp_ready or power_ready:
            self.final_state["danger_blocks"].pop(
                str(monster_id), None
            )
            self.save_final_state()
            self.logger.info(
                "[UNLOCKED] %s is ready for a new safe test.",
                (
                    monster.get("name_en")
                    or monster.get("name")
                    or monster.get("code")
                ),
            )
            return False

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

        hp_max = as_int(character.get("hp_max"), 1)
        output = []

        for candidate in candidates:
            if self.target_is_blocked(candidate.monster, character):
                continue

            if candidate.required_hp > hp_max:
                self.block_dangerous_target(
                    candidate.monster,
                    damage_taken=candidate.predicted_damage,
                    character_before=character,
                    reason="predicted damage exceeds maximum safe HP",
                )
                continue

            output.append(candidate)

        return output

    @staticmethod
    def session_id_from_response(data: Any) -> int | None:
        direct = engine.recursive_find(
            data,
            {"session_id", "combat_id", "sessionid", "combatid"},
        )

        try:
            return int(direct)
        except (TypeError, ValueError):
            pass

        if isinstance(data, dict):
            for key in ("session", "combat", "combat_session"):
                value = data.get(key)

                if isinstance(value, (int, str)):
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        pass

                if isinstance(value, dict):
                    for id_key in ("session_id", "combat_id", "id"):
                        try:
                            return int(value.get(id_key))
                        except (TypeError, ValueError):
                            pass

        for node in walk_dicts(data):
            keys = {str(key).lower() for key in node}
            combat_context = bool(
                keys.intersection(
                    {
                        "enemy_hp",
                        "monster_hp",
                        "player_hp",
                        "turn",
                        "skills",
                        "available_skills",
                        "monster",
                        "enemy",
                        "combat_log",
                    }
                )
            )

            if not combat_context:
                continue

            for key in ("session_id", "combat_id", "id"):
                try:
                    return int(node.get(key))
                except (TypeError, ValueError):
                    pass

        return None

    @staticmethod
    def contextual_hp(data: Any, side: str) -> int | None:
        explicit_names = (
            {
                "player_hp",
                "character_hp",
                "hero_hp",
                "current_player_hp",
            }
            if side == "player"
            else {
                "enemy_hp",
                "monster_hp",
                "target_hp",
                "current_enemy_hp",
            }
        )

        direct = engine.deep_find_number(data, explicit_names)
        if direct is not None:
            return int(direct)

        context_keys = (
            {"player", "character", "hero"}
            if side == "player"
            else {"enemy", "monster", "target"}
        )

        for node in walk_dicts(data):
            for key, value in node.items():
                if str(key).lower() in context_keys and isinstance(value, dict):
                    try:
                        return int(value.get("hp"))
                    except (TypeError, ValueError):
                        pass

        return None

    @staticmethod
    def combat_outcome(data: Any) -> str | None:
        status = str(
            engine.recursive_find(
                data,
                {
                    "result",
                    "outcome",
                    "combat_result",
                    "status",
                    "state",
                },
            )
            or ""
        ).lower()

        if status in {
            "victory",
            "won",
            "win",
            "completed",
            "finished",
            "success",
        }:
            return "victory"

        if status in {
            "defeat",
            "lost",
            "loss",
            "dead",
            "failed",
        }:
            return "defeat"

        player_hp = FinalEldoriaBot.contextual_hp(data, "player")
        enemy_hp = FinalEldoriaBot.contextual_hp(data, "enemy")

        if enemy_hp is not None and enemy_hp <= 0:
            return "victory"
        if player_hp is not None and player_hp <= 0:
            return "defeat"

        return None

    def save_interactive_debug(self, stage: str, data: Any) -> None:
        interactive = self.final_state.setdefault("interactive", {})
        now = time.time()
        last = as_float(interactive.get("last_debug_at"), 0)

        if (
            now - last
            < int(
                self.config["interactive_combat"][
                    "debug_write_cooldown_seconds"
                ]
            )
        ):
            return

        interactive["last_debug_at"] = now
        self.save_final_state()

        engine.save_json(
            self.interactive_schema_file,
            {
                "generated_at": utc_now(),
                "stage": stage,
                "data": engine.sanitize(data),
            },
        )

    @staticmethod
    def skill_state_rows(data: Any) -> list[dict[str, Any]]:
        output = []

        for node in walk_dicts(data):
            for key, value in node.items():
                if (
                    str(key).lower()
                    in {
                        "skills",
                        "available_skills",
                        "session_skills",
                        "loadout",
                    }
                    and isinstance(value, list)
                ):
                    output.extend(
                        row for row in value if isinstance(row, dict)
                    )

        return output

    def server_skill_ready(
        self,
        data: Any,
        skill_id: int,
    ) -> bool | None:
        for row in self.skill_state_rows(data):
            row_id = row.get("id") or row.get("skill_id")

            try:
                if int(row_id) != skill_id:
                    continue
            except (TypeError, ValueError):
                continue

            for key in ("can_use", "available", "ready", "is_ready"):
                if key in row and isinstance(row[key], bool):
                    return row[key]

            cooldown = (
                row.get("cooldown_remaining")
                or row.get("remaining_cooldown")
                or row.get("current_cooldown")
                or row.get("cooldown_left")
            )
            if cooldown is not None:
                try:
                    return int(cooldown) <= 0
                except (TypeError, ValueError):
                    pass

        return None

    @staticmethod
    def skill_cooldown_turns(skill: dict[str, Any]) -> int:
        for key in (
            "cooldown_turns",
            "cooldown",
            "turn_cooldown",
            "cd",
        ):
            try:
                value = int(skill.get(key))
                if value >= 0:
                    return value
            except (TypeError, ValueError):
                pass

        return 2

    def action_templates(
        self,
        action_type: str,
        skill_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if action_type == "basic":
            return [
                {"kind": "basic"},
                {"action": "basic"},
                {"type": "basic"},
                {"kind": "attack"},
                {"action": "attack"},
                {"type": "attack"},
                {"action": "basic_attack"},
                {"type": "basic_attack"},
            ]

        return [
            {"kind": "skill", "skill_id": skill_id},
            {"action": "skill", "skill_id": skill_id},
            {"type": "skill", "skill_id": skill_id},
            {"kind": "use_skill", "skill_id": skill_id},
            {"action": "use_skill", "skill_id": skill_id},
            {"skill_id": skill_id},
        ]

    def send_combat_action(
        self,
        session_id: int,
        action_type: str,
        skill_id: int | None = None,
    ):
        interactive = self.final_state.setdefault("interactive", {})
        schema_key = (
            "basic_schema" if action_type == "basic" else "skill_schema"
        )
        templates = self.action_templates(action_type, skill_id)
        cached = interactive.get(schema_key)

        if isinstance(cached, int) and 0 <= cached < len(templates):
            indexes = [cached]
        else:
            indexes = list(range(len(templates)))

        last_result = None

        for index in indexes:
            result = self.client.post(
                f"world/combat/{session_id}/action",
                templates[index],
            )
            last_result = result

            if result.ok:
                interactive[schema_key] = index
                interactive["unavailable_until"] = 0
                self.save_final_state()
                return result

            error_text = text_blob(
                {"error": result.error, "data": result.data}
            )

            if (
                action_type == "skill"
                and any(
                    word in error_text
                    for word in (
                        "cooldown",
                        "not ready",
                        "unavailable",
                        "insufficient mp",
                        "not enough mp",
                    )
                )
            ):
                return result

            if result.status not in {400, 404, 422}:
                return result

        return last_result

    def learned_active_skills(self) -> list[dict[str, Any]]:
        result = self.client.get("skills/mine")
        if not result.ok:
            return []

        skills = self.learned_skills(result.data)
        race = str(self.get_character().get("race") or "").lower()

        active = [
            skill
            for skill in skills
            if str(skill.get("type", "")).lower() != "passive"
            and not skill.get("passive")
            and self.skill_id(skill) is not None
        ]
        active.sort(
            key=lambda skill: self.advanced_skill_score(skill, race),
            reverse=True,
        )
        return active

    def interactive_combat(self, candidate):
        interactive = self.final_state.setdefault("interactive", {})

        if time.time() < as_float(
            interactive.get("unavailable_until"), 0
        ):
            return None

        skills = self.learned_active_skills()
        if not skills:
            return None

        character = self.get_character()
        high_priority = candidate.priority <= 1
        maximum_mp_cost = max(
            self.skill_mp_cost(skill) for skill in skills
        )

        if high_priority and as_int(character.get("mp")) < maximum_mp_cost:
            self.use_mana_potion_if_needed(
                maximum_mp_cost,
                high_priority=True,
            )

        start = self.client.post(
            f"world/combat/start/{candidate.monster['id']}",
            {},
        )

        if not start.ok:
            self.save_interactive_debug(
                "combat_start_failed",
                {
                    "status": start.status,
                    "error": start.error,
                    "data": start.data,
                },
            )
            return None

        immediate_outcome = self.combat_outcome(start.data)
        if immediate_outcome is not None:
            return engine.APIResult(
                immediate_outcome == "victory",
                start.status,
                start.data,
                None if immediate_outcome == "victory" else "defeat",
            )

        session_id = self.session_id_from_response(start.data)

        if session_id is None:
            self.save_interactive_debug(
                "session_id_not_found",
                start.data,
            )
            interactive["unavailable_until"] = (
                time.time()
                + int(
                    self.config["interactive_combat"][
                        "retry_after_schema_failure_seconds"
                    ]
                )
            )
            self.save_final_state()
            return None

        local_cooldowns = {
            int(self.skill_id(skill)): 0
            for skill in skills
            if self.skill_id(skill) is not None
        }
        current_data = start.data
        turn = 0

        while turn < int(
            self.config["interactive_combat"]["maximum_turns"]
        ):
            outcome = self.combat_outcome(current_data)

            if outcome is not None:
                if outcome == "victory":
                    self.interactive_victories += 1

                return engine.APIResult(
                    outcome == "victory",
                    200,
                    current_data,
                    None if outcome == "victory" else "defeat",
                )

            player_hp = self.contextual_hp(current_data, "player")
            if player_hp is None:
                player_hp = as_int(self.get_character().get("hp"))

            if player_hp <= int(
                self.config["interactive_combat"]["emergency_stop_hp"]
            ):
                return engine.APIResult(
                    False,
                    200,
                    current_data,
                    "interactive_hp_low",
                )

            current_mp = first_number(
                current_data,
                {"player_mp", "character_mp", "current_mp"},
            )
            if current_mp is None:
                current_mp = as_int(self.get_character().get("mp"))

            selected_skill = None

            for skill in skills:
                skill_id = self.skill_id(skill)
                if skill_id is None:
                    continue

                if current_mp < self.skill_mp_cost(skill):
                    continue

                server_ready = self.server_skill_ready(
                    current_data,
                    skill_id,
                )
                locally_ready = local_cooldowns.get(skill_id, 0) <= 0

                if server_ready is True or (
                    server_ready is None and locally_ready
                ):
                    selected_skill = skill
                    break

            if selected_skill is not None:
                skill_id = int(self.skill_id(selected_skill))
                action = self.send_combat_action(
                    session_id,
                    "skill",
                    skill_id,
                )

                if action is not None and action.ok:
                    local_cooldowns[skill_id] = (
                        self.skill_cooldown_turns(selected_skill)
                    )
                    current_data = action.data
                    turn += 1
                    time.sleep(
                        float(
                            self.config["automation"][
                                "action_delay_seconds"
                            ]
                        )
                    )
                    continue

                error_text = text_blob(
                    {
                        "error": action.error if action is not None else None,
                        "data": action.data if action is not None else None,
                    }
                )

                if any(
                    word in error_text
                    for word in (
                        "cooldown",
                        "not ready",
                        "unavailable",
                        "insufficient mp",
                        "not enough mp",
                    )
                ):
                    local_cooldowns[skill_id] = max(
                        1,
                        local_cooldowns.get(skill_id, 0),
                    )
                elif action is not None:
                    self.save_interactive_debug(
                        "skill_action_failed",
                        {
                            "status": action.status,
                            "error": action.error,
                            "data": action.data,
                        },
                    )

            basic = self.send_combat_action(
                session_id,
                "basic",
            )

            if basic is None or not basic.ok:
                self.save_interactive_debug(
                    "basic_action_failed",
                    {
                        "status": basic.status if basic is not None else None,
                        "error": basic.error if basic is not None else None,
                        "data": basic.data if basic is not None else None,
                    },
                )
                interactive["unavailable_until"] = (
                    time.time()
                    + int(
                        self.config["interactive_combat"][
                            "retry_after_schema_failure_seconds"
                        ]
                    )
                )
                self.save_final_state()
                return None

            current_data = basic.data
            turn += 1

            for skill_id in list(local_cooldowns):
                local_cooldowns[skill_id] = max(
                    0,
                    local_cooldowns[skill_id] - 1,
                )

            time.sleep(
                float(
                    self.config["automation"]["action_delay_seconds"]
                )
            )

        return engine.APIResult(
            False,
            408,
            current_data,
            "maximum_combat_turns_reached",
        )

    def execute_fight(self, candidate) -> bool:
        character_before = self.ensure_alive()
        monster = candidate.monster
        monster_id = as_int(monster.get("id"))

        if monster_id <= 0:
            return False

        hp_max = max(1, as_int(character_before.get("hp_max"), 1))
        hp_before = as_int(character_before.get("hp"))
        risk_ratio = candidate.predicted_damage / hp_max
        high_priority = candidate.priority <= 1

        label = (
            f"{candidate.reason}: "
            f"{monster.get('name_en') or monster.get('name')}"
        )
        if label != self.last_task_label:
            self.logger.info(
                "[TASK] %s | damage~%s | Gold/STM %.2f",
                label,
                candidate.predicted_damage,
                candidate.gold_per_stamina,
            )
            self.last_task_label = label

        requires_skill_mode = bool(
            monster.get("is_boss")
            or risk_ratio
            >= float(
                self.config["danger_learning"][
                    "normal_fight_max_damage_ratio"
                ]
            )
        )

        result = None
        used_interactive = False

        if (
            self.config["skills"]["use_mp_skills"]
            and (
                requires_skill_mode
                or (
                    high_priority
                    and candidate.predicted_damage
                    >= int(
                        self.config["skills"][
                            "skill_mode_damage_threshold"
                        ]
                    )
                )
            )
        ):
            result = self.interactive_combat(candidate)
            used_interactive = result is not None

        if result is None:
            if requires_skill_mode:
                self.block_dangerous_target(
                    monster,
                    damage_taken=candidate.predicted_damage,
                    character_before=character_before,
                    reason="interactive skill combat unavailable",
                )
                return False

            result = self.client.post(f"world/fight/{monster_id}")

        self.record(
            "fight",
            result.ok,
            {
                "zone_id": candidate.zone_id,
                "monster_id": monster_id,
                "monster": monster.get("name_en") or monster.get("name"),
                "reason": candidate.reason,
                "interactive": used_interactive,
                "predicted_damage": candidate.predicted_damage,
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        damage_taken = int(
            engine.deep_find_number(
                result.data,
                {"damage_taken", "total_damage_taken"},
            )
            or 0
        )
        gold_gained = int(
            engine.deep_find_number(
                result.data,
                {"gold_gained", "gold_reward"},
            )
            or 0
        )
        xp_gained = int(
            engine.deep_find_number(
                result.data,
                {"xp_gained", "xp_reward"},
            )
            or 0
        )

        character_after = self.get_character()
        hp_after = as_int(character_after.get("hp"))
        stamina_after = as_int(character_after.get("stamina"))
        stamina_before = as_int(character_before.get("stamina"))
        stamina_used = max(0, stamina_before - stamina_after)

        if damage_taken <= 0:
            damage_taken = max(0, hp_before - hp_after)

        if result.ok:
            self.update_damage_history(monster_id, damage_taken)
            self.update_farm_history(
                monster_id=monster_id,
                gold=gold_gained,
                xp=xp_gained,
                stamina=stamina_used,
                duration_seconds=1.0,
            )
            self.total_battles += 1
            self.total_gold_gained += gold_gained

        death_or_near_death = (
            not self.is_alive(character_after)
            or hp_after
            <= math.ceil(
                hp_max
                * float(
                    self.config["danger_learning"][
                        "near_death_hp_ratio"
                    ]
                )
            )
            or damage_taken
            >= math.ceil(
                hp_max
                * float(
                    self.config["danger_learning"][
                        "near_death_damage_ratio"
                    ]
                )
            )
        )

        if death_or_near_death:
            self.block_dangerous_target(
                monster,
                damage_taken=max(
                    damage_taken,
                    hp_before - hp_after,
                ),
                character_before=character_before,
                reason="death or near-death observed",
            )

        if not self.is_alive(character_after):
            self.ensure_alive()
            return False

        if not result.ok:
            return False

        every = int(
            self.config["logging"]["battle_summary_every"]
        )
        if self.total_battles % every == 0:
            self.log_status(
                "FARM",
                character_after,
                (
                    f"Battles {self.total_battles} | "
                    f"last {monster.get('name_en') or monster.get('name')} | "
                    f"damage {damage_taken} | +{gold_gained} Gold"
                ),
            )

        return True

    def candidate_is_heavy(
        self,
        candidate,
    ) -> bool:
        character = self.get_character()
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        player_level = as_int(
            character.get("level"),
            1,
        )
        monster_level = as_int(
            candidate.monster.get("level"),
            1,
        )
        risk_ratio = (
            candidate.predicted_damage / hp_max
        )

        return bool(
            candidate.monster.get("is_boss")
            or risk_ratio
            >= float(
                self.config["danger_learning"][
                    "heavy_fight_damage_ratio"
                ]
            )
            or monster_level
            >= player_level
            + int(
                self.config["light_farm"][
                    "heavy_level_gap"
                ]
            )
        )

    def dynamic_targets_for_candidate(
        self,
        candidate,
    ) -> tuple[int, int, int]:
        character = self.get_character()
        hp_max = max(
            1,
            as_int(character.get("hp_max"), 1),
        )
        stamina_max = max(
            1,
            as_int(character.get("stamina_max"), 1),
        )
        mp_max = max(
            1,
            as_int(character.get("mp_max"), 1),
        )
        fight_cost = max(
            1,
            as_int(
                candidate.monster.get("stamina_cost"),
                1,
            ),
        )
        reserve = int(
            self.config["dynamic_resources"][
                "emergency_stamina_reserve"
            ]
        )

        if not self.candidate_is_heavy(candidate):
            # Light farming continues whenever one more safe fight is possible.
            return (
                min(hp_max, candidate.required_hp),
                min(stamina_max, fight_cost + reserve),
                0,
            )

        hp_target = max(
            candidate.required_hp,
            math.ceil(
                hp_max
                * float(
                    self.config["dynamic_final"][
                        "heavy_fight_hp_percent"
                    ]
                )
                / 100
            ),
        )
        stamina_target = max(
            self.dynamic_stamina_target(candidate),
            math.ceil(
                stamina_max
                * float(
                    self.config["dynamic_final"][
                        "heavy_fight_stamina_percent"
                    ]
                )
                / 100
            ),
        )
        mp_target = max(
            self.dynamic_mp_target(candidate),
            math.ceil(
                mp_max
                * float(
                    self.config["dynamic_final"][
                        "heavy_fight_mp_percent"
                    ]
                )
                / 100
            ),
        )

        return (
            min(hp_max, hp_target),
            min(stamina_max, stamina_target),
            min(mp_max, mp_target),
        )

    def run_farming_batch(self, material_needs) -> None:
        maximum = int(
            self.config["continuous"]["max_battles_per_batch"]
        )
        completed = 0

        while completed < maximum:
            character = self.ensure_alive()
            objectives = self.objective_rows()
            candidates = self.build_farm_candidates(
                character,
                objectives,
                material_needs,
            )

            if not candidates:
                return

            candidate = candidates[0]
            hp_target, stamina_target, mp_target = (
                self.dynamic_targets_for_candidate(candidate)
            )

            hp = as_int(character.get("hp"))
            stamina = as_int(character.get("stamina"))
            mp = as_int(character.get("mp"))

            if (
                hp < hp_target
                or stamina < stamina_target
                or mp < mp_target
            ):
                strategic_consumable = bool(
                    self.candidate_is_heavy(candidate)
                    and candidate.priority <= 3
                )

                # Light farming never burns potions just to extend a batch.
                if (
                    hp < hp_target
                    and strategic_consumable
                    and self.use_hp_potions_until_safe(
                        hp_target,
                        high_priority=True,
                    )
                ):
                    continue

                if (
                    stamina < stamina_target
                    and strategic_consumable
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

                return

            travelled = self.travel_to(
                character,
                candidate.zone_id,
            )
            if travelled is None:
                return

            if not self.execute_fight(candidate):
                return

            completed += 1

            time.sleep(
                float(
                    self.config["automation"]["action_delay_seconds"]
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
                candidate.material_score > 0
                and self.total_battles % interval == 0
            ):
                material_needs.update(
                    self.complete_craft_quests()
                )

    def next_regular_targets(
        self,
    ) -> tuple[int, int, int, str, bool]:
        character = self.ensure_alive()
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
                as_int(character.get("mp")),
                "Safe progression target",
                False,
            )

        candidate = candidates[0]
        hp_target, stamina_target, mp_target = (
            self.dynamic_targets_for_candidate(candidate)
        )

        return (
            hp_target,
            stamina_target,
            mp_target,
            candidate.reason,
            bool(
                self.candidate_is_heavy(candidate)
                and candidate.priority <= 3
            ),
        )

    def wait_for_dynamic_targets(
        self,
        hp_target: int,
        stamina_target: int,
        mp_target: int,
        priority_label: str,
        allow_stamina_potion: bool,
    ) -> None:
        announced = False
        poll = int(self.config["continuous"]["poll_seconds"])

        while True:
            character = self.ensure_alive()

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

            if (
                hp >= hp_target
                and stamina >= stamina_target
                and mp >= mp_target
            ):
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
                if hp < hp_target:
                    missing.append(f"HP {hp}/{hp_target}")
                if stamina < stamina_target:
                    missing.append(
                        f"STM {stamina}/{stamina_target}"
                    )
                if mp < mp_target:
                    missing.append(f"MP {mp}/{mp_target}")

                self.logger.info(
                    "[WAIT] %s | %s",
                    priority_label,
                    ", ".join(missing),
                )
                announced = True

            time.sleep(poll)
            self.total_wait_seconds += poll

    def final_report(self) -> dict[str, Any]:
        report = self.advanced_report()
        report.update(
            {
                "version": self.VERSION,
                "respawns_completed": self.respawns_completed,
                "dangerous_targets_blocked": (
                    self.dangerous_targets_blocked
                ),
                "interactive_victories": self.interactive_victories,
                "active_danger_blocks": self.final_state.get(
                    "danger_blocks",
                    {},
                ),
            }
        )

        engine.save_json(
            OUTPUT_DIR
            / "eldoria_bot_v1_6_1_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v1_6_1_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".json"
            ),
            report,
        )

        return report

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
            "[MODE] Free quests, safe progression and continuous Gold farming."
        )
        self.log_status("START", self.initial_character)

        try:
            while True:
                self.ensure_alive()

                objectives = self.objective_rows()
                has_urgent_quests = any(
                    row.objective_type in {"kill", "craft", "loot"}
                    for row in objectives
                )

                boss = self.active_world_boss(objectives)
                if boss is not None:
                    self.run_world_boss(boss)
                    self.ensure_alive()
                    continue

                if self.run_dungeon_autopilot(
                    has_urgent_quests=has_urgent_quests,
                ):
                    self.ensure_alive()
                    continue

                self.regular_cycle()
                self.ensure_alive()

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
            self.final_report()


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
        bot = FinalEldoriaBot(client, config, logger)
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
