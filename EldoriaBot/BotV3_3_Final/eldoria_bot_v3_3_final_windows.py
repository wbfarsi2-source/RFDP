from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import re
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCRIPT_DIR = Path(__file__).resolve().parent
V32_FILE = SCRIPT_DIR / "eldoria_bot_v3_2_base.py"
CONFIG_FILE = SCRIPT_DIR / "eldoria_bot_v3_3_final_config.json"

DESKTOP = Path.home() / "Desktop"
DEFAULT_ELDORIA_ROOT = DESKTOP / "Eldoria_Bot"
_ACCOUNT_ROOT_ENV = os.environ.get("ELDORIA_ACCOUNT_ROOT", "").strip()
if _ACCOUNT_ROOT_ENV:
    ELDORIA_ROOT = Path(_ACCOUNT_ROOT_ENV).expanduser().resolve()
else:
    ELDORIA_ROOT = DEFAULT_ELDORIA_ROOT
PRIVATE_DIR = ELDORIA_ROOT / "Private"
OUTPUT_DIR = ELDORIA_ROOT / "Output"
PROJECT_DIR = ELDORIA_ROOT / "BotV3_3_Final"
STATE_DIR = PROJECT_DIR / "State"
LOG_DIR = PROJECT_DIR / "Logs"

LIVE_LOG_FILE = OUTPUT_DIR / "eldoria_bot_v3_3_final.log"
CURRENT_PLAN_FILE = OUTPUT_DIR / "eldoria_bot_current_plan.txt"
INSTANCE_LOCK_FILE = STATE_DIR / "eldoria_bot_v3_3.lock"
FORBIDDEN_ENDPOINT = "https://eldoriaworld.com/terms.html"

if not V32_FILE.exists():
    raise RuntimeError(f"Required file is missing: {V32_FILE}")

spec = importlib.util.spec_from_file_location(
    "eldoria_v32_base",
    V32_FILE,
)
if spec is None or spec.loader is None:
    raise RuntimeError("The Eldoria V3.2 base could not be loaded.")

v32 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v32
spec.loader.exec_module(v32)

v31 = v32.v31
v30 = v32.v30
v29 = v32.v29
v281 = v32.v281
v271 = v32.v271
v27 = v32.v27
v26 = v32.v26
v25 = v32.v25
v24 = v32.v24
v232 = v32.v232
v22 = v32.v22
v21 = v32.v21
v161 = v32.v161
base = v32.base
engine = v32.engine

ALL_MODULES = (
    v32, v31, v30, v29, v281, v271, v27, v26,
    v25, v24, v232, v22, v21, v161, base, engine,
)

for module in ALL_MODULES:
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
        OUTPUT_DIR / "eldoria_bot_v3_3_final_last_report.json"
    )
    module.LOG_COPY_FILE = LIVE_LOG_FILE

for module in (
    v32, v31, v30, v29, v281, v271, v27, v26,
    v25, v24, v232, v22, v21, v161, base,
):
    module.STATE_DIR = STATE_DIR
    module.OUTPUT_DIR = OUTPUT_DIR
    module.LOG_DIR = LOG_DIR
    module.CONFIG_FILE = CONFIG_FILE

for module in (v27, v271, v281, v29, v30, v31, v32):
    module.LIVE_LOG_FILE = LIVE_LOG_FILE
    module.CURRENT_PLAN_FILE = CURRENT_PLAN_FILE


_JSON_WRITE_LOCK = threading.RLock()
_ORIGINAL_SAVE_JSON = engine.save_json


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def atomic_save_json(path: Any, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    payload = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        default=json_default,
    )
    with _JSON_WRITE_LOCK:
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            last_error = None
            for attempt in range(5):
                try:
                    os.replace(temp, target)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass


def install_atomic_json_saving() -> None:
    engine.save_json = atomic_save_json
    for module in ALL_MODULES:
        if hasattr(module, "save_json"):
            try:
                setattr(module, "save_json", atomic_save_json)
            except Exception:
                pass


def endpoint_is_forbidden(url: Any) -> bool:
    try:
        parsed = urlsplit(str(url))
    except Exception:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = (parsed.path or "/").lower()
    return host == "eldoriaworld.com" and path.rstrip("/") == "/terms.html"


def install_forbidden_endpoint_guard(logger: logging.Logger) -> None:
    try:
        import requests

        if not getattr(requests.sessions.Session, "_eldoria_guarded", False):
            original = requests.sessions.Session.request

            def guarded_request(session, method, url, *args, **kwargs):
                if endpoint_is_forbidden(url):
                    raise RuntimeError(
                        "Blocked forbidden Eldoria endpoint by local safety policy."
                    )
                return original(session, method, url, *args, **kwargs)

            requests.sessions.Session.request = guarded_request
            requests.sessions.Session._eldoria_guarded = True
    except Exception as exc:
        logger.warning("[SAFETY] Requests guard could not be installed: %s", exc)

    try:
        import urllib.request

        if not getattr(urllib.request, "_eldoria_guarded", False):
            original_urlopen = urllib.request.urlopen

            def guarded_urlopen(url, *args, **kwargs):
                candidate = getattr(url, "full_url", url)
                if endpoint_is_forbidden(candidate):
                    raise RuntimeError(
                        "Blocked forbidden Eldoria endpoint by local safety policy."
                    )
                return original_urlopen(url, *args, **kwargs)

            urllib.request.urlopen = guarded_urlopen
            urllib.request._eldoria_guarded = True
    except Exception as exc:
        logger.warning("[SAFETY] urllib guard could not be installed: %s", exc)


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(str(os.getpid()).encode("ascii", errors="ignore"))
            self.handle.flush()
            return True
        except (OSError, BlockingIOError):
            self.release()
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self.handle.close()
        finally:
            self.handle = None


class RedactingFormatter(logging.Formatter):
    _patterns = (
        (
            re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
            r"\1<REDACTED>",
        ),
        (
            re.compile(r"(?i)((?:cookie|token|password|secret)\s*[:=]\s*)[^\s,;]+"),
            r"\1<REDACTED>",
        ),
        (
            re.compile(r"(?i)(set-cookie\s*:\s*).+"),
            r"\1<REDACTED>",
        ),
        (
            re.compile(
                r"(?i)\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
                r"(?:\.[A-Za-z0-9_-]{10,})?\b"
            ),
            "<JWT_REDACTED>",
        ),
    )

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text


def configure_logging(config: dict[str, Any]):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("eldoria_bot_v3_3_final")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = RedactingFormatter(
        "%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    log_config = config.get("logging", {})
    max_bytes = max(
        1_000_000,
        as_int(log_config.get("max_file_bytes"), 10_000_000),
    )
    backup_count = max(
        1,
        as_int(log_config.get("backup_count"), 5),
    )

    file_handler = RotatingFileHandler(
        LIVE_LOG_FILE,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def deep_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_defaults(target[key], value)


def prepare_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a JSON object.")

    deep_defaults(
        config,
        {
            "logging": {
                "max_file_bytes": 10_000_000,
                "backup_count": 5,
            },
            "progress_first": {
                "recent_sample_window": 12,
                "recent_outlier_cap_multiplier": 1.20,
                "recent_upper_margin": 1.08,
                "recent_upper_flat_buffer": 4,
                "recent_max_margin": 1.05,
                "prediction_floor_start_multiplier": 1.02,
                "prediction_floor_min_multiplier": 0.82,
                "prediction_calibration_samples": 8,
                "recent_stability_cv_threshold": 0.25,
                "aggregate_prediction_floor_multiplier": 0.92,
                "aggregate_average_multiplier": 1.12,
                "aggregate_flat_buffer": 6,
                "unproven_prediction_multiplier": 1.10,
                "minimum_recent_samples_for_proven": 3,
                "minimum_aggregate_samples_for_proven": 5,
                "campaign_switch_ratio": 0.82,
                "damage_log_heartbeat_seconds": 1800,
                "damage_state_flush_seconds": 120,
            },
            "deadline_priority": {
                "enabled": True,
                "daily_preemption": True,
                "quest_type_multipliers": {
                    "urgent": 0.20,
                    "daily": 0.48,
                    "weekly": 1.00,
                    "normal": 1.15,
                    "other": 1.25,
                },
                "objective_type_multipliers": {
                    "kill": 0.82,
                    "craft": 0.92,
                    "loot": 1.00,
                    "other": 1.08,
                },
                "deadline_impossible_penalty": 1.75,
                "deadline_close_multiplier": 0.35,
                "minimum_switch_improvement": 0.82,
            },
        },
    )

    required_sections = (
        "continuous",
        "combat",
        "active_scheduler",
        "network",
        "no_death",
        "progress_first",
    )
    missing = [name for name in required_sections if not isinstance(config.get(name), dict)]
    if missing:
        raise ValueError(
            "Missing or invalid configuration sections: " + ", ".join(missing)
        )

    for section, key in (
        ("continuous", "poll_seconds"),
        ("active_scheduler", "poll_seconds"),
        ("network", "read_timeout_seconds"),
        ("network", "write_timeout_seconds"),
    ):
        if as_float(config[section].get(key), 0.0) <= 0:
            raise ValueError(f"{section}.{key} must be greater than zero.")

    return config


class ProgressFirstSafetyDirector(v32.NoDeathEfficiencyDirector):
    VERSION = "3.4-root-hardened-progress-director-windows"

    def __init__(self, client, config, logger) -> None:
        super().__init__(client, config, logger)

        self.progress_file = STATE_DIR / "progress_first_safety_state.json"
        self.progress_state = engine.load_json(
            self.progress_file,
            {
                "schema_version": 2,
                "guaranteed_over_random_switches": 0,
                "robust_damage_estimates": 0,
                "last_damage_signature": "",
                "last_damage_at": 0.0,
                "damage_log_cache": {},
                "damage_calibrations": 0,
                "deadline_preemptions": 0,
            },
        )
        if not isinstance(self.progress_state, dict):
            self.progress_state = {}

        defaults = {
            "schema_version": 2,
            "guaranteed_over_random_switches": 0,
            "robust_damage_estimates": 0,
            "last_damage_signature": "",
            "last_damage_at": 0.0,
            "damage_log_cache": {},
            "damage_calibrations": 0,
            "deadline_preemptions": 0,
        }
        for key, default in defaults.items():
            self.progress_state.setdefault(key, default)

        if not isinstance(self.progress_state.get("damage_log_cache"), dict):
            self.progress_state["damage_log_cache"] = {}

        self._damage_log_cache: dict[str, dict[str, Any]] = dict(
            self.progress_state.get("damage_log_cache", {})
        )
        self._last_damage_state_save_at = time.time()
        self._progress_state_dirty = False
        self.flush_progress_state(force=True)

    def flush_progress_state(self, force: bool = False) -> None:
        now = time.time()
        interval = max(
            30.0,
            as_float(
                self.config["progress_first"].get(
                    "damage_state_flush_seconds",
                    120,
                ),
                120.0,
            ),
        )
        if not force and (
            not self._progress_state_dirty
            or now - self._last_damage_state_save_at < interval
        ):
            return

        self.progress_state["schema_version"] = 2
        self.progress_state["damage_log_cache"] = self._damage_log_cache
        engine.save_json(self.progress_file, self.progress_state)
        self._last_damage_state_save_at = now
        self._progress_state_dirty = False

    def save_progress_state(self) -> None:
        self._progress_state_dirty = True
        self.flush_progress_state(force=True)

    def recent_damage_profile(
        self,
        monster_id: int,
        character: dict[str, Any],
    ) -> dict[str, float] | None:
        samples = self.combat_sample_rows(monster_id)
        if not isinstance(samples, list) or not samples:
            return None

        cfg = self.config["progress_first"]
        window = max(3, as_int(cfg.get("recent_sample_window"), 12))
        current_power = max(
            1.0,
            as_float(self.current_power(character), 1.0),
        )
        current_level = max(1, as_int(character.get("level"), 1))

        scaled: list[float] = []
        for sample in samples[-window:]:
            if not isinstance(sample, dict):
                continue
            damage = max(0.0, as_float(sample.get("damage"), 0.0))
            if damage <= 0:
                continue

            sample_level = max(
                1,
                as_int(sample.get("level"), current_level),
            )
            if abs(sample_level - current_level) > 3:
                continue

            sample_power = max(
                1.0,
                as_float(sample.get("power"), current_power),
            )
            power_ratio = clamp(sample_power / current_power, 0.60, 1.50)
            scaled.append(damage * math.sqrt(power_ratio))

        if not scaled:
            return None

        scaled.sort()
        count = len(scaled)
        p80_index = max(0, min(count - 1, math.ceil(count * 0.80) - 1))
        median = statistics.median(scaled)
        mean = statistics.mean(scaled)
        maximum = max(scaled)
        stdev = statistics.pstdev(scaled) if count > 1 else 0.0
        cv = stdev / mean if mean > 0 else 1.0
        robust = min(
            scaled[p80_index],
            median * as_float(cfg.get("recent_outlier_cap_multiplier"), 1.20),
        )
        upper = max(
            robust * as_float(cfg.get("recent_upper_margin"), 1.08)
            + as_float(cfg.get("recent_upper_flat_buffer"), 4.0),
            maximum * as_float(cfg.get("recent_max_margin"), 1.05),
        )

        return {
            "count": float(count),
            "median": median,
            "mean": mean,
            "maximum": maximum,
            "stdev": stdev,
            "cv": cv,
            "robust": robust,
            "upper": upper,
        }

    def calibrated_prediction_floor(
        self,
        predicted: float,
        profile: dict[str, float],
    ) -> tuple[float, float]:
        cfg = self.config["progress_first"]
        start = as_float(cfg.get("prediction_floor_start_multiplier"), 1.02)
        minimum = as_float(cfg.get("prediction_floor_min_multiplier"), 0.82)
        sample_target = max(
            3,
            as_int(cfg.get("prediction_calibration_samples"), 8),
        )
        count = as_int(profile.get("count"), 0)
        cv = max(0.0, as_float(profile.get("cv"), 1.0))
        cv_threshold = max(
            0.05,
            as_float(cfg.get("recent_stability_cv_threshold"), 0.25),
        )

        sample_progress = clamp(count / sample_target, 0.0, 1.0)
        stability = clamp(1.0 - cv / cv_threshold, 0.0, 1.0)
        if count >= sample_target and cv <= cv_threshold:
            stability = max(stability, 0.75)
        strength = sample_progress * stability
        multiplier = start - (start - minimum) * strength
        return predicted * multiplier, multiplier

    def conservative_damage_estimate(
        self,
        row: dict[str, Any],
        candidate,
    ) -> tuple[float, bool]:
        character = (
            self._scheduler_character
            if isinstance(getattr(self, "_scheduler_character", None), dict)
            else {}
        )
        monster_id = as_int(candidate.monster.get("id"), 0)
        predicted = max(0.0, as_float(candidate.predicted_damage, 0.0))
        cfg = self.config["progress_first"]

        profile = self.recent_damage_profile(monster_id, character)
        if profile is not None:
            prediction_floor, floor_multiplier = self.calibrated_prediction_floor(
                predicted,
                profile,
            )
            recent_upper = profile["upper"]
            estimate = max(prediction_floor, recent_upper)
            recent_count = as_int(profile.get("count"), 0)
            proven = (
                recent_count
                >= as_int(cfg.get("minimum_recent_samples_for_proven"), 3)
                and profile["cv"]
                <= as_float(cfg.get("recent_stability_cv_threshold"), 0.25)
            )
            dominant = "recent-upper" if recent_upper >= prediction_floor else "prediction-floor"
            source = (
                f"recent-calibrated/{recent_count} {dominant} "
                f"pred={predicted:.0f} upper={recent_upper:.0f} "
                f"floor={floor_multiplier:.2f}"
            )
            self.log_damage_model_once(candidate, estimate, source)
            return estimate, proven

        aggregate = self.smart_state.get(
            "successful_damage",
            {},
        ).get(str(monster_id))
        if isinstance(aggregate, dict) and as_int(aggregate.get("count"), 0) > 0:
            average = max(0.0, as_float(aggregate.get("average"), 0.0))
            estimate = max(
                predicted
                * as_float(
                    cfg.get("aggregate_prediction_floor_multiplier"),
                    0.92,
                ),
                average
                * as_float(cfg.get("aggregate_average_multiplier"), 1.12)
                + as_float(cfg.get("aggregate_flat_buffer"), 6.0),
            )
            count = as_int(aggregate.get("count"), 0)
            proven = count >= as_int(
                cfg.get("minimum_aggregate_samples_for_proven"),
                5,
            )
            self.log_damage_model_once(
                candidate,
                estimate,
                f"aggregate-calibrated/{count} pred={predicted:.0f} avg={average:.0f}",
            )
            return estimate, proven

        estimate = predicted * as_float(
            cfg.get("unproven_prediction_multiplier"),
            1.10,
        )
        self.log_damage_model_once(
            candidate,
            estimate,
            f"prediction-only pred={predicted:.0f}",
        )
        return estimate, False

    def log_damage_model_once(
        self,
        candidate,
        estimate: float,
        source: str,
    ) -> None:
        monster_key = str(
            candidate.monster.get("id")
            or self.monster_name(candidate)
            or "unknown"
        )
        signature = f"{source}|{round(estimate)}"
        now = time.time()
        heartbeat = max(
            60.0,
            as_float(
                self.config["progress_first"].get(
                    "damage_log_heartbeat_seconds",
                    1800,
                ),
                1800.0,
            ),
        )

        previous = self._damage_log_cache.get(monster_key, {})
        last_signature = str(previous.get("signature") or "")
        last_at = as_float(previous.get("at"), 0.0)
        if signature == last_signature and now - last_at < heartbeat:
            self.flush_progress_state(force=False)
            return

        self._damage_log_cache[monster_key] = {
            "signature": signature,
            "at": now,
        }
        self.progress_state["last_damage_signature"] = f"{monster_key}|{signature}"
        self.progress_state["last_damage_at"] = now
        self.progress_state["robust_damage_estimates"] = (
            as_int(self.progress_state.get("robust_damage_estimates"), 0) + 1
        )
        if source.startswith("recent-calibrated"):
            self.progress_state["damage_calibrations"] = (
                as_int(self.progress_state.get("damage_calibrations"), 0) + 1
            )
        self._progress_state_dirty = True
        self.flush_progress_state(force=False)

        self.logger.info(
            "[DAMAGE MODEL] %s | estimate %.0f | source %s.",
            self.monster_name(candidate),
            estimate,
            source,
        )

    @staticmethod
    def record_is_viable(record) -> bool:
        row = record.get("best_row")
        return bool(
            math.isfinite(record.get("expected", float("inf")))
            and isinstance(row, dict)
            and row.get("state") in {"ready", "heal", "resource"}
            and not row.get("no_death_blocked")
        )

    @staticmethod
    def objective_field(objective: Any, name: str) -> Any:
        if isinstance(objective, dict):
            return objective.get(name)
        value = getattr(objective, name, None)
        if value is not None:
            return value
        for nested_name in ("quest", "raw", "data", "payload"):
            nested = getattr(objective, nested_name, None)
            if isinstance(nested, dict) and name in nested:
                return nested.get(name)
        return None

    @staticmethod
    def parse_duration_seconds(value: Any) -> float | None:
        numeric = as_float(value, -1.0)
        if numeric >= 0:
            return numeric
        if not isinstance(value, str):
            return None
        text = value.strip().lower()
        if not text:
            return None
        total = 0.0
        matched = False
        for amount, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)",
            text,
        ):
            matched = True
            number = float(amount)
            if unit.startswith("d"):
                total += number * 86400
            elif unit.startswith("h"):
                total += number * 3600
            elif unit.startswith("m"):
                total += number * 60
            else:
                total += number
        return total if matched else None

    def objective_deadline_remaining(self, objective: Any) -> float | None:
        now = time.time()
        absolute_names = (
            "expires_at",
            "expiration_at",
            "expiry_at",
            "deadline",
            "deadline_at",
            "end_at",
            "reset_at",
        )
        relative_names = (
            "expires_in",
            "expires_in_seconds",
            "remaining_seconds",
            "time_remaining",
        )

        for name in relative_names:
            value = self.objective_field(objective, name)
            seconds = self.parse_duration_seconds(value)
            if seconds is not None and seconds >= 0:
                return seconds

        for name in absolute_names:
            value = self.objective_field(objective, name)
            if value is None:
                continue
            if isinstance(value, datetime):
                timestamp = value.timestamp()
                return max(0.0, timestamp - now)
            numeric = as_float(value, -1.0)
            if numeric > 0:
                if numeric > 10_000_000_000:
                    numeric /= 1000.0
                if numeric > 1_000_000_000:
                    return max(0.0, numeric - now)
            if isinstance(value, str):
                text = value.strip().replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(text)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return max(0.0, parsed.timestamp() - now)
                except ValueError:
                    continue
        return None

    def quest_rank(self, objective: Any) -> int:
        quest_type = str(
            getattr(objective, "quest_type", "other") or "other"
        ).lower()
        return self.QUEST_TYPE_RANK.get(quest_type, 9)

    def quest_type_multiplier(self, objective: Any) -> float:
        cfg = self.config.get("deadline_priority", {})
        mapping = cfg.get("quest_type_multipliers", {})
        quest_type = str(getattr(objective, "quest_type", "other") or "other").lower()
        return as_float(mapping.get(quest_type, mapping.get("other", 1.25)), 1.25)

    def objective_type_multiplier(self, objective: Any) -> float:
        cfg = self.config.get("deadline_priority", {})
        mapping = cfg.get("objective_type_multipliers", {})
        objective_type = str(
            getattr(objective, "objective_type", "other") or "other"
        ).lower()
        return as_float(mapping.get(objective_type, mapping.get("other", 1.08)), 1.08)

    def priority_score(self, record: dict[str, Any]) -> float:
        objective = record["objective"]
        expected = as_float(record.get("effective"), float("inf"))
        if not math.isfinite(expected):
            return float("inf")

        cfg = self.config.get("deadline_priority", {})
        score = max(1.0, expected)
        score *= self.quest_type_multiplier(objective)
        score *= self.objective_type_multiplier(objective)

        deadline = self.objective_deadline_remaining(objective)
        record["deadline_remaining"] = deadline
        if deadline is not None and deadline > 0:
            if expected <= deadline:
                slack_ratio = clamp((deadline - expected) / deadline, 0.0, 1.0)
                close_multiplier = clamp(
                    as_float(cfg.get("deadline_close_multiplier"), 0.35),
                    0.10,
                    1.0,
                )
                score *= close_multiplier + (1.0 - close_multiplier) * slack_ratio
                record["deadline_feasible"] = True
            else:
                miss_ratio = expected / max(deadline, 1.0)
                score *= as_float(
                    cfg.get("deadline_impossible_penalty"),
                    1.75,
                ) + min(5.0, miss_ratio)
                record["deadline_feasible"] = False
        else:
            record["deadline_feasible"] = None

        if not self.record_is_viable(record):
            score *= 4.0
        record["root_priority_score"] = score
        return score

    def choose_campaign_objective(
        self,
        objectives,
        states,
        character: dict[str, Any],
    ):
        supported = self.supported_campaign_objectives(objectives)
        if not supported:
            self.clear_completed_campaign()
            return None

        records = [
            self.objective_priority_record(objective, states, character)
            for objective in supported
        ]
        active = [record for record in records if not record.get("paused")]
        if not active:
            active = records

        for record in records:
            self.priority_score(record)

        active.sort(
            key=lambda record: (
                record.get("root_priority_score", float("inf")),
                self.quest_rank(record["objective"]),
                record["objective"].remaining,
                record["objective"].quest_name,
            )
        )
        best = active[0]
        selected = best["objective"]
        selection_reason = "deadline-aware safe progress score"

        current = self.current_campaign_objective(supported)
        current_record = next(
            (
                record
                for record in records
                if current is not None
                and self.objective_key(record["objective"])
                == self.objective_key(current)
            ),
            None,
        )

        switch = current is None or current_record is None
        if current_record is not None:
            current_score = as_float(
                current_record.get("root_priority_score"),
                float("inf"),
            )
            best_score = as_float(
                best.get("root_priority_score"),
                float("inf"),
            )
            current_rank = self.quest_rank(current)
            selected_rank = self.quest_rank(selected)
            daily_preemption = bool(
                self.config.get("deadline_priority", {}).get(
                    "daily_preemption",
                    True,
                )
            )
            switch_ratio = clamp(
                as_float(
                    self.config.get("deadline_priority", {}).get(
                        "minimum_switch_improvement",
                        self.config["progress_first"].get(
                            "campaign_switch_ratio",
                            0.82,
                        ),
                    ),
                    0.82,
                ),
                0.30,
                0.98,
            )

            if current_record.get("paused"):
                switch = True
            elif not self.record_is_viable(current_record) and self.record_is_viable(best):
                switch = True
            elif daily_preemption and selected_rank < current_rank:
                switch = True
                selection_reason = "higher deadline class preempted current campaign"
            elif best_score < current_score * switch_ratio:
                switch = True

        if switch:
            previous_type = current.objective_type if current is not None else ""
            previous_rank = (
                self.QUEST_TYPE_RANK.get(current.quest_type, 9)
                if current is not None
                else 9
            )
            selected_rank = self.quest_rank(selected)
            self.set_campaign(selected, selection_reason)

            selected_type = str(selected.objective_type or "").lower()
            previous_type_normalized = str(previous_type or "").lower()
            if selected_type == "kill" and previous_type_normalized and previous_type_normalized != "kill":
                self.progress_state["guaranteed_over_random_switches"] = (
                    as_int(
                        self.progress_state.get("guaranteed_over_random_switches"),
                        0,
                    )
                    + 1
                )
                self._progress_state_dirty = True
            if selected_rank < previous_rank:
                self.progress_state["deadline_preemptions"] = (
                    as_int(self.progress_state.get("deadline_preemptions"), 0) + 1
                )
                self._progress_state_dirty = True
            self.flush_progress_state(force=False)
        elif current is not None:
            selected = current
            self.campaign["active_remaining"] = current.remaining
            self.save_campaign()

        chosen_record = next(
            (
                record
                for record in records
                if self.objective_key(record["objective"])
                == self.objective_key(selected)
            ),
            best,
        )
        expected_text = (
            v27.format_duration(chosen_record["expected"])
            if math.isfinite(chosen_record["expected"])
            else "blocked"
        )
        deadline = chosen_record.get("deadline_remaining")
        deadline_text = (
            f" | deadline {v27.format_duration(deadline)}"
            if isinstance(deadline, (int, float)) and deadline > 0
            else ""
        )
        self._priority_explanation = (
            f"{selected.quest_name}: "
            f"{selected.objective_type} | "
            f"{selected.remaining} remaining | "
            f"estimated completion {expected_text}"
            f"{deadline_text}"
        )
        self.log_priority_once()
        return selected

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
        with CURRENT_PLAN_FILE.open("a", encoding="utf-8") as handle:
            handle.write(
                "\nROOT-HARDENED SAFETY\n"
                "Quest selection is deadline-aware; Kill gets a bonus, not an absolute override.\n"
                "Damage uses calibrated recent upper bounds with a decaying prediction floor.\n"
                "Dangerous exact-target hard locks remain inherited and active.\n"
                "JSON state writes are atomic and duplicate bot instances are blocked.\n"
            )

    def final_report(self):
        self.flush_progress_state(force=True)
        report = super().final_report()
        report.update(
            {
                "version": self.VERSION,
                "progress_first_safety_state": self.progress_state,
                "root_hardening": {
                    "atomic_json_state": True,
                    "single_instance_lock": True,
                    "rotating_redacted_log": True,
                    "per_target_damage_log_deduplication": True,
                    "calibrated_recent_damage": True,
                    "deadline_aware_quest_priority": True,
                    "forbidden_endpoint_guard": True,
                },
            }
        )
        engine.save_json(
            OUTPUT_DIR / "eldoria_bot_v3_3_final_last_report.json",
            report,
        )
        engine.save_json(
            OUTPUT_DIR
            / (
                "eldoria_bot_v3_3_final_"
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

    install_atomic_json_saving()

    try:
        config = prepare_config(engine.load_json(CONFIG_FILE, {}))
    except Exception as exc:
        print(f"Invalid configuration: {exc}")
        return 2

    logger = configure_logging(config)
    install_forbidden_endpoint_guard(logger)

    instance_lock = SingleInstanceLock(INSTANCE_LOCK_FILE)
    if not instance_lock.acquire():
        logger.error(
            "[INSTANCE] Another Eldoria bot process is already running. "
            "The second instance was blocked."
        )
        return 3

    bot = None
    try:
        logger.info(
            "[START] Eldoria Bot %s",
            ProgressFirstSafetyDirector.VERSION,
        )
        logger.info(
            "[SAFETY] Atomic state, single-instance lock, redacted rotating log "
            "and forbidden-endpoint guard are active."
        )
        client = engine.APIClient(config, logger)
        bot = ProgressFirstSafetyDirector(client, config, logger)
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
        except Exception as exc:
            logger.error("[STATE] Final state flush failed: %s", exc)
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
