from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import requests


VERSION = "1.3.1-windows"
SITE_URL = "https://eldoriaworld.com/"
API_BASE = "https://eldoriaworld.com/api/"
SITE_HOST = urlsplit(SITE_URL).hostname or ""

SCRIPT_DIR = Path(__file__).resolve().parent
DESKTOP = Path.home() / "Desktop"
ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV1_3"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

COOKIE_FILE = PRIVATE_DIR / "cookie.txt"
TOKEN_FILE = PRIVATE_DIR / "token.txt"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v1_3_1_config.json"
COMBAT_HISTORY_FILE = STATE_DIR / "combat_history.json"
RUNTIME_STATE_FILE = STATE_DIR / "runtime_state.json"
LAST_REPORT_FILE = OUTPUT_DIR / "eldoria_bot_v1_3_1_last_report.json"
LOG_COPY_FILE = OUTPUT_DIR / "eldoria_bot_v1_3_1.log"

# Stored numerically so the blocked route is never placed in normal output.
DENIED_PATH = bytes(
    [47, 116, 101, 114, 109, 115, 46, 104, 116, 109, 108]
).decode("ascii").lower()

PAID_PATH_WORDS = {
    "vip",
    "battle-pass",
    "premium",
    "subscription",
    "payment",
    "checkout",
    "deposit",
    "withdraw",
    "buy-gems",
    "offerwall",
    "card-deposits",
    "ton/",
}

PAID_QUEST_TYPES = {
    "deposit",
    "withdraw",
    "vip",
    "battle_pass",
    "purchase",
}

SUPPORTED_FREE_QUEST_TYPES = {
    "kill",
    "craft",
    "loot",
}

EQUIPMENT_TYPES = {
    "weapon",
    "helmet",
    "armor",
    "gloves",
    "boots",
    "ring",
    "amulet",
}

EQUIPMENT_WEIGHTS = {
    # Gold generation is important, but combat strength remains necessary
    # because stronger and safer farming produces more long-term Gold.
    "gold_generation": 1.70,
    "bonus_attack": 10.0,
    "bonus_spell_attack": 6.0,
    "bonus_defense": 6.0,
    "bonus_magic_def": 4.0,
    "bonus_hp": 0.42,
    "bonus_mp": 0.08,
    "bonus_strength": 8.0,
    "bonus_agility": 4.0,
    "bonus_intelligence": 3.0,
    "bonus_vitality": 6.0,
    "bonus_perception": 2.0,
    "bonus_resistance": 3.5,
    "bonus_crit": 5.0,
    "bonus_dodge": 5.0,
}

FORGE_STAT_ORDER = {
    "weapon": ["atk", "str", "def", "hp"],
    "armor": ["def", "hp", "vit", "mdef"],
    "helmet": ["def", "hp", "vit", "mdef"],
    "gloves": ["atk", "str", "def", "agi"],
    "boots": ["def", "hp", "agi", "dodge"],
    "ring": ["atk", "str", "def", "hp"],
    "amulet": ["atk", "def", "hp", "mdef"],
}

STAT_ROI_WEIGHTS = {
    "atk": 10.0,
    "str": 8.0,
    "def": 6.0,
    "hp": 0.45,
    "vit": 6.0,
    "mdef": 4.0,
    "agi": 4.0,
    "dodge": 5.0,
    "gold_generation": 1.7,
}

SENSITIVE_KEYS = re.compile(
    r"(authorization|cookie|set-cookie|password|passwd|secret|token|session|"
    r"csrf|xsrf|signature|api[-_]?key|private[-_]?key|email|phone|mobile|address)",
    re.I,
)


@dataclass
class APIResult:
    ok: bool
    status: int | None
    data: Any
    error: str | None = None


@dataclass
class QuestObjective:
    quest_id: int | None
    quest_code: str
    quest_name: str
    objective_type: str
    target: str
    remaining: int
    reward_gold: int
    reward_xp: int


@dataclass
class FarmCandidate:
    zone_id: int
    zone_name: str
    monster: dict[str, Any]
    priority: int
    reason: str
    predicted_damage: int
    required_hp: int
    gold_per_stamina: float
    xp_per_stamina: float
    material_score: float


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_json_field(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        return "[MAX_DEPTH]"

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = (
                "[REDACTED]"
                if SENSITIVE_KEYS.search(key_text)
                else sanitize(item, depth + 1)
            )
        return result

    if isinstance(value, list):
        return [sanitize(item, depth + 1) for item in value[:10000]]

    if isinstance(value, str):
        return re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
            "[REDACTED]",
            value,
        )[:1_000_000]

    return value


def is_denied(url: str) -> bool:
    try:
        return DENIED_PATH in urlsplit(url).path.lower()
    except Exception:
        return DENIED_PATH in str(url).lower()


def is_paid_path(relative: str) -> bool:
    lowered = relative.lower()
    return any(word in lowered for word in PAID_PATH_WORDS)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(math.ceil(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def deep_find_number(data: Any, names: set[str]) -> float | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        for value in data.values():
            result = deep_find_number(value, names)
            if result is not None:
                return result

    elif isinstance(data, list):
        for value in data:
            result = deep_find_number(value, names)
            if result is not None:
                return result

    return None


def deep_find_bool(data: Any, names: set[str]) -> bool | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names and isinstance(value, bool):
                return value
        for value in data.values():
            result = deep_find_bool(value, names)
            if result is not None:
                return result

    elif isinstance(data, list):
        for value in data:
            result = deep_find_bool(value, names)
            if result is not None:
                return result

    return None


def recursive_find(data: Any, names: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names:
                return value
        for value in data.values():
            result = recursive_find(value, names)
            if result is not None:
                return result

    elif isinstance(data, list):
        for value in data:
            result = recursive_find(value, names)
            if result is not None:
                return result

    return None


def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v1_3_1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    local_handler = logging.FileHandler(
        LOG_DIR / "eldoria_bot_v1_3_1.log",
        encoding="utf-8",
    )
    local_handler.setFormatter(formatter)
    logger.addHandler(local_handler)

    output_handler = logging.FileHandler(
        LOG_COPY_FILE,
        encoding="utf-8",
    )
    output_handler.setFormatter(formatter)
    logger.addHandler(output_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class APIClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

        cookie = self._load_secret(COOKIE_FILE, "Cookie")
        token = self._load_secret(TOKEN_FILE, "Token")

        self._last_request_started = 0.0
        self._consecutive_transport_failures = 0
        self._circuit_open_until = 0.0

        self.session = requests.Session()
        self.direct_session = requests.Session()
        self.direct_session.trust_env = False
        self._use_direct_connection = False

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Authorization": f"Bearer {token}",
            "Origin": SITE_URL.rstrip("/"),
            "Referer": SITE_URL,
        }
        self.session.headers.update(headers)
        self.direct_session.headers.update(headers)

    @staticmethod
    def _load_secret(path: Path, label: str) -> str:
        if not path.exists():
            raise RuntimeError(f"{label} file is missing: {path}")

        value = path.read_text(encoding="utf-8", errors="strict").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()

        if not value:
            raise RuntimeError(f"{label} file is empty.")

        return value

    def _url(self, relative: str) -> str:
        relative = relative.lstrip("/")

        if is_paid_path(relative):
            raise RuntimeError(f"Paid endpoint blocked: {relative}")

        url = urljoin(API_BASE, relative)

        if is_denied(url):
            raise RuntimeError("Denied URL blocked.")

        if (urlsplit(url).hostname or "").lower() != SITE_HOST.lower():
            raise RuntimeError("Cross-origin request blocked.")

        return url

    @staticmethod
    def _is_proxy_connection_failure(exc: requests.RequestException) -> bool:
        if isinstance(exc, requests.exceptions.ProxyError):
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "proxy",
                "tunnel connection failed",
                "cannot connect to proxy",
                "proxyerror",
            )
        )

    def _request_with_connection_fallback(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        if self._use_direct_connection:
            return self.direct_session.request(method, url, **kwargs)

        try:
            return self.session.request(method, url, **kwargs)
        except requests.RequestException as proxy_exc:
            method_upper = method.upper()
            safe_read_fallback = method_upper in {"GET", "HEAD", "OPTIONS"} and isinstance(
                proxy_exc,
                (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
            )
            if not (self._is_proxy_connection_failure(proxy_exc) or safe_read_fallback):
                raise

            try:
                response = self.direct_session.request(method, url, **kwargs)
            except requests.RequestException as direct_exc:
                raise direct_exc from proxy_exc

            self._use_direct_connection = True
            self.logger.warning(
                "[NETWORK] System proxy connection failed; switched to direct connection."
            )
            return response

    def _pacing_config(self) -> dict[str, Any]:
        row = self.config.get("server_friendly_pacing", {})
        if not isinstance(row, dict) or not row.get("enabled", True):
            return {}
        return row

    def _before_request(self) -> APIResult | None:
        cfg = self._pacing_config()
        minimum_interval = max(
            0.0,
            float(cfg.get("minimum_request_interval_seconds", 0.0) or 0.0),
        )
        now = time.monotonic()
        wait_for = self._last_request_started + minimum_interval - now
        if wait_for > 0:
            time.sleep(wait_for)
        now = time.monotonic()
        self._last_request_started = now

        if self._circuit_open_until > now:
            remaining = max(1, int(math.ceil(self._circuit_open_until - now)))
            return APIResult(
                False,
                503,
                None,
                f"Local network circuit is open for {remaining}s",
            )
        return None

    def _retry_delay(self, attempt: int, response: requests.Response | None = None) -> float:
        cfg = self._pacing_config()
        initial = max(
            0.0,
            float(
                cfg.get(
                    "read_backoff_initial_seconds",
                    self.config.get("network", {}).get("retry_delay_seconds", 7),
                )
                or 0.0
            ),
        )
        multiplier = max(1.0, float(cfg.get("read_backoff_multiplier", 2.0) or 2.0))
        cap = max(initial, float(cfg.get("read_backoff_cap_seconds", 60.0) or 60.0))
        delay = min(cap, initial * (multiplier ** max(0, attempt - 1)))

        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, min(cap, float(retry_after)))
                except (TypeError, ValueError):
                    pass
        return delay

    def _register_transport_failure(self) -> None:
        cfg = self._pacing_config()
        self._consecutive_transport_failures += 1
        threshold = max(1, int(cfg.get("circuit_breaker_failures", 4) or 4))
        if self._consecutive_transport_failures < threshold:
            return
        pause = max(1.0, float(cfg.get("circuit_breaker_seconds", 120) or 120))
        self._circuit_open_until = time.monotonic() + pause
        self._consecutive_transport_failures = 0
        self.logger.warning(
            "[NETWORK] Circuit opened for %ss after repeated transport/server failures.",
            int(pause),
        )

    def _register_response(self, status_code: int) -> None:
        retryable = set(
            int(value)
            for value in self._pacing_config().get(
                "retryable_statuses", [429, 500, 502, 503, 504]
            )
        )
        if status_code in retryable:
            self._register_transport_failure()
        else:
            self._consecutive_transport_failures = 0
            self._circuit_open_until = 0.0

    def get(self, relative: str) -> APIResult:
        attempts = max(1, int(self.config.get("network", {}).get("read_retries", 3)))
        retryable = set(
            int(value)
            for value in self._pacing_config().get(
                "retryable_statuses", [429, 500, 502, 503, 504]
            )
        )
        url = self._url(relative)
        last_error: str | None = None
        last_status: int | None = None
        last_data: Any = None

        for attempt in range(1, attempts + 1):
            blocked = self._before_request()
            if blocked is not None:
                return blocked
            try:
                response = self._request_with_connection_fallback(
                    "GET",
                    url,
                    timeout=float(self.config["network"]["read_timeout_seconds"]),
                    allow_redirects=False,
                )

                if 300 <= response.status_code < 400:
                    self._register_response(response.status_code)
                    return APIResult(
                        False,
                        response.status_code,
                        None,
                        "Unexpected redirect",
                    )

                data = self._decode(response)
                last_status = response.status_code
                last_data = data
                last_error = self._extract_error(response.status_code, data)

                if response.status_code not in retryable:
                    self._register_response(response.status_code)
                    return APIResult(
                        200 <= response.status_code < 300,
                        response.status_code,
                        data,
                        last_error,
                    )

                if attempt < attempts:
                    delay = self._retry_delay(attempt, response)
                    self.logger.info(
                        "[NETWORK] Read returned %s (%s/%s); retrying in %ss.",
                        response.status_code,
                        attempt,
                        attempts,
                        int(math.ceil(delay)),
                    )
                    time.sleep(delay)
                    continue

            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < attempts:
                    delay = self._retry_delay(attempt)
                    self.logger.info(
                        "[NETWORK] Read failed %s/%s; retrying in %ss.",
                        attempt,
                        attempts,
                        int(math.ceil(delay)),
                    )
                    time.sleep(delay)
                    continue

        self._register_transport_failure()
        return APIResult(False, last_status, last_data, last_error)

    def post(self, relative: str, body: Any | None = None) -> APIResult:
        url = self._url(relative)
        blocked = self._before_request()
        if blocked is not None:
            return blocked

        try:
            response = self._request_with_connection_fallback(
                "POST",
                url,
                json=body,
                timeout=float(self.config["network"]["write_timeout_seconds"]),
                allow_redirects=False,
            )

            if 300 <= response.status_code < 400:
                self._register_response(response.status_code)
                return APIResult(
                    False,
                    response.status_code,
                    None,
                    "Unexpected redirect",
                )

            data = self._decode(response)
            self._register_response(response.status_code)
            return APIResult(
                200 <= response.status_code < 300,
                response.status_code,
                data,
                self._extract_error(response.status_code, data),
            )

        except requests.RequestException as exc:
            # Write requests are intentionally not replayed blindly.
            self._register_transport_failure()
            return APIResult(
                False,
                None,
                None,
                f"Ambiguous write failure: {type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _decode(response: requests.Response) -> Any:
        try:
            return sanitize(response.json())
        except Exception:
            return {"raw": response.text[:500000]}

    @staticmethod
    def _extract_error(status: int, data: Any) -> str | None:
        if 200 <= status < 300:
            return None

        if isinstance(data, dict):
            return str(
                data.get("error")
                or data.get("message")
                or f"http_{status}"
            )

        return f"http_{status}"


class EldoriaBot:
    def __init__(
        self,
        client: APIClient,
        config: dict[str, Any],
        logger: logging.Logger,
    ) -> None:
        self.client = client
        self.config = config
        self.logger = logger

        self.runtime = load_json(
            RUNTIME_STATE_FILE,
            {
                "consumables": {},
                "attribute_schema": None,
                "combat_action_schema": {},
            },
        )
        self.combat_history = load_json(COMBAT_HISTORY_FILE, {})

        self.actions: list[dict[str, Any]] = []
        self.zone_catalog_cache: list[dict[str, Any]] | None = None
        self.zone_cache: dict[int, dict[str, Any]] = {}

        self.initial_character: dict[str, Any] | None = None
        self.total_battles = 0
        self.total_wait_seconds = 0
        self.total_gold_spent = 0
        self.total_gold_gained = 0
        self.hp_potions_used = 0
        self.mp_potions_used = 0
        self.stamina_potions_used = 0
        self.boxes_opened = 0
        self.equipment_changes = 0
        self.upgrades_completed = 0
        self.crafts_completed = 0
        self.attribute_points_spent = 0
        self.last_task_label: str | None = None
        self.last_skipped_quest_codes: set[str] = set()

    def record(
        self,
        action: str,
        ok: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.actions.append(
            {
                "time": utc_now(),
                "action": action,
                "ok": ok,
                "details": sanitize(details or {}),
            }
        )

    @staticmethod
    def require(result: APIResult, label: str) -> Any:
        if not result.ok:
            raise RuntimeError(
                f"{label} failed: status={result.status} error={result.error}"
            )
        return result.data

    def get_character_payload(self) -> dict[str, Any]:
        data = self.require(
            self.client.get("character/me"),
            "Read character",
        )

        if not isinstance(data, dict):
            raise RuntimeError("Invalid character payload.")

        character = data.get("character")
        if not isinstance(character, dict):
            raise RuntimeError("Character object is missing.")

        return data

    def get_character(self) -> dict[str, Any]:
        return self.get_character_payload()["character"]

    def get_inventory_payload(self) -> dict[str, Any]:
        data = self.require(
            self.client.get("inventory"),
            "Read inventory",
        )

        if not isinstance(data, dict):
            raise RuntimeError("Invalid inventory payload.")

        return data

    def get_inventory_items(self) -> list[dict[str, Any]]:
        payload = self.get_inventory_payload()
        value = payload.get("inventory", [])
        return value if isinstance(value, list) else []

    def get_quests(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        mine_data = self.require(
            self.client.get("quests/mine"),
            "Read active quests",
        )
        available_data = self.require(
            self.client.get("quests/available"),
            "Read available quests",
        )

        mine = mine_data.get("quests", []) if isinstance(mine_data, dict) else []
        available = (
            available_data.get("quests", [])
            if isinstance(available_data, dict)
            else []
        )

        return mine, available

    def get_zone_catalog(self) -> list[dict[str, Any]]:
        if self.zone_catalog_cache is not None:
            return self.zone_catalog_cache

        data = self.require(
            self.client.get("world/zones"),
            "Read world zones",
        )

        zones: list[dict[str, Any]] = []

        if isinstance(data, list):
            zones = data
        elif isinstance(data, dict):
            for key in ("zones", "items", "rows", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    zones = value
                    break

        self.zone_catalog_cache = zones
        return zones

    def get_zone(self, zone_id: int, force: bool = False) -> dict[str, Any]:
        if not force and zone_id in self.zone_cache:
            return self.zone_cache[zone_id]

        data = self.require(
            self.client.get(f"world/zone/{zone_id}"),
            f"Read zone {zone_id}",
        )

        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid zone payload: {zone_id}")

        self.zone_cache[zone_id] = data
        return data

    def log_status(
        self,
        prefix: str,
        character: dict[str, Any],
        extra: str = "",
    ) -> None:
        message = (
            f"[{prefix}] LV {character.get('level')} | "
            f"HP {character.get('hp')}/{character.get('hp_max')} | "
            f"MP {character.get('mp')}/{character.get('mp_max')} | "
            f"STM {character.get('stamina')}/{character.get('stamina_max')} | "
            f"Gold {character.get('gold')}"
        )

        if extra:
            message += f" | {extra}"

        self.logger.info(message)

    @staticmethod
    def quest_objectives(
        quest: dict[str, Any],
        use_progress: bool,
    ) -> list[dict[str, Any]]:
        if use_progress:
            progress = parse_json_field(quest.get("progress"), {})
            if isinstance(progress, dict):
                value = progress.get("objectives", [])
                return value if isinstance(value, list) else []
            return []

        value = quest.get("objectives")
        if value is None:
            value = quest.get("quest_objectives")

        parsed = parse_json_field(value, [])
        return parsed if isinstance(parsed, list) else []

    def objective_rows(self) -> list[QuestObjective]:
        mine, _ = self.get_quests()
        rows: list[QuestObjective] = []

        for quest in mine:
            if str(quest.get("status", "")).lower() != "active":
                continue

            for objective in self.quest_objectives(quest, use_progress=True):
                objective_type = str(objective.get("type", "")).lower()
                total = int(objective.get("count") or 0)
                current = int(objective.get("current") or 0)
                remaining = max(0, total - current)

                if remaining <= 0:
                    continue

                rows.append(
                    QuestObjective(
                        quest_id=quest.get("id"),
                        quest_code=str(quest.get("code", "")),
                        quest_name=str(
                            quest.get("name_en")
                            or quest.get("name")
                            or quest.get("code")
                        ),
                        objective_type=objective_type,
                        target=str(objective.get("target", "any")),
                        remaining=remaining,
                        reward_gold=int(quest.get("gold_reward") or 0),
                        reward_xp=int(quest.get("xp_reward") or 0),
                    )
                )

        return rows

    def start_all_free_quests(self) -> None:
        _, available = self.get_quests()

        for quest in available:
            code = str(quest.get("code", ""))
            objectives = self.quest_objectives(
                quest,
                use_progress=False,
            )
            objective_types = {
                str(item.get("type", "")).lower()
                for item in objectives
            }

            if objective_types.intersection(PAID_QUEST_TYPES):
                continue

            # Market listings observed for this account are Gem-denominated.
            # Therefore bazaar_buy is treated as non-free and is not automated.
            if "bazaar_buy" in objective_types or "market_buy" in objective_types:
                if code not in self.last_skipped_quest_codes:
                    self.logger.info(
                        "[SKIP] %s requires Gem-market purchases.",
                        quest.get("name_en") or quest.get("name") or code,
                    )
                    self.last_skipped_quest_codes.add(code)
                continue

            if not objective_types:
                continue

            if not objective_types.issubset(SUPPORTED_FREE_QUEST_TYPES):
                if code not in self.last_skipped_quest_codes:
                    self.logger.info(
                        "[SKIP] Unsupported free quest objective: %s",
                        ", ".join(sorted(objective_types)),
                    )
                    self.last_skipped_quest_codes.add(code)
                continue

            quest_id = quest.get("id")
            if quest_id is None:
                continue

            result = self.client.post(f"quests/start/{quest_id}")

            self.record(
                "start_quest",
                result.ok,
                {
                    "quest_id": quest_id,
                    "quest": quest.get("name_en") or quest.get("name"),
                    "types": sorted(objective_types),
                    "status": result.status,
                    "error": result.error,
                },
            )

            if result.ok:
                self.logger.info(
                    "[QUEST] Started: %s",
                    quest.get("name_en") or quest.get("name"),
                )

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def claim_free_rewards(self) -> None:
        payload = self.get_character_payload()
        claim = payload.get("claim")

        if isinstance(claim, dict) and claim.get("can_claim"):
            result = self.client.post("character/claim-daily")

            self.record(
                "claim_daily_gold",
                result.ok,
                {
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                gained = int(
                    deep_find_number(
                        result.data,
                        {"gold", "gold_gained", "amount"},
                    )
                    or 0
                )
                self.total_gold_gained += gained
                self.logger.info(
                    "[REWARD] Free daily Gold claimed%s.",
                    f": +{gained}" if gained else "",
                )

        mine, _ = self.get_quests()

        for quest in mine:
            if str(quest.get("status", "")).lower() != "completed":
                continue

            quest_instance_id = quest.get("id")
            if quest_instance_id is None:
                continue

            result = self.client.post(
                f"quests/claim/{quest_instance_id}"
            )

            self.record(
                "claim_quest",
                result.ok,
                {
                    "quest_id": quest_instance_id,
                    "quest": quest.get("name_en") or quest.get("name"),
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                gained = int(
                    deep_find_number(
                        result.data,
                        {"gold", "gold_gained"},
                    )
                    or 0
                )
                self.total_gold_gained += gained
                self.logger.info(
                    "[QUEST] Claimed: %s%s",
                    quest.get("name_en") or quest.get("name"),
                    f" | +{gained} Gold" if gained else "",
                )

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def investment_policy(
        self,
        character: dict[str, Any],
    ) -> dict[str, int | float]:
        level = int(character.get("level") or 1)
        gold = int(character.get("gold") or 0)

        if level <= 10:
            reserve_ratio = 0.10
            invest_ratio = 0.70
            payback_days = 8.0
        elif level <= 20:
            reserve_ratio = 0.18
            invest_ratio = 0.55
            payback_days = 12.0
        elif level <= 40:
            reserve_ratio = 0.28
            invest_ratio = 0.42
            payback_days = 18.0
        else:
            reserve_ratio = 0.38
            invest_ratio = 0.30
            payback_days = 25.0

        reserve = max(
            int(self.config["economy"]["absolute_minimum_gold"]),
            int(gold * reserve_ratio),
        )
        budget = max(
            0,
            min(
                gold - reserve,
                int(gold * invest_ratio),
            ),
        )

        return {
            "reserve": reserve,
            "budget": budget,
            "payback_days": payback_days,
        }

    @staticmethod
    def item_score(item: dict[str, Any] | None) -> float:
        if not item:
            return -1.0

        score = 0.0

        for key, weight in EQUIPMENT_WEIGHTS.items():
            try:
                score += float(item.get(key) or 0) * weight
            except (TypeError, ValueError):
                pass

        try:
            score += float(item.get("upgrade_level") or 1) * 2.5
        except (TypeError, ValueError):
            pass

        rarity = str(item.get("effective_tier") or item.get("rarity") or "")
        rarity_bonus = {
            "common": 0,
            "uncommon": 6,
            "rare": 15,
            "epic": 30,
            "legendary": 55,
        }
        score += rarity_bonus.get(rarity.lower(), 0)

        return score

    def open_free_boxes(self) -> None:
        if not self.config["equipment"]["open_free_boxes"]:
            return

        for item in self.get_inventory_items():
            code = str(item.get("code", "")).lower()
            item_type = str(item.get("type", "")).lower()
            subtype = str(item.get("subtype", "")).lower()

            is_box = (
                code.startswith("box_")
                or "chest" in code
                or item_type in {"box", "chest"}
                or subtype in {"box", "chest"}
            )

            if not is_box:
                continue

            inventory_id = item.get("id")
            quantity = int(item.get("quantity") or 0)

            if inventory_id is None or quantity <= 0:
                continue

            result = self.client.post(
                f"inventory/open/{inventory_id}",
                {"quantity": quantity},
            )

            self.record(
                "open_box",
                result.ok,
                {
                    "code": code,
                    "quantity": quantity,
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                self.boxes_opened += quantity
                self.logger.info(
                    "[BOX] Opened %sx %s.",
                    quantity,
                    code,
                )

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def auto_equip_best(self) -> None:
        if not self.config["equipment"]["auto_equip"]:
            return

        payload = self.get_inventory_payload()
        items = payload.get("inventory", [])
        equipment = payload.get("equipment", [])

        if not isinstance(items, list) or not isinstance(equipment, list):
            return

        character = self.get_character()
        level = int(character.get("level") or 1)

        items_by_id = {
            int(item["id"]): item
            for item in items
            if item.get("id") is not None
        }

        current_by_slot: dict[str, dict[str, Any] | None] = {}

        for row in equipment:
            slot = str(row.get("slot", ""))
            inventory_id = row.get("inventory_id")

            try:
                current_by_slot[slot] = items_by_id.get(int(inventory_id))
            except (TypeError, ValueError):
                current_by_slot[slot] = None

        candidates_by_type: dict[str, list[dict[str, Any]]] = {}

        for item in items:
            item_type = str(item.get("type", "")).lower()

            if item_type not in EQUIPMENT_TYPES:
                continue
            if int(item.get("level_req") or 1) > level:
                continue
            if item.get("broken"):
                continue

            candidates_by_type.setdefault(item_type, []).append(item)

        desired: dict[str, dict[str, Any]] = {}

        for slot in ("weapon", "helmet", "armor", "gloves", "boots", "amulet"):
            candidates = candidates_by_type.get(slot, [])
            if candidates:
                desired[slot] = max(candidates, key=self.item_score)

        rings = sorted(
            candidates_by_type.get("ring", []),
            key=self.item_score,
            reverse=True,
        )

        if rings:
            desired["ring1"] = rings[0]
        if len(rings) > 1:
            desired["ring2"] = rings[1]

        minimum_gain = float(
            self.config["equipment"]["minimum_score_gain"]
        )

        for slot, best in desired.items():
            current = current_by_slot.get(slot)
            current_score = self.item_score(current)
            new_score = self.item_score(best)

            if current and int(current.get("id")) == int(best.get("id")):
                continue

            if new_score < current_score + minimum_gain:
                continue

            body = {"slot": slot} if slot.startswith("ring") else None
            result = self.client.post(
                f"inventory/equip/{best['id']}",
                body,
            )

            self.record(
                "equip",
                result.ok,
                {
                    "slot": slot,
                    "item": best.get("name") or best.get("name_en"),
                    "old_score": round(current_score, 2),
                    "new_score": round(new_score, 2),
                    "status": result.status,
                    "error": result.error,
                },
            )

            if result.ok:
                self.equipment_changes += 1
                self.logger.info(
                    "[EQUIP] %s: %s | score %.1f -> %.1f",
                    slot,
                    best.get("name") or best.get("name_en"),
                    current_score,
                    new_score,
                )

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def allocate_attributes(self) -> None:
        if not self.config["progression"]["auto_allocate_attributes"]:
            return

        character = self.get_character()
        points = int(character.get("attribute_points") or 0)

        if points <= 0:
            return

        race = str(character.get("race", "")).lower()

        if race == "drakkar":
            stat_order = ["strength", "vitality", "resistance"]
        else:
            stat_order = ["strength", "vitality", "agility"]

        cached_schema = self.runtime.get("attribute_schema")
        schemas = [
            lambda stat: {stat: 1},
            lambda stat: {"attribute": stat, "points": 1},
            lambda stat: {"stat": stat, "points": 1},
            lambda stat: {"attribute": stat},
        ]

        if isinstance(cached_schema, int) and 0 <= cached_schema < len(schemas):
            schema_indexes = [cached_schema]
        else:
            schema_indexes = list(range(len(schemas)))

        spent = 0

        while points > 0:
            stat = stat_order[spent % len(stat_order)]
            accepted = False

            for schema_index in schema_indexes:
                body = schemas[schema_index](stat)
                result = self.client.post("character/allocate", body)

                if result.ok:
                    self.runtime["attribute_schema"] = schema_index
                    save_json(RUNTIME_STATE_FILE, self.runtime)
                    schema_indexes = [schema_index]
                    accepted = True
                    spent += 1
                    points -= 1
                    self.attribute_points_spent += 1
                    self.logger.info(
                        "[ATTR] +1 %s.",
                        stat,
                    )
                    self.record(
                        "allocate_attribute",
                        True,
                        {
                            "stat": stat,
                            "schema": schema_index,
                            "response": result.data,
                        },
                    )
                    break

                # Validation errors allow trying another body shape.
                if result.status not in {400, 404, 422}:
                    self.record(
                        "allocate_attribute",
                        False,
                        {
                            "stat": stat,
                            "status": result.status,
                            "error": result.error,
                        },
                    )
                    return

            if not accepted:
                self.logger.info(
                    "[ATTR] Server allocation format was not recognized; skipped."
                )
                return

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def forge_best_stats(self) -> None:
        if not self.config["progression"]["auto_forge"]:
            return

        character = self.get_character()
        policy = self.investment_policy(character)
        remaining_budget = int(policy["budget"])
        reserve = int(policy["reserve"])

        if remaining_budget <= 0:
            return

        items_result = self.client.get("forge/stat/items")

        if not items_result.ok:
            self.logger.info(
                "[UPGRADE] Forge list unavailable; skipped this cycle."
            )
            return

        raw = items_result.data
        forge_items: list[dict[str, Any]] = []

        if isinstance(raw, list):
            forge_items = raw
        elif isinstance(raw, dict):
            for key in ("items", "rows", "data"):
                value = raw.get(key)
                if isinstance(value, list):
                    forge_items = value
                    break

        if not forge_items:
            return

        inventory = self.get_inventory_payload()
        equipped_ids = {
            int(row.get("inventory_id"))
            for row in inventory.get("equipment", [])
            if row.get("inventory_id") is not None
        }

        proposals: list[dict[str, Any]] = []

        for item in forge_items:
            kind = str(item.get("kind") or "inventory")
            item_id = item.get("id")
            inventory_id = item.get("inventory_id") or item_id
            item_type = str(item.get("type") or "").lower()

            try:
                inventory_id_int = int(inventory_id)
            except (TypeError, ValueError):
                continue

            if inventory_id_int not in equipped_ids:
                continue

            for stat in FORGE_STAT_ORDER.get(
                item_type,
                ["atk", "def", "hp"],
            ):
                preview = self.client.get(
                    "forge/stat/preview/"
                    f"{quote(kind)}/{quote(str(item_id))}/{quote(stat)}"
                )

                if not preview.ok:
                    continue

                can_upgrade = deep_find_bool(
                    preview.data,
                    {"can_upgrade", "can_forge", "affordable", "can"},
                )
                gem_cost = deep_find_number(
                    preview.data,
                    {"gem_cost", "gems_cost", "cost_gems"},
                ) or 0
                gold_cost = deep_find_number(
                    preview.data,
                    {"gold_cost", "cost_gold", "gold"},
                )
                missing = deep_find_number(
                    preview.data,
                    {"missing", "missing_qty", "material_missing"},
                )
                stat_gain = deep_find_number(
                    preview.data,
                    {
                        "gain",
                        "stat_gain",
                        "increase",
                        "delta",
                        "next_gain",
                    },
                )
                daily_gold_gain = deep_find_number(
                    preview.data,
                    {
                        "gold_generation_gain",
                        "daily_gold_gain",
                        "gold_gain",
                    },
                )

                if can_upgrade is False:
                    continue
                if gem_cost > 0:
                    continue
                if missing is not None and missing > 0:
                    continue
                if gold_cost is None or gold_cost <= 0:
                    continue

                if daily_gold_gain and daily_gold_gain > 0:
                    roi_value = daily_gold_gain * 100
                    payback_days = gold_cost / daily_gold_gain
                    acceptable = payback_days <= float(policy["payback_days"])
                else:
                    if stat_gain is None:
                        # Never spend Gold when the upgrade result is unknown.
                        continue
                    roi_value = (
                        float(stat_gain)
                        * STAT_ROI_WEIGHTS.get(stat, 1.0)
                        / float(gold_cost)
                    )
                    payback_days = None
                    acceptable = roi_value >= float(
                        self.config["economy"]["minimum_combat_upgrade_roi"]
                    )

                if not acceptable:
                    continue

                proposals.append(
                    {
                        "kind": kind,
                        "item_id": item_id,
                        "inventory_id": inventory_id_int,
                        "item_type": item_type,
                        "stat": stat,
                        "gold_cost": int(gold_cost),
                        "roi": float(roi_value),
                        "payback_days": payback_days,
                    }
                )

        proposals.sort(
            key=lambda row: (
                row["payback_days"] is None,
                row["payback_days"] or 0,
                -row["roi"],
            )
        )

        max_upgrades = int(
            self.config["progression"]["max_forge_upgrades_per_cycle"]
        )

        for proposal in proposals:
            if self.upgrades_completed >= max_upgrades:
                break

            cost = int(proposal["gold_cost"])

            if cost > remaining_budget:
                continue

            current = self.get_character()
            current_gold = int(current.get("gold") or 0)

            if current_gold - cost < reserve:
                continue

            result = self.client.post(
                "forge/stat/upgrade",
                {
                    "kind": proposal["kind"],
                    "id": proposal["item_id"],
                    "stat": proposal["stat"],
                },
            )

            self.record(
                "forge_upgrade",
                result.ok,
                {
                    **proposal,
                    "status": result.status,
                    "error": result.error,
                    "response": result.data,
                },
            )

            if result.ok:
                remaining_budget -= cost
                self.total_gold_spent += cost
                self.upgrades_completed += 1
                self.logger.info(
                    "[UPGRADE] %s +1 | %s Gold | reserve %s",
                    proposal["stat"].upper(),
                    cost,
                    reserve,
                )

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

    def optimize_progression(self) -> None:
        self.open_free_boxes()
        self.auto_equip_best()
        self.allocate_attributes()
        self.forge_best_stats()
        self.auto_equip_best()

    def recipe_rows(self) -> list[dict[str, Any]]:
        data = self.require(
            self.client.get("crafting/table/recipes"),
            "Read crafting recipes",
        )

        if isinstance(data, dict):
            value = data.get("recipes", [])
            return value if isinstance(value, list) else []

        return []

    def complete_craft_quests(self) -> dict[str, int]:
        objectives = [
            row
            for row in self.objective_rows()
            if row.objective_type == "craft"
        ]

        if not objectives:
            return {}

        recipes = self.recipe_rows()
        recipes_by_output: dict[str, dict[str, Any]] = {}

        for recipe in recipes:
            output = recipe.get("output")
            if isinstance(output, dict):
                output_code = str(output.get("code", ""))
                if output_code:
                    recipes_by_output[output_code] = recipe

        missing_materials: dict[str, int] = {}

        for objective in objectives:
            recipe = recipes_by_output.get(objective.target)

            if recipe is None:
                continue

            character = self.get_character()
            policy = self.investment_policy(character)
            gold = int(character.get("gold") or 0)

            # Craft quests may spend more aggressively because completing them
            # unlocks progression. A small emergency reserve is still preserved.
            quest_reserve = max(
                int(self.config["economy"]["absolute_minimum_gold"]),
                int(policy["reserve"] * 0.50),
            )
            recipe_cost = int(recipe.get("gold_cost") or 0)

            ingredients = recipe.get("ingredients", [])
            if not isinstance(ingredients, list):
                ingredients = []

            material_capacity = objective.remaining

            for ingredient in ingredients:
                required_each = int(ingredient.get("qty") or 0)
                have = int(ingredient.get("have") or 0)

                if required_each <= 0:
                    continue

                material_capacity = min(
                    material_capacity,
                    have // required_each,
                )

                total_needed = required_each * objective.remaining
                shortage = max(0, total_needed - have)

                if shortage > 0:
                    code = str(ingredient.get("code", ""))
                    if code:
                        missing_materials[code] = max(
                            missing_materials.get(code, 0),
                            shortage,
                        )

            if recipe_cost > 0:
                gold_capacity = max(
                    0,
                    (gold - quest_reserve) // recipe_cost,
                )
            else:
                gold_capacity = objective.remaining

            craft_count = max(
                0,
                min(
                    objective.remaining,
                    material_capacity,
                    gold_capacity,
                ),
            )

            if craft_count <= 0:
                continue

            self.logger.info(
                "[CRAFT] %s | crafting %s/%s %s.",
                objective.quest_name,
                craft_count,
                objective.remaining,
                objective.target,
            )

            for _ in range(craft_count):
                result = self.client.post(
                    f"crafting/table/craft/{recipe['id']}"
                )

                self.record(
                    "craft",
                    result.ok,
                    {
                        "quest": objective.quest_name,
                        "target": objective.target,
                        "recipe_id": recipe.get("id"),
                        "gold_cost": recipe_cost,
                        "status": result.status,
                        "error": result.error,
                        "response": result.data,
                    },
                )

                if not result.ok:
                    break

                self.crafts_completed += 1
                self.total_gold_spent += recipe_cost

                time.sleep(
                    float(self.config["automation"]["action_delay_seconds"])
                )

        return missing_materials

    def accessible_farm_zones(
        self,
        character_level: int,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        for zone in self.get_zone_catalog():
            try:
                zone_id = int(zone.get("id"))
                min_level = int(zone.get("min_level") or 1)
                max_level = int(zone.get("max_level") or 9999)
            except (TypeError, ValueError):
                continue

            if str(zone.get("type", "")).lower() != "farm":
                continue
            if zone.get("hidden"):
                continue
            if min_level <= character_level <= max_level:
                result.append({**zone, "id": zone_id})

        return result

    def observed_damage(
        self,
        monster_id: int,
    ) -> tuple[float, float, int] | None:
        row = self.combat_history.get(str(monster_id))

        if not isinstance(row, dict):
            return None

        count = int(row.get("count") or 0)
        if count <= 0:
            return None

        return (
            float(row.get("average") or 0),
            float(row.get("maximum") or 0),
            count,
        )

    def update_damage_history(
        self,
        monster_id: int,
        damage_taken: int,
    ) -> None:
        key = str(monster_id)
        row = self.combat_history.setdefault(
            key,
            {
                "count": 0,
                "total": 0,
                "maximum": 0,
                "average": 0,
            },
        )

        row["count"] = int(row.get("count") or 0) + 1
        row["total"] = int(row.get("total") or 0) + max(0, damage_taken)
        row["maximum"] = max(
            int(row.get("maximum") or 0),
            max(0, damage_taken),
        )
        row["average"] = row["total"] / row["count"]

        save_json(COMBAT_HISTORY_FILE, self.combat_history)

    def predict_damage(
        self,
        character: dict[str, Any],
        monster: dict[str, Any],
    ) -> int:
        monster_id = int(monster.get("id") or 0)
        observed = self.observed_damage(monster_id)

        if observed:
            average, maximum, samples = observed
            if samples >= int(
                self.config["combat"]["minimum_history_samples"]
            ):
                predicted = max(
                    maximum
                    + int(self.config["combat"]["history_flat_margin"]),
                    average
                    * float(self.config["combat"]["history_multiplier"]),
                )
                return max(1, math.ceil(predicted))

        derived = character.get("derived")
        if not isinstance(derived, dict):
            derived = {}

        player_attack = float(
            derived.get("attack")
            or character.get("attack")
            or character.get("strength")
            or 1
        )
        player_defense = float(
            derived.get("defense")
            or character.get("defense")
            or character.get("resistance")
            or 0
        )
        monster_hp = float(
            monster.get("hp")
            or monster.get("hp_max")
            or 1
        )
        monster_attack = float(monster.get("attack") or 1)
        monster_defense = float(monster.get("defense") or 0)

        expected_player_hit = max(
            8.0,
            player_attack * 2.3 - monster_defense * 0.5,
        )
        expected_rounds = max(
            1,
            math.ceil(monster_hp / expected_player_hit),
        )
        expected_incoming = max(
            3.0,
            monster_attack - player_defense * 0.45,
        )

        return max(
            1,
            math.ceil(expected_rounds * expected_incoming * 0.70),
        )

    @staticmethod
    def drop_material_score(
        monster: dict[str, Any],
        material_needs: dict[str, int],
    ) -> float:
        if not material_needs:
            return 0.0

        score = 0.0
        drops: list[dict[str, Any]] = []

        for key in ("guaranteed_drops", "chance_drops"):
            value = monster.get(key)
            if isinstance(value, list):
                drops.extend(value)

        for drop in drops:
            code = str(drop.get("item") or drop.get("code") or "")
            if code not in material_needs:
                continue

            chance = float(drop.get("chance") or 100)
            quantity = float(drop.get("qty") or 1)
            need = material_needs[code]

            score += chance * quantity * min(need, 10)

        return score

    def build_farm_candidates(
        self,
        character: dict[str, Any],
        objectives: list[QuestObjective],
        material_needs: dict[str, int],
    ) -> list[FarmCandidate]:
        level = int(character.get("level") or 1)

        specific_targets: dict[str, list[QuestObjective]] = {}
        any_kill_objectives: list[QuestObjective] = []
        loot_objectives: list[QuestObjective] = []

        for objective in objectives:
            if objective.objective_type == "kill":
                if objective.target in {"", "any", "*"}:
                    any_kill_objectives.append(objective)
                else:
                    specific_targets.setdefault(
                        objective.target,
                        [],
                    ).append(objective)

            elif objective.objective_type == "loot":
                loot_objectives.append(objective)

        candidates: list[FarmCandidate] = []

        for zone in self.accessible_farm_zones(level):
            zone_id = int(zone["id"])
            zone_payload = self.get_zone(zone_id)
            monsters = zone_payload.get("monsters", [])

            if not isinstance(monsters, list):
                continue

            for monster in monsters:
                if monster.get("level_locked"):
                    continue
                if monster.get("boss_kills_locked"):
                    continue
                if monster.get("overlevel_penalty"):
                    continue

                monster_code = str(monster.get("code", ""))
                matched_specific = specific_targets.get(monster_code, [])
                material_score = self.drop_material_score(
                    monster,
                    material_needs,
                )

                if matched_specific:
                    best_objective = min(
                        matched_specific,
                        key=lambda row: (
                            row.remaining,
                            -row.reward_gold,
                            -row.reward_xp,
                        ),
                    )
                    priority = 0
                    reason = (
                        f"{best_objective.quest_name} "
                        f"({best_objective.remaining} remaining)"
                    )

                elif material_score > 0:
                    priority = 1
                    reason = "Craft material farming"

                elif any_kill_objectives:
                    best_objective = min(
                        any_kill_objectives,
                        key=lambda row: (
                            row.remaining,
                            -row.reward_gold,
                            -row.reward_xp,
                        ),
                    )
                    priority = 2
                    reason = (
                        f"{best_objective.quest_name} "
                        f"({best_objective.remaining} remaining)"
                    )

                elif loot_objectives:
                    best_objective = min(
                        loot_objectives,
                        key=lambda row: row.remaining,
                    )
                    priority = 3
                    reason = (
                        f"{best_objective.quest_name} "
                        f"({best_objective.remaining} remaining)"
                    )

                else:
                    priority = 4
                    reason = "Continuous Gold farming"

                damage = self.predict_damage(character, monster)
                required_hp = (
                    damage
                    + int(self.config["combat"]["minimum_hp_after_battle"])
                    + int(self.config["combat"]["extra_hp_margin"])
                )

                stamina_cost = max(
                    1,
                    int(monster.get("stamina_cost") or 1),
                )
                expected_gold = (
                    float(monster.get("gold_min") or 0)
                    + float(monster.get("gold_max") or 0)
                ) / 2

                candidates.append(
                    FarmCandidate(
                        zone_id=zone_id,
                        zone_name=str(
                            zone.get("name_en")
                            or zone.get("name")
                            or zone_id
                        ),
                        monster=monster,
                        priority=priority,
                        reason=reason,
                        predicted_damage=damage,
                        required_hp=required_hp,
                        gold_per_stamina=expected_gold / stamina_cost,
                        xp_per_stamina=(
                            float(monster.get("xp_reward") or 0)
                            / stamina_cost
                        ),
                        material_score=material_score,
                    )
                )

        candidates.sort(
            key=lambda row: (
                row.priority,
                row.predicted_damage,
                row.required_hp,
                -row.material_score,
                -row.gold_per_stamina,
                -row.xp_per_stamina,
                int(row.monster.get("level") or 0),
            )
        )

        return candidates

    @staticmethod
    def inventory_consumables(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = []

        for item in items:
            if str(item.get("type", "")).lower() != "consumable":
                continue
            if int(item.get("quantity") or 0) <= 0:
                continue
            if item.get("id") is None:
                continue

            effects = parse_json_field(item.get("effects"), {})
            if not isinstance(effects, dict):
                effects = {}

            result.append(
                {
                    **item,
                    "_effects": effects,
                }
            )

        return result

    def use_inventory_item(
        self,
        item: dict[str, Any],
        purpose: str,
    ) -> bool:
        result = self.client.post(
            f"inventory/use/{item['id']}"
        )

        self.record(
            "use_consumable",
            result.ok,
            {
                "purpose": purpose,
                "code": item.get("code"),
                "inventory_id": item.get("id"),
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        if result.ok:
            self.logger.info(
                "[POTION] %s used for %s.",
                item.get("name_en") or item.get("name") or item.get("code"),
                purpose,
            )
            return True

        return False

    def use_hp_potions_until_safe(
        self,
        required_hp: int,
        high_priority: bool,
    ) -> bool:
        character = self.get_character()
        current_hp = int(character.get("hp") or 0)
        hp_max = int(character.get("hp_max") or 1)

        if current_hp >= required_hp:
            return True

        if not self.config["consumables"]["use_hp_potions"]:
            return False

        # Potions are used aggressively for quests/material progression,
        # but ordinary Gold farming can wait for natural regeneration.
        if not high_priority:
            return False

        maximum_uses = int(
            self.config["consumables"]["max_hp_potions_per_cycle"]
        )
        uses = 0

        while current_hp < required_hp and uses < maximum_uses:
            consumables = self.inventory_consumables(
                self.get_inventory_items()
            )

            hp_options = []

            for item in consumables:
                effects = item["_effects"]
                heal_value = effects.get("heal")

                if heal_value == "max":
                    amount = hp_max
                else:
                    try:
                        amount = int(heal_value or 0)
                    except (TypeError, ValueError):
                        amount = 0

                if amount > 0:
                    hp_options.append((amount, item))

            if not hp_options:
                return False

            missing = max(1, required_hp - current_hp)
            hp_options.sort(
                key=lambda row: (
                    row[0] < missing,
                    abs(row[0] - missing),
                )
            )
            _, selected = hp_options[0]

            if not self.use_inventory_item(
                selected,
                "safe quest combat",
            ):
                return False

            self.hp_potions_used += 1
            uses += 1
            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

            character = self.get_character()
            current_hp = int(character.get("hp") or 0)

        return current_hp >= required_hp

    def stamina_potion_allowed(self) -> bool:
        now = time.time()
        state = self.runtime.setdefault("consumables", {})
        uses = state.setdefault("stamina_uses", [])

        if not isinstance(uses, list):
            uses = []
            state["stamina_uses"] = uses

        day_seconds = 24 * 3600
        uses[:] = [
            float(timestamp)
            for timestamp in uses
            if now - float(timestamp) < day_seconds
        ]

        return len(uses) < int(
            self.config["consumables"]["max_stamina_potions_per_24h"]
        )

    def mark_stamina_potion_used(self) -> None:
        state = self.runtime.setdefault("consumables", {})
        uses = state.setdefault("stamina_uses", [])
        uses.append(time.time())
        save_json(RUNTIME_STATE_FILE, self.runtime)

    def use_stamina_potion_if_worthwhile(
        self,
        character: dict[str, Any],
        has_priority_tasks: bool,
    ) -> bool:
        if not self.config["consumables"]["use_stamina_potions"]:
            return False
        if not self.stamina_potion_allowed():
            return False

        current = int(character.get("stamina") or 0)
        maximum = int(character.get("stamina_max") or 1)

        if current > int(
            self.config["consumables"]["stamina_use_below"]
        ):
            return False

        # Max Stamina Potions are valuable. They are used only when a large
        # part of the refill is needed or important tasks remain.
        missing_ratio = (maximum - current) / max(1, maximum)

        if (
            missing_ratio
            < float(
                self.config["consumables"][
                    "minimum_stamina_refill_efficiency"
                ]
            )
            and not has_priority_tasks
        ):
            return False

        consumables = self.inventory_consumables(
            self.get_inventory_items()
        )
        options = []

        for item in consumables:
            stamina_value = item["_effects"].get("stamina")

            if stamina_value == "max":
                amount = maximum - current
            else:
                try:
                    amount = int(stamina_value or 0)
                except (TypeError, ValueError):
                    amount = 0

            if amount > 0:
                options.append((amount, item))

        if not options:
            return False

        needed = max(
            1,
            int(self.config["continuous"]["resume_stamina"]) - current,
        )
        options.sort(
            key=lambda row: (
                row[0] < needed,
                abs(row[0] - needed),
            )
        )
        _, selected = options[0]

        if not self.use_inventory_item(
            selected,
            "quest and Gold farming continuation",
        ):
            return False

        self.stamina_potions_used += 1
        self.mark_stamina_potion_used()
        return True

    def use_mana_potion_if_needed(
        self,
        required_mp: int,
        high_priority: bool,
    ) -> bool:
        character = self.get_character()
        current_mp = int(character.get("mp") or 0)

        if current_mp >= required_mp:
            return True
        if not high_priority:
            return False
        if not self.config["consumables"]["use_mana_potions"]:
            return False

        consumables = self.inventory_consumables(
            self.get_inventory_items()
        )
        options = []

        for item in consumables:
            mana_value = item["_effects"].get("mana")
            if mana_value == "max":
                amount = int(character.get("mp_max") or 1)
            else:
                try:
                    amount = int(mana_value or 0)
                except (TypeError, ValueError):
                    amount = 0

            if amount > 0:
                options.append((amount, item))

        if not options:
            return False

        missing = max(1, required_mp - current_mp)
        options.sort(
            key=lambda row: (
                row[0] < missing,
                abs(row[0] - missing),
            )
        )

        if self.use_inventory_item(
            options[0][1],
            "high-priority skill combat",
        ):
            self.mp_potions_used += 1
            return True

        return False

    def travel_to(
        self,
        character: dict[str, Any],
        zone_id: int,
    ) -> dict[str, Any] | None:
        current_zone = int(character.get("zone_id") or 0)

        if current_zone == zone_id:
            return character

        result = self.client.post(f"world/travel/{zone_id}")

        self.record(
            "travel",
            result.ok,
            {
                "from_zone": current_zone,
                "to_zone": zone_id,
                "status": result.status,
                "error": result.error,
            },
        )

        for _ in range(
            int(self.config["travel"]["verification_attempts"])
        ):
            time.sleep(
                float(self.config["travel"]["verification_delay_seconds"])
            )
            refreshed = self.get_character()

            if int(refreshed.get("zone_id") or 0) == zone_id:
                self.logger.info(
                    "[TRAVEL] Zone %s -> %s.",
                    current_zone,
                    zone_id,
                )
                return refreshed

        self.logger.info(
            "[STOP] Travel to zone %s could not be confirmed.",
            zone_id,
        )
        return None

    @staticmethod
    def learned_skills(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = []
            for key in (
                "skills",
                "learned",
                "mine",
                "items",
                "data",
            ):
                value = data.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
        else:
            return []

        result = []

        for skill in candidates:
            if not isinstance(skill, dict):
                continue
            skill_id = skill.get("id") or skill.get("skill_id")
            if skill_id is None:
                continue
            result.append(skill)

        return result

    @staticmethod
    def skill_mp_cost(skill: dict[str, Any]) -> int:
        value = (
            skill.get("mp_cost")
            or skill.get("mana_cost")
            or skill.get("cost_mp")
            or 0
        )
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def skill_score(skill: dict[str, Any]) -> float:
        damage = (
            deep_find_number(
                skill,
                {
                    "damage",
                    "base_damage",
                    "power",
                    "damage_pct",
                    "multiplier",
                },
            )
            or 0
        )
        heal = (
            deep_find_number(
                skill,
                {
                    "heal",
                    "healing",
                    "heal_amount",
                    "heal_pct",
                },
            )
            or 0
        )
        defense = (
            deep_find_number(
                skill,
                {
                    "defense",
                    "shield",
                    "damage_reduction",
                    "defense_pct",
                },
            )
            or 0
        )
        mp_cost = max(1, EldoriaBot.skill_mp_cost(skill))

        return (
            float(damage)
            + float(heal) * 0.7
            + float(defense) * 0.5
        ) / mp_cost

    def best_learned_skill(self) -> dict[str, Any] | None:
        result = self.client.get("skills/mine")

        if not result.ok:
            return None

        skills = self.learned_skills(result.data)

        usable = [
            skill
            for skill in skills
            if not skill.get("passive")
            and str(skill.get("type", "")).lower() != "passive"
            and self.skill_mp_cost(skill) > 0
        ]

        if not usable:
            return None

        return max(usable, key=self.skill_score)

    def interactive_combat(
        self,
        candidate: FarmCandidate,
    ) -> APIResult | None:
        # Interactive combat is used only for higher-risk, high-priority fights.
        # If the server's current session format is not recognized, the bot
        # returns None and does not guess repeatedly.
        skill = self.best_learned_skill()

        if skill is None:
            return None

        required_mp = self.skill_mp_cost(skill)

        if required_mp <= 0:
            return None

        if not self.use_mana_potion_if_needed(
            required_mp,
            high_priority=True,
        ):
            character = self.get_character()
            if int(character.get("mp") or 0) < required_mp:
                return None

        start = self.client.post(
            f"world/combat/start/{candidate.monster['id']}",
            {},
        )

        if not start.ok:
            return None

        session_id = recursive_find(
            start.data,
            {
                "session_id",
                "combat_id",
                "sessionid",
                "combatid",
            },
        )

        if session_id is None:
            # Some APIs expose the session object with a generic id.
            session = recursive_find(
                start.data,
                {"session", "combat"},
            )
            if isinstance(session, dict):
                session_id = (
                    session.get("session_id")
                    or session.get("combat_id")
                    or session.get("id")
                )

        if session_id is None:
            self.logger.info(
                "[SKILL] Combat session format not recognized; skill mode skipped."
            )
            return None

        action_schema = self.runtime.setdefault(
            "combat_action_schema",
            {},
        )

        attack_templates = [
            {"action": "attack"},
            {"type": "attack"},
        ]
        skill_templates = [
            {"action": "skill", "skill_id": skill.get("id") or skill.get("skill_id")},
            {"type": "skill", "skill_id": skill.get("id") or skill.get("skill_id")},
            {"action": "use_skill", "skill_id": skill.get("id") or skill.get("skill_id")},
        ]

        if isinstance(action_schema.get("attack"), int):
            index = int(action_schema["attack"])
            attack_indexes = [index] if 0 <= index < len(attack_templates) else []
        else:
            attack_indexes = list(range(len(attack_templates)))

        if isinstance(action_schema.get("skill"), int):
            index = int(action_schema["skill"])
            skill_indexes = [index] if 0 <= index < len(skill_templates) else []
        else:
            skill_indexes = list(range(len(skill_templates)))

        current_data = start.data
        total_damage_taken = 0
        turns = 0

        while turns < int(self.config["skills"]["maximum_combat_turns"]):
            status_value = recursive_find(
                current_data,
                {"status", "result", "outcome"},
            )
            status_text = str(status_value or "").lower()

            if status_text in {
                "victory",
                "won",
                "win",
                "defeat",
                "dead",
                "finished",
                "completed",
            }:
                return APIResult(
                    status_text in {"victory", "won", "win", "finished", "completed"},
                    200,
                    current_data,
                    None if status_text not in {"defeat", "dead"} else status_text,
                )

            enemy_hp = recursive_find(
                current_data,
                {"enemy_hp", "monster_hp", "target_hp"},
            )
            player_mp = recursive_find(
                current_data,
                {"player_mp", "current_mp", "mp"},
            )
            player_hp = recursive_find(
                current_data,
                {"player_hp", "current_hp", "hp"},
            )

            try:
                current_mp = int(player_mp)
            except (TypeError, ValueError):
                current_mp = int(self.get_character().get("mp") or 0)

            try:
                current_hp = int(player_hp)
            except (TypeError, ValueError):
                current_hp = int(self.get_character().get("hp") or 0)

            if current_hp <= int(
                self.config["combat"]["interactive_emergency_hp"]
            ):
                self.logger.info(
                    "[SKILL] Interactive HP is low; stopping session actions."
                )
                return APIResult(False, 200, current_data, "interactive_hp_low")

            use_skill = current_mp >= required_mp

            if use_skill:
                templates = skill_templates
                indexes = skill_indexes
                schema_key = "skill"
            else:
                templates = attack_templates
                indexes = attack_indexes
                schema_key = "attack"

            accepted: APIResult | None = None

            for schema_index in indexes:
                body = templates[schema_index]
                action = self.client.post(
                    f"world/combat/{session_id}/action",
                    body,
                )

                if action.ok:
                    action_schema[schema_key] = schema_index
                    save_json(RUNTIME_STATE_FILE, self.runtime)
                    accepted = action
                    break

                if action.status not in {400, 404, 422}:
                    return action

            if accepted is None:
                self.logger.info(
                    "[SKILL] Combat action format not recognized."
                )
                return APIResult(False, 422, current_data, "action_schema_unknown")

            previous_hp = current_hp
            current_data = accepted.data
            turns += 1

            next_hp = recursive_find(
                current_data,
                {"player_hp", "current_hp", "hp"},
            )
            try:
                next_hp_int = int(next_hp)
                total_damage_taken += max(0, previous_hp - next_hp_int)
            except (TypeError, ValueError):
                pass

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

        return APIResult(
            False,
            408,
            current_data,
            "maximum_combat_turns_reached",
        )

    def execute_fight(
        self,
        candidate: FarmCandidate,
    ) -> bool:
        character = self.get_character()
        high_priority = candidate.priority <= 1
        monster = candidate.monster
        monster_id = int(monster.get("id") or 0)

        if monster_id <= 0:
            return False

        task_label = (
            f"{candidate.reason}: "
            f"{monster.get('name_en') or monster.get('name')}"
        )

        if task_label != self.last_task_label:
            self.logger.info(
                "[TASK] %s | damage~%s | Gold/STM %.2f",
                task_label,
                candidate.predicted_damage,
                candidate.gold_per_stamina,
            )
            self.last_task_label = task_label

        use_skill_mode = (
            self.config["skills"]["use_mp_skills"]
            and high_priority
            and (
                monster.get("is_boss")
                or candidate.predicted_damage
                >= int(self.config["skills"]["skill_mode_damage_threshold"])
            )
        )

        result: APIResult | None = None

        if use_skill_mode:
            result = self.interactive_combat(candidate)

            if result is not None:
                self.logger.info(
                    "[SKILL] MP combat used for %s.",
                    monster.get("name_en") or monster.get("name"),
                )

        if result is None:
            result = self.client.post(f"world/fight/{monster_id}")

        self.record(
            "fight",
            result.ok,
            {
                "zone_id": candidate.zone_id,
                "monster_id": monster_id,
                "monster": monster.get("name_en") or monster.get("name"),
                "reason": candidate.reason,
                "skill_mode": use_skill_mode,
                "predicted_damage": candidate.predicted_damage,
                "status": result.status,
                "error": result.error,
                "response": result.data,
            },
        )

        if not result.ok:
            self.logger.info(
                "[STOP] Fight failed: status=%s error=%s",
                result.status,
                result.error,
            )
            return False

        damage_taken = int(
            deep_find_number(
                result.data,
                {"damage_taken", "total_damage_taken"},
            )
            or 0
        )
        gold_gained = int(
            deep_find_number(
                result.data,
                {"gold_gained", "gold_reward"},
            )
            or 0
        )

        self.update_damage_history(monster_id, damage_taken)
        self.total_battles += 1
        self.total_gold_gained += gold_gained

        every = int(self.config["logging"]["battle_summary_every"])

        if self.total_battles % every == 0:
            refreshed = self.get_character()
            self.log_status(
                "FARM",
                refreshed,
                (
                    f"Battles {self.total_battles} | "
                    f"last {monster.get('name_en') or monster.get('name')} | "
                    f"damage {damage_taken} | +{gold_gained} Gold"
                ),
            )

        return True

    def resource_wait_seconds(
        self,
        character: dict[str, Any],
        required_hp: int | None,
    ) -> tuple[float, str]:
        hp = int(character.get("hp") or 0)
        hp_max = max(1, int(character.get("hp_max") or 1))
        stamina = int(character.get("stamina") or 0)

        target_hp = max(
            int(required_hp or 0),
            int(
                hp_max
                * float(self.config["continuous"]["resume_hp_percent"])
                / 100
            ),
        )
        target_stamina = int(
            self.config["continuous"]["resume_stamina"]
        )

        hp_per_hour = float(character.get("hp_regen_per_hour") or 0)
        stamina_per_hour = float(
            character.get("stamina_regen_per_hour") or 0
        )

        hp_seconds = 0.0
        stamina_seconds = 0.0

        if hp < target_hp:
            if hp_per_hour > 0:
                hp_seconds = (target_hp - hp) / hp_per_hour * 3600
            else:
                hp_seconds = float(
                    self.config["continuous"]["fallback_wait_seconds"]
                )

        if stamina < target_stamina:
            if stamina_per_hour > 0:
                stamina_seconds = (
                    (target_stamina - stamina)
                    / stamina_per_hour
                    * 3600
                )
            else:
                stamina_seconds = float(
                    self.config["continuous"]["fallback_wait_seconds"]
                )

        reasons = []

        if hp_seconds > 0:
            reasons.append(f"HP {hp}/{target_hp}")
        if stamina_seconds > 0:
            reasons.append(f"STM {stamina}/{target_stamina}")

        return (
            max(hp_seconds, stamina_seconds),
            ", ".join(reasons) or "resources ready",
        )

    def wait_for_resources(
        self,
        required_hp: int | None,
        has_priority_tasks: bool,
    ) -> None:
        poll_seconds = int(
            self.config["continuous"]["poll_seconds"]
        )
        wait_announced = False

        while True:
            character = self.get_character()

            if self.use_stamina_potion_if_worthwhile(
                character,
                has_priority_tasks=has_priority_tasks,
            ):
                time.sleep(
                    float(
                        self.config["automation"]["action_delay_seconds"]
                    )
                )
                continue

            wait_seconds, reason = self.resource_wait_seconds(
                character,
                required_hp,
            )

            if wait_seconds <= 0:
                self.log_status(
                    "READY",
                    character,
                    "farming resumed",
                )
                return

            if not wait_announced:
                self.logger.info(
                    "[WAIT] %s | automatic recovery mode",
                    reason,
                )
                wait_announced = True

            sleep_for = min(
                poll_seconds,
                max(30, int(wait_seconds)),
            )
            self.total_wait_seconds += sleep_for
            time.sleep(sleep_for)

    def run_farming_batch(
        self,
        material_needs: dict[str, int],
    ) -> None:
        maximum_battles = int(
            self.config["continuous"]["max_battles_per_batch"]
        )
        reserve_stamina = int(
            self.config["continuous"]["minimum_stamina_reserve"]
        )
        battles_this_batch = 0

        while battles_this_batch < maximum_battles:
            character = self.get_character()

            if str(character.get("status", "")).lower() != "alive":
                self.logger.info("[STOP] Character is not alive.")
                return

            objectives = self.objective_rows()
            candidates = self.build_farm_candidates(
                character,
                objectives,
                material_needs,
            )

            if not candidates:
                self.logger.info("[PAUSE] No eligible farm target.")
                return

            safe_candidate = next(
                (
                    row
                    for row in candidates
                    if int(character.get("hp") or 0) >= row.required_hp
                ),
                None,
            )

            high_priority_candidate = candidates[0]
            has_priority_tasks = high_priority_candidate.priority <= 3

            if safe_candidate is None:
                high_priority = high_priority_candidate.priority <= 1

                if self.use_hp_potions_until_safe(
                    high_priority_candidate.required_hp,
                    high_priority=high_priority,
                ):
                    continue

                return

            stamina = int(character.get("stamina") or 0)
            stamina_cost = int(
                safe_candidate.monster.get("stamina_cost") or 0
            )

            if stamina - stamina_cost < reserve_stamina:
                if self.use_stamina_potion_if_worthwhile(
                    character,
                    has_priority_tasks=has_priority_tasks,
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
                safe_candidate.zone_id,
            )

            if travelled is None:
                return

            refreshed = self.get_character()

            if int(refreshed.get("hp") or 0) < safe_candidate.required_hp:
                continue

            if not self.execute_fight(safe_candidate):
                return

            battles_this_batch += 1

            time.sleep(float(self.config["automation"]["action_delay_seconds"]))

            self.claim_free_rewards()

            # Recheck crafting periodically instead of after every fight.
            craft_interval = int(
                self.config["logging"]["craft_recheck_every_battles"]
            )
            if (
                safe_candidate.material_score > 0
                and self.total_battles % craft_interval == 0
            ):
                material_needs.update(
                    self.complete_craft_quests()
                )

    def run_cycle(self) -> None:
        character = self.get_character()
        self.log_status(
            "CYCLE",
            character,
            "free progression and Gold cycle",
        )

        self.claim_free_rewards()
        self.start_all_free_quests()
        self.optimize_progression()

        material_needs = self.complete_craft_quests()
        self.run_farming_batch(material_needs)

        self.claim_free_rewards()
        self.complete_craft_quests()
        self.optimize_progression()

    def report(self) -> dict[str, Any]:
        final_character = self.get_character()

        report = {
            "generated_at": utc_now(),
            "version": VERSION,
            "windows_only": True,
            "paid_systems_enabled": False,
            "battles": self.total_battles,
            "wait_seconds": self.total_wait_seconds,
            "gold_gained_observed": self.total_gold_gained,
            "gold_spent": self.total_gold_spent,
            "hp_potions_used": self.hp_potions_used,
            "mana_potions_used": self.mp_potions_used,
            "stamina_potions_used": self.stamina_potions_used,
            "boxes_opened": self.boxes_opened,
            "equipment_changes": self.equipment_changes,
            "forge_upgrades": self.upgrades_completed,
            "crafts_completed": self.crafts_completed,
            "attribute_points_spent": self.attribute_points_spent,
            "initial": sanitize(self.initial_character or {}),
            "final": sanitize(final_character),
            "actions": self.actions,
        }

        save_json(LAST_REPORT_FILE, report)

        timestamped = OUTPUT_DIR / (
            "eldoria_bot_v1_3_1_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        save_json(timestamped, report)

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

        self.logger.info("[START] Eldoria Bot %s", VERSION)
        self.logger.info(
            "[RULES] Real-money, VIP, Battle Pass and Gem-market spending are blocked."
        )
        self.logger.info(
            "[MODE] HP/MP/Stamina consumables are used only when strategically useful."
        )
        self.log_status("START", self.initial_character)

        while True:
            self.run_cycle()

            if not self.config["continuous"]["enabled"]:
                break

            character = self.get_character()
            objectives = self.objective_rows()
            material_needs = self.complete_craft_quests()
            candidates = self.build_farm_candidates(
                character,
                objectives,
                material_needs,
            )

            required_hp = candidates[0].required_hp if candidates else None
            has_priority_tasks = any(
                row.objective_type in {"kill", "craft", "loot"}
                for row in objectives
            )

            self.wait_for_resources(
                required_hp=required_hp,
                has_priority_tasks=has_priority_tasks,
            )

        self.report()


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

    config = load_json(CONFIG_FILE, {})
    logger = configure_logging()

    try:
        client = APIClient(config, logger)
        bot = EldoriaBot(client, config, logger)
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
