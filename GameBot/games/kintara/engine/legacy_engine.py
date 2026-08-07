#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Farm Mahi with Base/Sea fishing, cooking, and trading flows.

import getpass
import gzip
import json
import math
import os
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

try:
    import websocket
except ImportError:
    websocket = None


APP_VERSION = "Farm Mahi V3 + Base/Sea + Ember Spectator All Servers"
BASE = "https://kintara.gg"
ENV_FILE = Path(".env")
ERROR_LOG = Path("farm_mahi_errors.txt")
LOCATION_SETTINGS_FILE = Path(__file__).resolve().with_name("farm_mahi_location_settings.json")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

SPOT = {
    "x": 0.5,
    "y": 0.25,
    "z": 6.5,
    "ry": -2.677945044588987,
    "fc": 19,
    "fr": 24,
}

FISH_HOOK_SWITCH_EVERY = 50
FISH_DAILY_LIMIT_SECONDS = 19 * 60 * 60
FISH_DAILY_ENV_DATE_KEY = "FISH_DAILY_UTC_DATE"
FISH_DAILY_ENV_SECONDS_KEY = "FISH_DAILY_USED_SECONDS"
FISH_DAILY_LIMIT_MESSAGE = "FISH daily 19-hour limit reached. Fishing is paused; wait until 00:00 UTC."
FISH_DAILY_PERSIST_INTERVAL_SECONDS = 1.0
MIN_SERVER_NUMBER = 9
NEW_SERVER_DELAY_MIN_SECONDS = 60.0
NEW_SERVER_DELAY_MAX_SECONDS = 120.0
POST_SERVER_JOIN_WAIT_SECONDS = 10.0
SERVER_JOIN_COOK_COUNT = 1
JOIN_COOK_ATTEMPTS = 15
JOIN_COOK_ATTEMPT_DELAY_SECONDS = 1.0
JOIN_LOCATION_PRIME_MESSAGES = 1
JOIN_LOCATION_PRIME_DELAY_SECONDS = 0.0

BASE_FISH_LOCATIONS = [
    {
        "key": "cook_fish_1",
        "kind": "base",
        "name": "Base 1 | Cook/Fish | x=0.5 z=6.5",
        "hooks": [
            {"x": 0.5, "y": 0.25, "z": 6.5, "ry": -2.677945044588987, "fc": 19, "fr": 24, "region": "pond"},
            {"x": 0.5, "y": 0.25, "z": 6.5, "ry": 3.141592653589793, "fc": 20, "fr": 24, "region": "pond"},
            {"x": 0.5, "y": 0.25, "z": 6.5, "ry": -2.356194490192345, "fc": 18, "fr": 24, "region": "pond"},
        ],
    },
    {
        "key": "cook_fish_2",
        "kind": "base",
        "name": "Base 2 | Cook/Fish | x=-7.5 z=-5.5",
        "hooks": [
            {"x": -7.5, "y": 0.25, "z": -5.5, "ry": 0.982793723247329, "fc": 15, "fr": 16, "region": "pond"},
            {"x": -7.5, "y": 0.25, "z": -5.5, "ry": 1.2490457723982544, "fc": 15, "fr": 15, "region": "pond"},
            {"x": -7.5, "y": 0.25, "z": -5.5, "ry": 0.7853981633974483, "fc": 15, "fr": 17, "region": "pond"},
        ],
    },
    {
        "key": "cook_fish_3",
        "kind": "base",
        "name": "Base 3 | Cook/Fish | x=-3.5 z=6.5",
        "hooks": [
            {"x": -3.5, "y": 0.25, "z": 6.5, "ry": 3.141592653589793, "fc": 16, "fr": 24, "region": "pond"},
            {"x": -3.5, "y": 0.25, "z": 6.5, "ry": 3.141592653589793, "fc": 16, "fr": 23, "region": "pond"},
        ],
    },
]

SEA_FISH_LOCATIONS = [
    {
        "key": "sea_1",
        "kind": "sea",
        "name": "Sea 1 | Beach | x=4.5 z=13.5",
        "land": {
            "x": 4.5,
            "y": 0.215,
            "z": 13.5,
            "ry": 0.7853981633974483,
            "region": "beach",
        },
        "hooks": [
            {"x": 4.5, "y": 0.215, "z": 13.5, "ry": 1.5707963267948966, "fc": 25, "fr": 33, "fph": 0, "region": "beach"},
            {"x": 4.5, "y": 0.215, "z": 13.5, "ry": 1.5707963267948966, "fc": 26, "fr": 33, "fph": 0, "region": "beach"},
            {"x": 4.5, "y": 0.215, "z": 13.5, "ry": 1.892546881191539, "fc": 27, "fr": 32, "fph": 0, "region": "beach"},
        ],
    },
    {
        "key": "sea_2",
        "kind": "sea",
        "name": "Sea 2 | Beach | x=1.5 z=1.5",
        "land": {
            "x": 1.5,
            "y": 0.25,
            "z": 1.5,
            "ry": 0.7853981633974483,
            "region": "beach",
        },
        "hooks": [
            {"x": 1.5, "y": 0.25, "z": 1.5, "ry": 0.7853981633974483, "fc": 22, "fr": 22, "fph": 0, "region": "beach"},
            {"x": 1.5, "y": 0.25, "z": 1.5, "ry": 1.1071487177940904, "fc": 23, "fr": 22, "fph": 0, "region": "beach"},
            {"x": 1.5, "y": 0.25, "z": 1.5, "ry": 1.2490457723982544, "fc": 24, "fr": 22, "fph": 0, "region": "beach"},
        ],
    },
    {
        "key": "sea_3",
        "kind": "sea",
        "name": "Sea 3 | Beach | x=4.5 z=-16.5",
        "land": {
            "x": 4.5,
            "y": 0.25,
            "z": -16.5,
            "ry": 2.356194490192345,
            "region": "beach",
        },
        "hooks": [
            {"x": 4.5, "y": 0.25, "z": -16.5, "ry": 1.5707963267948966, "fc": 26, "fr": 3, "fph": 0, "region": "beach"},
            {"x": 4.5, "y": 0.25, "z": -16.5, "ry": 1.5707963267948966, "fc": 27, "fr": 3, "fph": 0, "region": "beach"},
            {"x": 4.5, "y": 0.25, "z": -16.5, "ry": 1.8157749899217608, "fc": 28, "fr": 2, "fph": 0, "region": "beach"},
        ],
    },
]

FISH_LOCATIONS = BASE_FISH_LOCATIONS + SEA_FISH_LOCATIONS
SEA_COOK_START_RAW_FISH = 2000
SEA_COOK_STOP_RAW_FISH = 100
SEA_COOK_BASE_KEYS = ("cook_fish_1", "cook_fish_3")
FISH_ZONE_PRIME_GAP_SECONDS = 0.20


WAIT_MIN = 20.2
WAIT_MAX = 30.0
STRIKE_MIN = 2.35
STRIKE_MAX = 2.80
REEL_MIN = 1.50
REEL_MAX = 2.00
POST_DELAY_MIN = 0.20
POST_DELAY_MAX = 0.80
EXTRA_GAP_MIN = 1.0
EXTRA_GAP_MAX = 3.0
MIN_POST_GAP = 38.0
MAX_POST_GAP = 42.0
TOO_FAST_BACKOFF = 20.0
MAX_STACK = 10000
INV_LEN = 24
HOTBAR_LEN = 6
BANK_PAGE_SIZE = 28
BANK_RETRY_SECONDS = 60.0
COOK_START_RAW_FISH = 500
COOK_STOP_RAW_FISH = 100
COOK_DELAY_SECONDS = 10.5
# Fish/cook timing guard. Cook remains active between fish actions, but it is
# allowed only in the safe middle of the fish interval so cook HTTP latency
# cannot land on top of the next grant-fish-xp POST.
FISH_COOK_AFTER_CAST_START_SECONDS = 2.0
FISH_COOK_AFTER_FISH_POST_SECONDS = 2.0
FISH_COOK_BEFORE_FISH_POST_GUARD_SECONDS = 10.0
COOK_PROGRESS_LOG_EVERY = 5
COOK_RETRY_SECONDS = 60.0
SELL_START_COOKED_FISH = 2500
SELL_COOKED_QTY = 500
SELL_CURRENCY = "token"
MARKET_STACK_MAX = 5000
SELL_RETRY_SECONDS = 180.0
SELL_SUCCESS_COOLDOWN_MIN_SECONDS = 180.0
SELL_SUCCESS_COOLDOWN_MAX_SECONDS = 300.0
SELL_NO_SLOT_BACKOFF_SECONDS = 300.0

# Compact console logging: detailed movement/server internals stay behind the scenes.

# Runtime connection mode: this build is direct-only. Proxy is disabled for all HTTP/websocket traffic.
CONNECTION_MODE = "direct"

FAST_HTTP_TIMEOUT = 8.0

# Recovery policy: never stop farming for temporary Cloudflare/server/network noise.
RECOVERY_STABLE_CHECKS = 2
RECOVERY_STABLE_GAP_SECONDS = 2.0
RECOVERY_SETTLE_MIN_SECONDS = 35.0
RECOVERY_SETTLE_MAX_SECONDS = 55.0

# Same-shard reconnect settings used by Base/Sea fishing-zone switches.
SAME_SHARD_REJOIN_ATTEMPTS = 5
SAME_SHARD_REJOIN_SETTLE_SECONDS = 6.0
SAME_SHARD_QUEUE_WAIT_SECONDS = 90.0
FAST_RECOVERY_STABLE_CHECKS = 1
FAST_RECOVERY_RETRY_MAX_SECONDS = 5.0



def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def short_now():
    return time.strftime("%H:%M:%S")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def pause(message="Press Enter..."):
    try:
        input(message)
    except EOFError:
        pass


def write_error(title, detail="", raw=""):
    try:
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"{now()} | {title}\n")
            if detail:
                f.write(str(detail).strip() + "\n")
            if raw:
                f.write("[RAW]\n")
                f.write(str(raw)[:4000].strip() + "\n")
    except Exception:
        pass


_ENV_WRITE_LOCK = threading.Lock()
_LOCATION_SETTINGS_WRITE_LOCK = threading.Lock()


def _read_location_settings():
    if not LOCATION_SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(LOCATION_SETTINGS_FILE.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _update_location_settings(values):
    updates = dict(values or {})
    if not updates:
        return
    try:
        with _LOCATION_SETTINGS_WRITE_LOCK:
            data = _read_location_settings()
            data.update(updates)
            temp_file = LOCATION_SETTINGS_FILE.with_suffix(LOCATION_SETTINGS_FILE.suffix + ".tmp")
            temp_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_file.replace(LOCATION_SETTINGS_FILE)
    except Exception:
        write_error("location settings save failed", traceback.format_exc())


def _env_unquote(value):
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _read_env_values():
    values = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _env_unquote(value)
    return values


def _update_env_values(values, quoted_keys=None):
    quoted_keys = set(quoted_keys or ())
    normalized = {str(key): str(value) for key, value in (values or {}).items()}
    with _ENV_WRITE_LOCK:
        lines = []
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()

        replaced = set()
        updated_lines = []
        for raw in lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                updated_lines.append(raw)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key not in normalized:
                updated_lines.append(raw)
                continue
            value = normalized[key]
            rendered = f"'{value}'" if key in quoted_keys else value
            updated_lines.append(f"{key}={rendered}")
            replaced.add(key)

        for key, value in normalized.items():
            if key in replaced:
                continue
            rendered = f"'{value}'" if key in quoted_keys else value
            updated_lines.append(f"{key}={rendered}")

        ENV_FILE.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")
        for key, value in normalized.items():
            os.environ[key] = value


def load_env():
    for key, value in _read_env_values().items():
        os.environ.setdefault(key, value)


def save_cookie_env(cookie):
    cookie = str(cookie or "").strip()
    if not cookie:
        print("[ERR] Cookie is empty.")
        return False
    if "=" not in cookie:
        print("[ERR] Cookie must be the full NAME=VALUE cookie.")
        print("Example: __Host-kintara_session=eyJ...")
        return False

    _update_env_values({"KINTARA_COOKIE": cookie}, quoted_keys={"KINTARA_COOKIE"})
    print("[OK] .env saved.")
    return True


def setup_env_menu():
    clear_screen()
    print("=========== Cookie Setup ===========")
    print("Paste the full cookie. Input is hidden when possible.")
    print("Example: __Host-kintara_session=eyJ...")
    print("====================================\n")
    try:
        cookie = getpass.getpass("KINTARA_COOKIE: ").strip()
    except Exception:
        cookie = input("KINTARA_COOKIE: ").strip()
    save_cookie_env(cookie)
    pause()


def get_cookie(required=True):
    load_env()
    cookie = os.environ.get("KINTARA_COOKIE", "").strip()
    if required and not cookie:
        raise RuntimeError("KINTARA_COOKIE was not found. Use menu option 4 to create .env.")
    if required and "=" not in cookie:
        raise RuntimeError("KINTARA_COOKIE is incomplete. Use the full NAME=VALUE cookie.")
    return cookie


class FishDailyLimitReached(Exception):
    pass


def _utc_day_key(epoch=None):
    epoch = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")


def _utc_day_start_epoch(epoch=None):
    epoch = time.time() if epoch is None else float(epoch)
    current = datetime.fromtimestamp(epoch, timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _seconds_until_next_utc_day(epoch=None):
    epoch = time.time() if epoch is None else float(epoch)
    return max(0.0, _utc_day_start_epoch(epoch) + 86400.0 - epoch)


def _fish_daily_safe_float(value, default=0.0):
    try:
        return max(0.0, float(value))
    except Exception:
        return float(default)


def fish_daily_initialize(auto_state):
    if auto_state is None:
        return
    values = _read_env_values()
    today = _utc_day_key()
    stored_day = str(values.get(FISH_DAILY_ENV_DATE_KEY) or today)
    used = _fish_daily_safe_float(values.get(FISH_DAILY_ENV_SECONDS_KEY), 0.0)
    if stored_day != today:
        stored_day = today
        used = 0.0
        _update_env_values({
            FISH_DAILY_ENV_DATE_KEY: stored_day,
            FISH_DAILY_ENV_SECONDS_KEY: "0.000",
        })
    auto_state["fish_daily_day"] = stored_day
    auto_state["fish_daily_used_seconds"] = min(used, float(FISH_DAILY_LIMIT_SECONDS))
    auto_state["fish_daily_active_since"] = None
    auto_state["fish_daily_last_persist_at"] = 0.0


def fish_daily_rollover_if_needed(auto_state, now_epoch=None):
    if auto_state is None:
        return False
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    today = _utc_day_key(now_epoch)
    stored_day = str(auto_state.get("fish_daily_day") or today)
    if stored_day == today:
        return False

    active_since = auto_state.get("fish_daily_active_since")
    auto_state["fish_daily_day"] = today
    auto_state["fish_daily_used_seconds"] = 0.0
    if active_since is not None:
        boundary = _utc_day_start_epoch(now_epoch)
        auto_state["fish_daily_active_since"] = max(float(active_since), boundary)
    auto_state["fish_daily_last_persist_at"] = 0.0
    fish_daily_persist(auto_state, force=True, now_epoch=now_epoch)
    return True


def fish_daily_used_seconds(auto_state, now_epoch=None):
    if auto_state is None:
        return 0.0
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    used = _fish_daily_safe_float(auto_state.get("fish_daily_used_seconds"), 0.0)
    active_since = auto_state.get("fish_daily_active_since")
    if active_since is not None:
        used += max(0.0, now_epoch - float(active_since))
    return min(used, float(FISH_DAILY_LIMIT_SECONDS))


def fish_daily_persist(auto_state, force=False, now_epoch=None):
    if auto_state is None:
        return
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    last = _fish_daily_safe_float(auto_state.get("fish_daily_last_persist_at"), 0.0)
    if not force and now_epoch - last < FISH_DAILY_PERSIST_INTERVAL_SECONDS:
        return
    used = fish_daily_used_seconds(auto_state, now_epoch=now_epoch)
    _update_env_values({
        FISH_DAILY_ENV_DATE_KEY: str(auto_state.get("fish_daily_day") or _utc_day_key(now_epoch)),
        FISH_DAILY_ENV_SECONDS_KEY: f"{used:.3f}",
    })
    auto_state["fish_daily_last_persist_at"] = now_epoch


def fish_daily_start(auto_state):
    if auto_state is None:
        return
    now_epoch = time.time()
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    if fish_daily_used_seconds(auto_state, now_epoch=now_epoch) >= FISH_DAILY_LIMIT_SECONDS:
        raise FishDailyLimitReached()
    if auto_state.get("fish_daily_active_since") is None:
        auto_state["fish_daily_active_since"] = now_epoch
        fish_daily_persist(auto_state, force=True, now_epoch=now_epoch)


def fish_daily_pause(auto_state):
    if auto_state is None:
        return
    now_epoch = time.time()
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    active_since = auto_state.get("fish_daily_active_since")
    if active_since is not None:
        used = _fish_daily_safe_float(auto_state.get("fish_daily_used_seconds"), 0.0)
        used += max(0.0, now_epoch - float(active_since))
        auto_state["fish_daily_used_seconds"] = min(used, float(FISH_DAILY_LIMIT_SECONDS))
        auto_state["fish_daily_active_since"] = None
    fish_daily_persist(auto_state, force=True, now_epoch=now_epoch)


def fish_daily_guard(auto_state):
    if auto_state is None:
        return float("inf")
    now_epoch = time.time()
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    used = fish_daily_used_seconds(auto_state, now_epoch=now_epoch)
    remaining = max(0.0, float(FISH_DAILY_LIMIT_SECONDS) - used)
    fish_daily_persist(auto_state, force=False, now_epoch=now_epoch)
    if remaining <= 0.0:
        fish_daily_pause(auto_state)
        raise FishDailyLimitReached()
    return remaining


def fish_daily_sleep_slice(auto_state, requested_seconds):
    requested = max(0.0, float(requested_seconds or 0.0))
    remaining = fish_daily_guard(auto_state)
    return min(requested, remaining)


def fish_daily_limit_reached(auto_state):
    if auto_state is None:
        return False
    now_epoch = time.time()
    fish_daily_rollover_if_needed(auto_state, now_epoch=now_epoch)
    return fish_daily_used_seconds(auto_state, now_epoch=now_epoch) >= FISH_DAILY_LIMIT_SECONDS


def fish_daily_wait_until_reset(auto_state):
    fish_daily_pause(auto_state)
    while fish_daily_limit_reached(auto_state):
        sleep_s = _seconds_until_next_utc_day()
        time.sleep(min(1.0, max(0.05, sleep_s)))
        fish_daily_rollover_if_needed(auto_state)


def fish_daily_wait_before_start_if_needed(auto_state):
    if not fish_daily_limit_reached(auto_state):
        return
    print(FISH_DAILY_LIMIT_MESSAGE)
    fish_daily_wait_until_reset(auto_state)


def rebuild_fish_after_daily_limit(realm_type, server, ws, reader_stop, auto_state):
    fish_daily_pause(auto_state)
    close_presence(ws, reader_stop)
    print(FISH_DAILY_LIMIT_MESSAGE)
    fish_daily_wait_until_reset(auto_state)
    server, ws, reader_stop = open_presence_for_server_with_retry(
        realm_type,
        server,
        "FISH RESET",
    )
    me = get_me()
    outfit = me.get("outfit") or {}
    current_fish = count_raw_fish_from_backpack(me.get("backpack") or {})
    return server, ws, reader_stop, outfit, current_fish


def ensure_dependency():
    if websocket is None:
        raise RuntimeError(
            "websocket-client is not installed. Run START_FARM_MAHI.bat again, "
            "or run: python -m pip install websocket-client"
        )


def system_proxy_url(target_url):
    # Proxy is intentionally disabled; all HTTP and websocket traffic is direct.
    return ""

def direct_urlopen(request, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def proxy_urlopen(request, timeout, proxy_url):
    parsed = urllib.parse.urlparse(str(proxy_url or ""))
    if parsed.scheme.lower() in ("http", "https"):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def http(method, path, body=None, timeout=25):
    """Direct-only HTTP helper.

    Proxy is deliberately ignored in this direct-only build.
    """
    headers = {
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Origin": BASE,
        "Referer": BASE + "/play",
        "Cookie": get_cookie(),
    }
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    url = BASE + path
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with direct_urlopen(request, timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {}
            return response.status, payload, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {}
        return exc.code, payload, raw
    except Exception as exc:
        return 0, {"ok": False, "error": str(exc)}, str(exc)

def slot_type(slot):
    if not isinstance(slot, dict):
        return None
    return slot.get("t") or slot.get("type") or slot.get("itemType")


def slot_count(slot):
    if not isinstance(slot, dict):
        return 0
    try:
        return max(0, int(float(slot.get("n", slot.get("count", slot.get("amount", 0))) or 0)))
    except Exception:
        return 0


def count_raw_fish_from_backpack(backpack):
    if not isinstance(backpack, dict):
        return 0

    try:
        direct = max(0, int(float(backpack.get("fish", 0) or 0)))
    except Exception:
        direct = 0

    slot_sum = 0
    for key in ("hotbar", "invSlots"):
        slots = backpack.get(key) or []
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if slot_type(slot) == "fish":
                slot_sum += slot_count(slot)

    return max(direct, slot_sum)


def pack_slot(slot):
    item_type = slot_type(slot)
    amount = slot_count(slot)
    if not item_type or amount <= 0:
        return None
    out = {"t": item_type, "n": amount}
    if isinstance(slot, dict) and "d" in slot:
        out["d"] = slot["d"]
    return out


def norm_slots(slots, length):
    out = []
    if isinstance(slots, list):
        for slot in slots[:length]:
            out.append(pack_slot(slot))
    while len(out) < length:
        out.append(None)
    return out


def bank_length(backpack):
    raw = backpack.get("bankSlots") if isinstance(backpack, dict) else []
    raw_len = len(raw) if isinstance(raw, list) else 0
    try:
        pages = max(1, int(float(backpack.get("bankPages", 1) or 1)))
    except Exception:
        pages = 1
    return max(raw_len, pages * BANK_PAGE_SIZE, BANK_PAGE_SIZE)


def extract_storage(me):
    backpack = me.get("backpack", {}) if isinstance(me, dict) else {}
    inv_slots = norm_slots(backpack.get("invSlots"), INV_LEN)
    hotbar = norm_slots(backpack.get("hotbar"), HOTBAR_LEN)
    bank_slots = norm_slots(backpack.get("bankSlots"), bank_length(backpack))
    return backpack, inv_slots, hotbar, bank_slots


def count_slots(slots, item_type):
    total = 0
    for slot in slots or []:
        if slot_type(slot) == item_type:
            total += slot_count(slot)
    return total


def count_bank_fish(backpack):
    if not isinstance(backpack, dict):
        return 0
    return count_slots(backpack.get("bankSlots") or [], "fish")


def count_carry_item(backpack, item_type):
    if not isinstance(backpack, dict):
        return 0
    return count_slots((backpack.get("invSlots") or []) + (backpack.get("hotbar") or []), item_type)


def count_bank_item(backpack, item_type):
    if not isinstance(backpack, dict):
        return 0
    return count_slots(backpack.get("bankSlots") or [], item_type)


def count_total_item(backpack, item_type):
    return count_carry_item(backpack, item_type) + count_bank_item(backpack, item_type)


def fish_bank_capacity(bank_slots):
    capacity = 0
    for slot in bank_slots or []:
        item_type = slot_type(slot)
        amount = slot_count(slot)
        if not item_type or amount <= 0:
            capacity += MAX_STACK
        elif item_type == "fish" and amount < MAX_STACK:
            capacity += MAX_STACK - amount
    return capacity


def fish_inventory_has_room(inv_slots):
    for slot in inv_slots or []:
        item_type = slot_type(slot)
        amount = slot_count(slot)
        if not item_type or amount <= 0:
            return True
        if item_type == "fish" and amount < MAX_STACK:
            return True
    return False


def take_fish_from_slots(slots, amount):
    left = max(0, int(amount))
    moved = 0
    for index, slot in enumerate(slots):
        if left <= 0:
            break
        if slot_type(slot) != "fish":
            continue
        take = min(slot_count(slot), left)
        if take <= 0:
            continue
        new_amount = slot_count(slot) - take
        if new_amount > 0:
            slots[index]["n"] = new_amount
        else:
            slots[index] = None
        moved += take
        left -= take
    return moved


def put_fish_into_bank(bank_slots, amount):
    left = max(0, int(amount))
    moved = 0
    for slot in bank_slots:
        if left <= 0:
            break
        if slot_type(slot) != "fish":
            continue
        room = MAX_STACK - slot_count(slot)
        if room <= 0:
            continue
        add = min(room, left)
        slot["n"] = slot_count(slot) + add
        moved += add
        left -= add

    for index, slot in enumerate(bank_slots):
        if left <= 0:
            break
        if slot_type(slot):
            continue
        add = min(MAX_STACK, left)
        bank_slots[index] = {"t": "fish", "n": add}
        moved += add
        left -= add

    return moved


def item_stack_max(item_type):
    # Current server inventory/hotbar/bank stack limit is 10000 per slot.
    # MARKET_STACK_MAX is a separate marketplace-listing limit.
    return MAX_STACK


def take_item_from_slots(slots, item_type, amount):
    left = int(amount)
    moved = 0
    for index, slot in enumerate(slots):
        if left <= 0:
            break
        if slot_type(slot) != item_type:
            continue
        take = min(slot_count(slot), left)
        new_amount = slot_count(slot) - take
        if new_amount <= 0:
            slots[index] = None
        else:
            slots[index] = {"t": item_type, "n": new_amount}
        moved += take
        left -= take
    return moved


def put_item_into_slots(slots, item_type, amount):
    left = int(amount)
    moved = 0
    max_stack = item_stack_max(item_type)

    for slot in slots:
        if left <= 0:
            break
        if slot_type(slot) != item_type:
            continue
        room = max_stack - slot_count(slot)
        if room <= 0:
            continue
        add = min(room, left)
        slot["n"] = slot_count(slot) + add
        moved += add
        left -= add

    for index, slot in enumerate(slots):
        if left <= 0:
            break
        if slot_type(slot):
            continue
        add = min(max_stack, left)
        slots[index] = {"t": item_type, "n": add}
        moved += add
        left -= add

    return moved


def move_bank_item_to_carry(item_type, amount, label="MOVE", max_attempts=2):
    amount = max(0, int(amount))
    if amount <= 0:
        return {"ok": True, "moved": 0}

    for attempt in range(1, max_attempts + 1):
        me = get_me()
        backpack, inv_slots, hotbar, bank_slots = extract_storage(me)
        carry_slots = inv_slots + hotbar
        before_carry = count_slots(carry_slots, item_type)
        before_bank = count_slots(bank_slots, item_type)
        to_move = min(amount, before_bank)
        if to_move <= 0:
            return {"ok": False, "moved": 0, "error": "bank_item_missing", "carry": before_carry, "bank": before_bank}

        taken = take_item_from_slots(bank_slots, item_type, to_move)
        placed = put_item_into_slots(carry_slots, item_type, taken)
        if placed < taken:
            put_item_into_slots(bank_slots, item_type, taken - placed)

        if placed <= 0:
            return {"ok": False, "moved": 0, "error": "carry_full", "carry": before_carry, "bank": before_bank}

        status, payload, raw = save_backpack(me, carry_slots[:INV_LEN], carry_slots[INV_LEN:INV_LEN + HOTBAR_LEN], bank_slots)
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
        if ok:
            verify = get_me()
            verified_backpack = verify.get("backpack") or {}
            after_carry = count_carry_item(verified_backpack, item_type)
            after_bank = count_bank_item(verified_backpack, item_type)
            moved = max(0, after_carry - before_carry)
            return {"ok": True, "moved": moved or placed, "carry": after_carry, "bank": after_bank}

        write_error(
            f"{label.lower()} bank move failed",
            f"item={item_type} attempt={attempt} status={status} error={payload.get('error') if isinstance(payload, dict) else None}",
            raw,
        )
        if status != 409:
            return {"ok": False, "moved": 0, "error": payload.get("error") if isinstance(payload, dict) else "save_failed"}
        time.sleep(0.8)

    return {"ok": False, "moved": 0, "error": "stale_state_retry_failed"}


def consolidate_carry_item_stack(item_type, min_stack, label="STACK", max_attempts=2):
    min_stack = max(1, int(min_stack))
    for attempt in range(1, max_attempts + 1):
        me = get_me()
        backpack, inv_slots, hotbar, bank_slots = extract_storage(me)
        carry_slots = inv_slots + hotbar
        total = count_slots(carry_slots, item_type)
        if total < min_stack:
            return {"ok": False, "error": "not_enough_carry", "carry": total}

        if any(slot_type(slot) == item_type and slot_count(slot) >= min_stack for slot in carry_slots):
            return {"ok": True, "changed": False, "carry": total}

        for index, slot in enumerate(carry_slots):
            if slot_type(slot) == item_type:
                carry_slots[index] = None
        put_item_into_slots(carry_slots, item_type, total)

        status, payload, raw = save_backpack(me, carry_slots[:INV_LEN], carry_slots[INV_LEN:INV_LEN + HOTBAR_LEN], bank_slots)
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
        if ok:
            verify = get_me()
            verified_backpack, verified_inv, verified_hotbar, _verified_bank = extract_storage(verify)
            verified_carry = verified_inv + verified_hotbar
            ready = any(slot_type(slot) == item_type and slot_count(slot) >= min_stack for slot in verified_carry)
            return {"ok": ready, "changed": True, "carry": count_slots(verified_carry, item_type)}

        write_error(
            f"{label.lower()} consolidate failed",
            f"item={item_type} attempt={attempt} status={status} error={payload.get('error') if isinstance(payload, dict) else None}",
            raw,
        )
        if status != 409:
            return {"ok": False, "error": payload.get("error") if isinstance(payload, dict) else "save_failed"}
        time.sleep(0.8)

    return {"ok": False, "error": "stale_state_retry_failed"}



def validate_slot_stack_limits(slots, label):
    """Reject any save-backpack payload containing an illegal stack."""
    for index, slot in enumerate(slots or []):
        item = slot_type(slot)
        amount = slot_count(slot)
        if item and amount > MAX_STACK:
            raise ValueError(
                f"{label}[{index}] has illegal stack {amount}x {item}; max is {MAX_STACK}"
            )


def build_save_backpack_payload(me, inv_slots, hotbar, bank_slots):
    validate_slot_stack_limits(inv_slots, "invSlots")
    validate_slot_stack_limits(hotbar, "hotbar")
    validate_slot_stack_limits(bank_slots, "bankSlots")

    backpack = me.get("backpack", {}) if isinstance(me, dict) else {}
    payload = {
        "invSlots": [pack_slot(slot) for slot in inv_slots],
        "hotbar": [pack_slot(slot) for slot in hotbar],
        "bankSlots": [pack_slot(slot) for slot in bank_slots],
        "baseSeq": me.get("stateSeq", backpack.get("stateSeq") if isinstance(backpack, dict) else None),
        "intentionalRemovals": [],
    }
    if isinstance(backpack, dict):
        for key in ("cosmeticSlots", "mountSlots", "petSlots", "furnitureSlots"):
            if isinstance(backpack.get(key), list):
                payload[key] = [pack_slot(slot) for slot in backpack.get(key)]
    return payload


def save_backpack(me, inv_slots, hotbar, bank_slots):
    payload = build_save_backpack_payload(me, inv_slots, hotbar, bank_slots)
    return http(
        "POST",
        "/api/auth/save-backpack",
        payload,
        timeout=FAST_HTTP_TIMEOUT,
    )


RAW_FISH_SLOT_CLEAR_RESOURCE_FALLBACK_ITEMS = (
    "wood",
    "stone",
    "coal",
    "metal",
    "gold",
)

RAW_FISH_SLOT_CLEAR_PROTECTED_ITEMS = {
    "fish",
    "cooked_fish_meat",
}

RAW_FISH_SLOT_CLEAR_PROTECTED_KEYWORDS = (
    "rod",
    "hook",
    "tool",
    "axe",
    "pickaxe",
    "sword",
    "key",
    "ticket",
    "bait",
    "pet",
    "mount",
    "cosmetic",
)


def is_safe_to_bank_for_raw_fish_slot(item_type, allow_resource_fallback=False):
    if not item_type:
        return False
    name = str(item_type).lower()
    if name in RAW_FISH_SLOT_CLEAR_PROTECTED_ITEMS:
        return False
    if any(key in name for key in RAW_FISH_SLOT_CLEAR_PROTECTED_KEYWORDS):
        return False
    if name in RAW_FISH_SLOT_CLEAR_RESOURCE_FALLBACK_ITEMS:
        return bool(allow_resource_fallback)
    return True


def free_one_inventory_slot_for_raw_fish(label="BANK", max_attempts=2):
    """Open exactly one inventory slot by banking one stack.

    Resource stacks are preferred because the user explicitly wants one slot of
    wood/stone/coal/metal/gold to be banked when raw-fish inventory room is
    blocked. Metal is kept last in the fallback order. The function keeps trying
    candidates until
    one actually creates a verified empty/fish room slot; it does not mass-clean
    the inventory.
    """
    # Avoid touching metal unless there is no other safe resource stack available.
    preferred_resource_order = ("wood", "stone", "coal", "gold", "metal")
    preferred_resource_rank = {name: i for i, name in enumerate(preferred_resource_order)}

    for attempt in range(1, max_attempts + 1):
        me = get_me()
        backpack, inv_slots, hotbar, bank_slots = extract_storage(me)
        if fish_inventory_has_room(inv_slots):
            return {"ok": True, "changed": False, "reason": "already_has_room"}

        candidates = []

        # First: exactly one stack from wood/stone/coal/gold/metal if available.
        # Sort by resource priority instead of inventory position so metal is
        # not banked before cheaper/fallback resources.
        for index, slot in enumerate(inv_slots):
            item_type = slot_type(slot)
            amount = slot_count(slot)
            if amount > 0 and item_type in preferred_resource_rank:
                candidates.append((0, index, item_type, amount))

        # Second: one non-critical non-protected item.
        for index, slot in enumerate(inv_slots):
            item_type = slot_type(slot)
            amount = slot_count(slot)
            if amount > 0 and is_safe_to_bank_for_raw_fish_slot(item_type, allow_resource_fallback=False):
                candidates.append((1, index, item_type, amount))

        candidates.sort(key=lambda x: (x[0], preferred_resource_rank.get(x[2], 999), x[1]))
        if not candidates:
            return {"ok": False, "error": "no_single_slot_candidate"}

        last_error = None
        for _prio, candidate_index, candidate_type, candidate_count in candidates[:8]:
            # Rebuild from the latest snapshot for each candidate so a failed
            # verification cannot leave us working on stale slot arrays.
            me2 = get_me()
            backpack2, inv2, hotbar2, bank2 = extract_storage(me2)
            if fish_inventory_has_room(inv2):
                return {"ok": True, "changed": False, "reason": "already_has_room"}
            slot = inv2[candidate_index] if 0 <= candidate_index < len(inv2) else None
            if slot_type(slot) != candidate_type or slot_count(slot) <= 0:
                continue
            amount = slot_count(slot)

            trial_bank = [pack_slot(s) for s in bank2]
            placed = put_item_into_slots(trial_bank, candidate_type, amount)
            if placed != amount:
                last_error = "bank_no_room_for_candidate"
                continue

            inv2[candidate_index] = None
            status, payload, raw = save_backpack(me2, inv2, hotbar2, trial_bank)
            ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
            if not ok:
                last_error = payload.get("error") if isinstance(payload, dict) else "save_failed"
                write_error(
                    f"{label.lower()} raw fish slot cleanup failed",
                    f"attempt={attempt} item={candidate_type} count={amount} status={status} error={last_error}",
                    raw,
                )
                if status == 409:
                    break
                continue

            verify = get_me()
            _bp, verified_inv, _verified_hotbar, _verified_bank = extract_storage(verify)
            if fish_inventory_has_room(verified_inv):
                print(
                    f"[{short_now()}] {label} opened 1 raw-fish slot by banking "
                    f"{amount}x {candidate_type}"
                )
                return {
                    "ok": True,
                    "changed": True,
                    "cleared_item": candidate_type,
                    "cleared_count": amount,
                }

            # Some server-side validations can accept the request but normalize
            # the inventory back. Try the next candidate instead of giving up.
            last_error = "cleanup_verify_failed"

        if last_error != "stale_state_retry_failed":
            # Fast retry on stale state; otherwise return the most useful reason.
            if last_error == "cleanup_verify_failed":
                return {"ok": False, "error": "cleanup_verify_failed"}
            if last_error and last_error != "bank_no_room_for_candidate":
                return {"ok": False, "error": last_error}
        time.sleep(0.15)

    return {"ok": False, "error": "stale_state_retry_failed"}

def deposit_raw_fish_to_bank(label="BANK", max_attempts=2):
    for attempt in range(1, max_attempts + 1):
        me = get_me()
        backpack, inv_slots, hotbar, bank_slots = extract_storage(me)
        carry_slots = inv_slots + hotbar
        carry_fish = count_slots(carry_slots, "fish")
        bank_fish_before = count_slots(bank_slots, "fish")
        capacity = fish_bank_capacity(bank_slots)
        has_room = fish_inventory_has_room(inv_slots)

        if has_room:
            return {
                "ok": True,
                "moved": 0,
                "carry_fish": carry_fish,
                "bank_fish": bank_fish_before,
                "bank_capacity": capacity,
                "inventory_has_room": True,
            }

        if capacity <= 0:
            return {
                "ok": False,
                "moved": 0,
                "error": "bank_full",
                "carry_fish": carry_fish,
                "bank_fish": bank_fish_before,
                "bank_capacity": 0,
                "inventory_has_room": False,
            }

        # Deposit raw fish from the whole carry area, not only invSlots.
        # Catches can land in the hotbar when inventory slots are full; the
        # logic saw carry_fish=1 but no fish in invSlots and incorrectly tried
        # to open a raw-fish slot instead of banking the fish already in carry.
        move_amount = min(carry_fish, capacity) if carry_fish > 0 else 0

        if move_amount <= 0:
            cleanup = free_one_inventory_slot_for_raw_fish(label, max_attempts=1)
            if cleanup.get("ok"):
                return {
                    "ok": True,
                    "moved": 0,
                    "cleared_slot": bool(cleanup.get("changed")),
                    "cleared_item": cleanup.get("cleared_item"),
                    "cleared_count": cleanup.get("cleared_count", 0),
                    "carry_fish": carry_fish,
                    "bank_fish": bank_fish_before,
                    "bank_capacity": capacity,
                    "inventory_has_room": True,
                }
            return {
                "ok": False,
                "moved": 0,
                "error": "inventory_full_no_raw_fish_slot",
                "cleanup_error": cleanup.get("error"),
                "carry_fish": carry_fish,
                "bank_fish": bank_fish_before,
                "bank_capacity": capacity,
                "inventory_has_room": False,
            }

        moved_from_carry = take_fish_from_slots(carry_slots, move_amount)
        moved_to_bank = put_fish_into_bank(bank_slots, moved_from_carry)
        if moved_to_bank < moved_from_carry:
            # Put the unmatched amount back into carry to keep the payload balanced.
            put_item_into_slots(carry_slots, "fish", moved_from_carry - moved_to_bank)

        status, payload, raw = save_backpack(me, carry_slots[:INV_LEN], carry_slots[INV_LEN:INV_LEN + HOTBAR_LEN], bank_slots)
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
        if ok:
            verify = get_me()
            verified_backpack, verified_inv, verified_hotbar, verified_bank = extract_storage(verify)
            bank_fish_after = count_slots(verified_bank, "fish")
            carry_after = count_slots(verified_inv + verified_hotbar, "fish")
            moved_verified = max(0, bank_fish_after - bank_fish_before)
            moved_final = moved_verified or moved_to_bank
            if moved_final > 0 or carry_after < carry_fish:
                print(f"[{short_now()}] {label} emergency moved={moved_final} bank_fish={bank_fish_after} carry_fish={carry_after}")
            return {
                "ok": True,
                "moved": moved_final,
                "carry_fish": carry_after,
                "bank_fish": bank_fish_after,
                "bank_capacity": fish_bank_capacity(verified_bank),
                "inventory_has_room": fish_inventory_has_room(verified_inv),
            }

        write_error(
            "emergency bank deposit failed",
            f"attempt={attempt} status={status} error={payload.get('error') if isinstance(payload, dict) else None}",
            raw,
        )
        if status != 409:
            return {
                "ok": False,
                "moved": 0,
                "error": payload.get("error") if isinstance(payload, dict) else "save_failed",
                "carry_fish": carry_fish,
                "bank_fish": bank_fish_before,
                "bank_capacity": capacity,
                "inventory_has_room": False,
            }
        time.sleep(0.8)

    return {"ok": False, "moved": 0, "error": "stale_state_retry_failed"}


def wait_for_storage_space():
    print(f"[{short_now()}] STORAGE full. Waiting until inventory or bank has room...")
    while True:
        try:
            wait_for_connection()
            result = deposit_raw_fish_to_bank("BANK", max_attempts=2)
            if result.get("ok") and (result.get("inventory_has_room") or result.get("moved", 0) > 0):
                print(f"[{short_now()}] STORAGE ready. Continuing.")
                return result

            print(f"[{short_now()}] STORAGE still full. Next check in {BANK_RETRY_SECONDS:.0f}s")
        except KeyboardInterrupt:
            raise
        except Exception:
            write_error("storage wait error", traceback.format_exc())
            print(f"[{short_now()}] STORAGE check failed. Next check in {BANK_RETRY_SECONDS:.0f}s")
        time.sleep(BANK_RETRY_SECONDS)


def is_auth_response(status, error):
    error_text = str(error or "").lower()
    return int(status or 0) in (401, 403) or error_text in ("unauthorized", "forbidden")


def is_recoverable_http_status(status):
    try:
        status = int(status or 0)
    except Exception:
        status = 0
    return status == 0 or status in (408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524)


def is_recoverable_state_error(status, error="", raw=""):
    if is_auth_response(status, error):
        return False
    if is_recoverable_http_status(status):
        return True
    text = f"{error} {raw}".lower()
    markers = (
        "bad gateway",
        "gateway timeout",
        "service unavailable",
        "cloudflare",
        "origin web server",
        "temporarily unavailable",
        "connection reset",
        "timed out",
        "timeout",
    )
    return any(marker in text for marker in markers)


def is_auth_problem_detail(detail):
    text = str(detail or "").lower()
    return (
        "unauthorized" in text
        or "forbidden" in text
        or "cookie/login problem" in text
        or "cookie is not valid" in text
        or "status=401" in text
        or "status=403" in text
    )


def get_me():
    delay = 5.0
    attempt = 0
    while True:
        status, payload, raw = http("GET", "/api/auth/me", timeout=12)
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False and payload.get("player")
        if ok:
            return payload

        error = payload.get("error") if isinstance(payload, dict) else None
        if is_auth_response(status, error):
            raise RuntimeError("Cookie/login problem. Refresh the cookie with option 4.")

        if is_recoverable_state_error(status, error, raw):
            attempt += 1
            if attempt == 1 or attempt % 6 == 0:
                write_error("/api/auth/me transient wait", f"status={status} error={error} raw={str(raw)[:300]}")
            sleep_s = min(60.0, delay) + random.uniform(0.0, 3.0)
            print(f"[{short_now()}] STATE unstable /api/auth/me status={status}. Waiting {sleep_s:.0f}s, then retrying...")
            time.sleep(sleep_s)
            delay = min(60.0, delay * 1.5)
            continue

        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise RuntimeError(f"/api/auth/me failed status={status} error={error} raw={str(raw)[:250]}")
        raise RuntimeError("The account is not logged in, or the cookie is not valid.")


def get_me_fast(label="STATE"):
    """One-shot /api/auth/me for latency-sensitive operations.

    The normal get_me() intentionally waits and retries for farming stability.
    This helper surfaces a transient read error immediately instead of sleeping
    through a cook or same-shard location transition.
    """
    status, payload, raw = http("GET", "/api/auth/me", timeout=FAST_HTTP_TIMEOUT)
    ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False and payload.get("player")
    if ok:
        return payload
    error = payload.get("error") if isinstance(payload, dict) else None
    if is_auth_response(status, error):
        raise RuntimeError("Cookie/login problem. Refresh the cookie with option 4.")
    if is_recoverable_state_error(status, error, raw):
        raise RuntimeError(f"{label} temporary /api/auth/me status={status} err={error}")
    if not isinstance(payload, dict) or payload.get("ok") is False:
        raise RuntimeError(f"{label} /api/auth/me failed status={status} error={error} raw={str(raw)[:250]}")
    raise RuntimeError(f"{label} account is not logged in, or the cookie is not valid.")


def cook_raw_fish_once():
    return http("POST", "/api/auth/grant-cook-xp", {"mode": "fish"}, timeout=25)


def set_cook_cooldown(auto_state):
    if auto_state is not None:
        auto_state["cook_next_at"] = time.time() + COOK_DELAY_SECONDS


def wait_for_cook_cooldown(auto_state):
    if auto_state is None:
        return
    wait_s = float(auto_state.get("cook_next_at", 0.0) or 0.0) - time.time()
    if wait_s > 0:
        time.sleep(wait_s)


def maybe_refill_cook_materials(backpack, raw_total=None):
    carry_fish = count_carry_item(backpack, "fish")
    carry_wood = count_carry_item(backpack, "wood")

    if raw_total is None:
        raw_total = count_total_item(backpack, "fish")
    cooks_left = max(0, int(raw_total or 0) - COOK_STOP_RAW_FISH)

    # when cooking needs raw fish from bank, move the whole useful
    # batch in one save-backpack operation instead of pulling one fish at a
    # time.  The target is the remaining number of cooks until the stop level;
    # move_bank_item_to_carry may still move a partial amount if carry space is
    # limited, and logs below make that visible.
    bank_fish = count_bank_item(backpack, "fish")
    fish_shortage = max(0, cooks_left - carry_fish)
    if fish_shortage > 0 and bank_fish > 0:
        want_fish = min(fish_shortage, bank_fish)
        moved = move_bank_item_to_carry("fish", want_fish, "COOK_BULK_FISH")
        try:
            print(
                f"[{short_now()}] COOK bulk fish refill want={want_fish} "
                f"moved={moved.get('moved')} carry={moved.get('carry')} bank={moved.get('bank')} "
                f"ok={moved.get('ok')} err={moved.get('error')}"
            )
        except Exception:
            pass

    wood_shortage = max(0, cooks_left - carry_wood)
    bank_wood = count_bank_item(backpack, "wood")
    if wood_shortage > 0 and bank_wood > 0:
        move_bank_item_to_carry("wood", min(wood_shortage, bank_wood), "COOK")


def is_cook_location_error(error):
    text = str(error or "").lower()
    return "roast" in text or "pit" in text


def is_cook_mode(mode):
    return mode in ("farm_cook", "full_auto")


def is_sell_mode(mode):
    return mode == "full_auto"






def cook_step(auto_state, ws=None, outfit=None, location_state=None):
    if not auto_state or not is_cook_mode(auto_state.get("mode")):
        return

    now_ts = time.time()
    if now_ts < float(auto_state.get("cook_next_at", 0.0) or 0.0):
        return

    try:
        me = get_me_fast("COOK")
        backpack = me.get("backpack") or {}
        raw_total = count_total_item(backpack, "fish")

        if not auto_state.get("cook_active") and raw_total >= COOK_START_RAW_FISH:
            auto_state["cook_active"] = True
            auto_state["cook_cycle_done"] = 0
            auto_state["cook_cycle_start_raw"] = raw_total
            print(f"[{short_now()}] COOK started raw_fish={raw_total} target_stop={COOK_STOP_RAW_FISH}")

        if not auto_state.get("cook_active"):
            auto_state["cook_next_at"] = time.time() + 15.0
            return

        if raw_total <= COOK_STOP_RAW_FISH:
            auto_state["cook_active"] = False
            auto_state["cook_cycle_done"] = 0
            print(f"[{short_now()}] COOK paused raw_fish={raw_total}; waiting for {COOK_START_RAW_FISH}.")
            return

        maybe_refill_cook_materials(backpack, raw_total=raw_total)
        me = get_me()
        backpack = me.get("backpack") or {}
        carry_fish = count_carry_item(backpack, "fish")
        carry_wood = count_carry_item(backpack, "wood")
        if min(carry_fish, carry_wood) <= 0:
            auto_state["cook_next_at"] = time.time() + COOK_RETRY_SECONDS
            print(f"[{short_now()}] COOK waiting materials fish={carry_fish} wood={carry_wood}")
            return

        status, payload, raw = cook_raw_fish_once()
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
        if ok:
            auto_state["cook_done"] = int(auto_state.get("cook_done", 0) or 0) + 1
            auto_state["cook_cycle_done"] = int(auto_state.get("cook_cycle_done", 0) or 0) + 1
            cooked = auto_state["cook_cycle_done"]
            set_cook_cooldown(auto_state)
            if cooked % COOK_PROGRESS_LOG_EVERY == 0:
                latest_bp = payload.get("backpack") if isinstance(payload.get("backpack"), dict) else get_me().get("backpack", {})
                raw_left = count_total_item(latest_bp, "fish")
                cycle_start = int(auto_state.get("cook_cycle_start_raw", raw_left) or raw_left)
                print(
                    f"[{short_now()}] COOK progress cooked={cooked} "
                    f"raw={raw_left}/{COOK_STOP_RAW_FISH} started={cycle_start}"
                )
            return

        err = payload.get("error") if isinstance(payload, dict) else None
        if is_cook_location_error(err) and ws is not None and location_state is not None:
            try:
                prime_join_cook_location(ws, outfit, location_state)
                print(f"[{short_now()}] COOK location refreshed after location error.")
            except Exception:
                write_error("cook location refresh failed", traceback.format_exc())
            auto_state["cook_next_at"] = time.time() + 2.0
        elif err == "missing_materials":
            auto_state["cook_next_at"] = time.time() + 60.0
        elif err == "inventory_full":
            auto_state["cook_next_at"] = time.time() + 180.0
        elif status == 429:
            set_cook_cooldown(auto_state)
        elif status == 0:
            auto_state["cook_next_at"] = time.time() + 60.0
        else:
            auto_state["cook_next_at"] = time.time() + 120.0
        write_error("cook failed", f"status={status} error={err}", raw)
    except KeyboardInterrupt:
        raise
    except Exception:
        auto_state["cook_next_at"] = time.time() + 60.0
        write_error("cook step error", traceback.format_exc())
        print(f"[{short_now()}] COOK error saved.")


def marketplace_category_for_item(item_type):
    if item_type in ("fish", "cooked_fish_meat", "raw_chicken", "cooked_chicken"):
        return "cat_food"
    if item_type in ("wood", "stone", "coal", "metal", "molten_rock"):
        return "cat_materials"
    if item_type == "gold":
        return "cat_gold"
    return "all"


def marketplace_listings(item_type, currency=SELL_CURRENCY, limit=100):
    params = {
        "sort": "cheap",
        "currency": "token" if currency == "token" else "gold",
        "category": marketplace_category_for_item(item_type),
        "limit": str(limit),
        "offset": "0",
        "q": item_type,
    }
    path = "/api/marketplace/listings?" + urllib.parse.urlencode(params)
    status, payload, raw = http("GET", path, timeout=30)
    if status != 200 or not isinstance(payload, dict):
        return []
    rows = payload.get("listings") if isinstance(payload.get("listings"), list) else []
    out = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("itemType")) != item_type:
            continue
        if currency == "token":
            if str(row.get("currency", "gold")) == "token" and row.get("priceUsd") is not None:
                out.append(row)
        else:
            if str(row.get("currency", "gold")) != "token":
                out.append(row)
    return out


def marketplace_unit_price(row, currency):
    qty = max(1, int(float(row.get("quantity", 1) or 1)))
    if currency == "token":
        return float(row.get("priceUsd", 0) or 0) / qty
    return float(row.get("priceGold", 0) or 0) / qty


def marketplace_balanced_price(item_type, qty, currency=SELL_CURRENCY):
    rows = marketplace_listings(item_type, currency=currency, limit=100)
    units = sorted(
        marketplace_unit_price(row, currency)
        for row in rows
        if marketplace_unit_price(row, currency) > 0
    )
    if not units:
        return None, 0
    top = units[:min(5, len(units))]
    price = median(top) * max(1, int(qty))
    if currency == "token":
        return round(max(0.01, price), 2), len(rows)
    return int(max(1, math.ceil(price))), len(rows)


def trade_prep(me):
    backpack = me.get("backpack") if isinstance(me, dict) else {}
    payload = {}
    if isinstance(backpack, dict):
        for key in ("invSlots", "hotbar", "bankSlots", "cosmeticSlots", "mountSlots", "petSlots", "furnitureSlots"):
            if isinstance(backpack.get(key), list):
                payload[key] = [pack_slot(slot) for slot in backpack.get(key)]
    return http("POST", "/api/auth/trade-prep", payload, timeout=30)


def find_sell_slot(backpack, item_type):
    for kind, key in (("inv", "invSlots"), ("hot", "hotbar")):
        slots = backpack.get(key) if isinstance(backpack, dict) else []
        if not isinstance(slots, list):
            continue
        for index, slot in enumerate(slots):
            if slot_type(slot) == item_type and slot_count(slot) >= SELL_COOKED_QTY:
                return kind, index, slot_count(slot)
    return None


def sell_cooked_fish_once(auto_state=None, quiet=False):
    item_type = "cooked_fish_meat"
    qty = SELL_COOKED_QTY
    try:
        me = get_me()
        backpack = me.get("backpack") or {}
        carry = count_carry_item(backpack, item_type)
        bank = count_bank_item(backpack, item_type)
        total = carry + bank
        if total < SELL_START_COOKED_FISH:
            if not quiet:
                print(f"[{short_now()}] SELL waiting cooked_fish_meat={total}/{SELL_START_COOKED_FISH}")
            return False

        if carry < qty:
            moved = move_bank_item_to_carry(item_type, qty - carry, "SELL")
            if not moved.get("ok"):
                print(f"[{short_now()}] SELL cannot move cooked fish from bank: {moved.get('error')}")
                return False
            me = get_me()
            backpack = me.get("backpack") or {}
            carry = count_carry_item(backpack, item_type)
            if carry < qty:
                print(f"[{short_now()}] SELL still not enough carry={carry}/{qty}")
                return False

        stacked = consolidate_carry_item_stack(item_type, qty, "SELL")
        if not stacked.get("ok"):
            print(f"[{short_now()}] SELL cannot prepare one stack: {stacked.get('error')}")
            return False

        price, rows_seen = marketplace_balanced_price(item_type, qty, SELL_CURRENCY)
        if price is None:
            print(f"[{short_now()}] SELL no live token floor for cooked fish.")
            return False

        prep_status, prep_payload, prep_raw = trade_prep(me)
        if prep_status != 200 or not isinstance(prep_payload, dict) or prep_payload.get("ok") is False:
            print(f"[{short_now()}] SELL trade-prep warning status={prep_status} err={prep_payload.get('error') if isinstance(prep_payload, dict) else None}")

        me = get_me()
        backpack = me.get("backpack") or {}
        slot = find_sell_slot(backpack, item_type)
        if not slot:
            # One quiet refresh/consolidation retry before backing off.
            # This avoids repeated noisy SELL attempts when the server inventory state
            # has not caught up right after a successful listing.
            time.sleep(1.5)
            try:
                me = get_me()
                backpack = me.get("backpack") or {}
                consolidate_carry_item_stack(item_type, qty, "SELL")
                me = get_me()
                backpack = me.get("backpack") or {}
                slot = find_sell_slot(backpack, item_type)
            except Exception:
                slot = None
            if not slot:
                if auto_state is not None:
                    auto_state["sell_next_at"] = time.time() + SELL_NO_SLOT_BACKOFF_SECONDS
                print(f"[{short_now()}] SELL skipped: cooked fish slot not ready; retry later.")
                return False

        slot_kind, slot_index, slot_qty = slot
        payload = {
            "itemType": item_type,
            "slotKind": slot_kind,
            "slotIndex": int(slot_index),
            "quantity": int(qty),
            "currency": SELL_CURRENCY,
            "priceUsd": float(price),
        }
        status, data, raw = http("POST", "/api/marketplace/sell", payload, timeout=30)
        ok = status == 200 and isinstance(data, dict) and data.get("ok") is not False
        if ok:
            if auto_state is not None:
                auto_state["sell_done"] = int(auto_state.get("sell_done", 0) or 0) + 1
            print(f"[{short_now()}] SELL listed {qty} cooked fish | price=${price}")
            return True

        err = data.get("error") if isinstance(data, dict) else None
        print(f"[{short_now()}] SELL failed status={status} err={err}")
        write_error("market sell failed", f"status={status} error={err} payload={json.dumps(payload, separators=(',', ':'))}", raw)
        return False
    except KeyboardInterrupt:
        raise
    except Exception:
        write_error("market sell step error", traceback.format_exc())
        print(f"[{short_now()}] SELL error saved.")
        return False


def sell_step(auto_state):
    if not auto_state or not is_sell_mode(auto_state.get("mode")):
        return
    now_ts = time.time()
    if now_ts < float(auto_state.get("sell_next_at", 0.0) or 0.0):
        return
    ok = sell_cooked_fish_once(auto_state=auto_state, quiet=True)
    now_after = time.time()
    if ok:
        auto_state["sell_next_at"] = now_after + random.uniform(SELL_SUCCESS_COOLDOWN_MIN_SECONDS, SELL_SUCCESS_COOLDOWN_MAX_SECONDS)
    else:
        # Respect a more specific backoff that sell_cooked_fish_once may have set.
        existing_next = float(auto_state.get("sell_next_at", 0.0) or 0.0)
        auto_state["sell_next_at"] = max(existing_next, now_after + SELL_RETRY_SECONDS)



















def run_auto_features(auto_state, allow_sell=False, ws=None, outfit=None, location_state=None, allow_cook=True):
    if not auto_state:
        return

    # Sea fishing is intentionally outside cook range. Cook is allowed only
    # after the Sea cycle moves to Base 1 or Base 3.
    allow_cook = bool(allow_cook and location_allows_cook(location_state))

    if allow_cook and fish_cook_timing_allows(auto_state):
        try:
            cook_step(auto_state, ws=ws, outfit=outfit, location_state=location_state)
        except KeyboardInterrupt:
            raise
        except Exception:
            auto_state["cook_next_at"] = time.time() + COOK_RETRY_SECONDS
            write_error("auto cook wrapper error", traceback.format_exc())
            print(f"[{short_now()}] COOK wrapper error saved. Continuing.")

    if allow_sell:
        try:
            sell_step(auto_state)
        except KeyboardInterrupt:
            raise
        except Exception:
            auto_state["sell_next_at"] = time.time() + SELL_RETRY_SECONDS
            write_error("auto sell wrapper error", traceback.format_exc())
            print(f"[{short_now()}] SELL wrapper error saved. Continuing.")

























def send_land_presence(ws, spot, outfit=None):
    if not ws or not ws.connected:
        raise RuntimeError("Presence websocket was closed.")
    msg = {
        "t": "pos",
        "region": str(spot.get("region") or "pond"),
        "x": float(spot["x"]),
        "y": float(spot.get("y", 0.25)),
        "z": float(spot["z"]),
        "ry": float(spot.get("ry", 0.0)),
        "mov": False,
        "outfit": outfit or {},
        "le": 0,
    }
    if "fc" in spot:
        msg["fc"] = int(spot.get("fc") or 0)
    if "fr" in spot:
        msg["fr"] = int(spot.get("fr") or 0)
    ws.send(json.dumps(msg, separators=(",", ":")))






























































def open_presence_for_same_server_controlled(server, label="SAME SHARD", fast=True):
    """Open presence on the exact same server/shard with retries; never pick another server."""
    if not server:
        raise RuntimeError(f"{label}: current server is missing; refusing random server switch")
    last_exc = None
    for attempt in range(1, SAME_SHARD_REJOIN_ATTEMPTS + 1):
        try:
            name, shard, queue_len = server_display(server)
            if attempt == 1:
                print(f"[{short_now()}] {label}: reconnecting SAME shard {name} (shard={shard})")
            else:
                print(f"[{short_now()}] {label}: same-shard retry {attempt}/{SAME_SHARD_REJOIN_ATTEMPTS}")
            if fast:
                ws, reader_stop = open_presence_for_server_fast(
                    server,
                    max_queue_wait=SAME_SHARD_QUEUE_WAIT_SECONDS,
                )
            else:
                ws, reader_stop = open_presence_for_server(server)
            return server, ws, reader_stop
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            last_exc = exc
            write_error(f"{label.lower()} same-shard reconnect failed", traceback.format_exc())
            if attempt >= SAME_SHARD_REJOIN_ATTEMPTS:
                break
            wait_for_connection_fast(label)
            time.sleep(min(10.0, 2.5 * attempt))
    raise last_exc


def clean_close_presence_for_zone_change(ws, reader_stop, label="ZONE"):
    """Cleanly close presence before changing fishing zones."""
    print(f"[{short_now()}] {label}: clean close before zone change")
    close_presence(ws, reader_stop)
    time.sleep(SAME_SHARD_REJOIN_SETTLE_SECONDS)








def ws_url(path, base=""):
    base = (base or "").strip()
    if base:
        if base.startswith("ws://") or base.startswith("wss://"):
            return base.rstrip("/") + path
        return re.sub(r"^http", "ws", base, flags=re.I).rstrip("/") + path
    return "wss://kintara.gg" + path


def append_ws_connect_token(url, token):
    """Append the current cross-origin lobby token using the game's `kt` key."""
    token = str(token or "").strip()
    if not token:
        return str(url or "")
    separator = "&" if "?" in str(url or "") else "?"
    return f"{url}{separator}kt={urllib.parse.quote(token, safe='')}"


def ws_base_is_cross_origin(ws_base):
    """Return True when the shard websocket host differs from kintara.gg."""
    ws_base = str(ws_base or "").strip()
    if not ws_base:
        return False
    try:
        ws_http = re.sub(r"^wss:", "https:", ws_base, flags=re.I)
        ws_http = re.sub(r"^ws:", "http:", ws_http, flags=re.I)
        target = urllib.parse.urlparse(ws_http)
        origin = urllib.parse.urlparse(BASE)
        target_port = target.port or (443 if target.scheme == "https" else 80)
        origin_port = origin.port or (443 if origin.scheme == "https" else 80)
        return (target.hostname, target_port) != (origin.hostname, origin_port)
    except Exception:
        return True


def server_route_shard_id(server):
    """Resolve the shard id used in Queue/Presence URLs after the regional-server update."""
    if not isinstance(server, dict):
        return 0
    for key in ("routeShardId", "localShardId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def server_global_display_id(server):
    """Resolve the global/display server number shown in the server list."""
    if not isinstance(server, dict):
        return 0
    for key in ("displayId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def server_connection_zone(server):
    if not isinstance(server, dict):
        return ""
    return str(server.get("zone") or server.get("region") or "").strip().lower()


def fetch_ws_connect_token(shard, purpose, ws_base="", zone=""):
    """Fetch the token required by the new regional cross-origin websocket gateways."""
    if not ws_base_is_cross_origin(ws_base):
        return ""

    try:
        shard = max(1, int(float(shard or 0)))
    except Exception:
        shard = 1
    purpose = str(purpose or "queue").strip().lower() or "queue"
    params = {
        "shard": str(shard),
        "purpose": purpose,
    }
    zone = str(zone or "").strip().lower()
    if zone:
        params["zone"] = zone

    path = "/api/lobby/connect-token?" + urllib.parse.urlencode(params)
    status, payload, raw = http(
        "GET",
        path,
        timeout=FAST_HTTP_TIMEOUT,
    )
    if status == 404:
        # Backward compatibility for older/same-origin deployments.
        return ""

    token = str(payload.get("token") or "").strip() if isinstance(payload, dict) else ""
    ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False and token
    if ok:
        return token

    error = payload.get("error") if isinstance(payload, dict) else None
    if is_auth_response(status, error):
        raise RuntimeError("Cookie/login problem while requesting the server connection token.")
    raise RuntimeError(
        f"Lobby connect-token failed purpose={purpose} shard={shard} "
        f"zone={zone or '-'} status={status} error={error} raw={str(raw)[:250]}"
    )


def websocket_proxy_options(proxy_url):
    proxy_url = str(proxy_url or "").strip()
    if not proxy_url:
        return {}
    if "://" not in proxy_url:
        proxy_url = "http://" + proxy_url

    parsed = urllib.parse.urlparse(proxy_url)
    proxy_type = (parsed.scheme or "http").lower()
    if proxy_type in ("http", "https"):
        proxy_type = "http"
    if proxy_type not in ("http", "socks4", "socks4a", "socks5", "socks5h"):
        proxy_type = "http"

    host = parsed.hostname
    port = parsed.port
    if not host:
        return {}
    if port is None:
        port = 443 if (parsed.scheme or "").lower() == "https" else 80

    options = {
        "http_proxy_host": host,
        "http_proxy_port": int(port),
        "proxy_type": proxy_type,
    }
    if parsed.username:
        options["http_proxy_auth"] = (
            urllib.parse.unquote(parsed.username or ""),
            urllib.parse.unquote(parsed.password or ""),
        )
    return options


def create_ws_connection(url, timeout=10, proxy_url="", force_direct=False):
    options = {}
    if force_direct:
        options["http_no_proxy"] = ["*"]
    elif proxy_url:
        options.update(websocket_proxy_options(proxy_url))

    return websocket.create_connection(
        url,
        timeout=timeout,
        cookie=get_cookie(),
        origin=BASE,
        enable_multithread=True,
        header=[
            f"User-Agent: {UA}",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
        ],
        **options,
    )


def open_ws(url, timeout=10):
    ensure_dependency()
    last_exc = None
    # WebSocket TLS handshakes can time out during rapid same-shard zone changes.
    # Retry direct connections a few times instead of falling back to proxy/server switching.
    effective_timeout = max(float(timeout or 0), 20.0)
    for attempt in range(1, 6):
        try:
            return create_ws_connection(url, timeout=effective_timeout, force_direct=True)
        except Exception as exc:
            last_exc = exc
            write_error("websocket direct retry", f"attempt={attempt}/5 url={url} error={exc}")
            if attempt >= 5:
                break
            time.sleep(min(10.0, 2.5 * attempt))
    raise last_exc


def server_name_matches(name, realm_type):
    name = str(name or "")
    if realm_type == "club":
        match = re.fullmatch(r"Kintara Club (\d+)", name)
        return match is not None
    else:
        match = re.fullmatch(r"Server (\d+)", name)
    if not match:
        return False
    return int(match.group(1)) >= MIN_SERVER_NUMBER


def pick_server(realm_type):
    delay = 5.0
    attempt = 0
    while True:
        status, payload, raw = http("GET", "/api/servers", timeout=20)
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok")
        if not ok:
            error = payload.get("error") if isinstance(payload, dict) else None
            if is_auth_response(status, error):
                raise RuntimeError("Cookie/login problem while loading servers. Refresh the cookie with option 4.")
            if is_recoverable_state_error(status, error, raw):
                attempt += 1
                if attempt == 1 or attempt % 6 == 0:
                    write_error("server list transient wait", f"status={status} error={error} raw={str(raw)[:300]}")
                sleep_s = min(60.0, delay) + random.uniform(0.0, 3.0)
                print(f"[{short_now()}] SERVER list unstable status={status}. Waiting {sleep_s:.0f}s, then retrying...")
                time.sleep(sleep_s)
                delay = min(60.0, delay * 1.5)
                continue
            raise RuntimeError(f"/api/servers failed status={status} raw={str(raw)[:300]}")

        rows = []
        for server in payload.get("servers") or []:
            name = str(server.get("name") or "")
            if server_name_matches(name, realm_type):
                rows.append(server)

        if not rows:
            label = "Kintara Club" if realm_type == "club" else "Server"
            if realm_type == "club":
                raise RuntimeError(f"No selectable {label} server was found.")
            raise RuntimeError(f"No selectable {label} server >= {MIN_SERVER_NUMBER} was found.")

        min_queue = min(int(server.get("queueLength") or 0) for server in rows)
        best = [server for server in rows if int(server.get("queueLength") or 0) == min_queue]
        return random.choice(best)


def server_display(server):
    name = str(server.get("name") or "?")
    shard = server_route_shard_id(server)
    queue_len = int(server.get("queueLength") or 0)
    return name, shard, queue_len


def queue_until_ready(shard, ws_base, max_wait=240, zone=""):
    queue_token = fetch_ws_connect_token(
        shard,
        "queue",
        ws_base=ws_base,
        zone=zone,
    )
    url = append_ws_connect_token(
        ws_url(f"/ws/queue/s{shard}", ws_base),
        queue_token,
    )
    ws = open_ws(url)
    ws.settimeout(1.0)
    started = time.time()
    last_print = 0.0
    last_ping = 0.0
    zero_queue_seen_at = None
    zero_queue_seen_count = 0
    zero_queue_assume_ready_after = 25.0
    presence_connect_token = ""

    try:
        while True:
            if time.time() - started > max_wait:
                raise RuntimeError("Queue timeout.")

            if time.time() - last_ping >= 5.0:
                last_ping = time.time()
                try:
                    ws.send(json.dumps({"t": "q_ping"}))
                except Exception:
                    pass

            try:
                msg = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                # Some shards keep sending queue_pos ahead=0/pos=1 but never emit
                # queue_ready. If that state stays stable, continue and request a
                # fresh purpose=presence token before opening Presence.
                if zero_queue_seen_at is not None and time.time() - zero_queue_seen_at >= zero_queue_assume_ready_after:
                    waited = time.time() - zero_queue_seen_at
                    print(f"[{short_now()}] SERVER queue assume-ready: ahead=0 pos=1 stable for {waited:.0f}s")
                    return presence_connect_token
                continue

            msg_type = msg.get("t")
            if msg_type == "queue_ready":
                presence_connect_token = str(msg.get("connectToken") or "").strip()
                return presence_connect_token
            if msg_type == "queue_pos":
                try:
                    ahead = int(float(msg.get("ahead") or 0))
                except Exception:
                    ahead = None
                try:
                    pos = int(float(msg.get("pos") or 0))
                except Exception:
                    pos = None

                if ahead == 0 and pos <= 1:
                    zero_queue_seen_count += 1
                    if zero_queue_seen_at is None:
                        zero_queue_seen_at = time.time()
                    elif time.time() - zero_queue_seen_at >= zero_queue_assume_ready_after:
                        waited = time.time() - zero_queue_seen_at
                        print(f"[{short_now()}] SERVER queue assume-ready: ahead=0 pos={pos} stable for {waited:.0f}s")
                        return presence_connect_token
                else:
                    zero_queue_seen_at = None
                    zero_queue_seen_count = 0

                if time.time() - last_print >= 10.0:
                    last_print = time.time()
                    print(f"[{short_now()}] SERVER queue: ahead={msg.get('ahead')} pos={msg.get('pos')}")
                continue
            if msg_type in ("queue_error", "queue_evicted"):
                raise RuntimeError(f"Queue failed: {msg}")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def open_presence_for_server(server):
    name, shard, queue_len = server_display(server)
    ws_base = str(server.get("wsBaseUrl") or "")
    zone = server_connection_zone(server)
    presence_token = queue_until_ready(
        shard,
        ws_base,
        zone=zone,
    )
    if not presence_token:
        presence_token = fetch_ws_connect_token(
            shard,
            "presence",
            ws_base=ws_base,
            zone=zone,
        )
    presence_url = append_ws_connect_token(
        ws_url(f"/ws/presence/s{shard}", ws_base),
        presence_token,
    )
    ws = open_ws(presence_url)
    reader_stop = start_presence_reader(ws)
    display_id = server_global_display_id(server)
    print(
        f"[{short_now()}] SERVER connected: {name} | "
        f"display={display_id or '?'} route_shard={shard} zone={zone or '-'} queue={queue_len}"
    )
    time.sleep(POST_SERVER_JOIN_WAIT_SECONDS)
    return ws, reader_stop


def open_presence_for_server_with_retry(realm_type, server=None, label="SERVER"):
    current_server = server
    while True:
        try:
            if current_server is None:
                current_server = pick_server(realm_type)
            ws, reader_stop = open_presence_for_server(current_server)
            return current_server, ws, reader_stop
        except KeyboardInterrupt:
            raise
        except Exception:
            write_error(f"{label.lower()} server join retry", traceback.format_exc())
            print(f"[{short_now()}] {label} could not join server. Waiting for stable connection...")
            wait_for_connection()
            wait_before_new_server(label)
            current_server = pick_server(realm_type)


def close_presence(ws, reader_stop):
    if reader_stop:
        reader_stop["value"] = True
    try:
        if ws:
            ws.close()
    except Exception:
        pass


def is_recoverable_connection_error(detail):
    text = str(detail or "").lower()
    markers = (
        "getaddrinfo failed",
        "temporary failure in name resolution",
        "winerror 10054",
        "connectionreseterror",
        "connection reset",
        "connection aborted",
        "forcibly closed",
        "remote host was lost",
        "socket is already closed",
        "websocketconnectionclosedexception",
        "presence websocket was closed",
        "timed out",
        "timeout",
        "network is unreachable",
        "failed to establish a new connection",
        "name or service not known",
        "ssl: eof",
        "ssleoferror",
        "status=0",
        "status=408",
        "status=425",
        "status=429",
        "status=500",
        "status=502",
        "status=503",
        "status=504",
        "status=520",
        "status=521",
        "status=522",
        "status=523",
        "status=524",
        "bad gateway",
        "gateway timeout",
        "service unavailable",
        "cloudflare",
        "origin web server",
        "temporarily unavailable",
    )
    return any(marker in text for marker in markers)


def wait_for_connection():
    delay = 5.0
    attempt = 0
    stable_seen = 0
    last_payload = None
    while True:
        attempt += 1
        status, payload, raw = http("GET", "/api/auth/me", timeout=12)
        if status == 200 and isinstance(payload, dict) and payload.get("ok") and payload.get("player"):
            stable_seen += 1
            last_payload = payload
            if stable_seen >= RECOVERY_STABLE_CHECKS:
                print(f"[{short_now()}] RECOVER online and stable.")
                return last_payload
            pass
            time.sleep(RECOVERY_STABLE_GAP_SECONDS)
            continue

        stable_seen = 0
        error = str(payload.get("error") if isinstance(payload, dict) else "")
        if is_auth_response(status, error):
            raise RuntimeError("Cookie/login problem during recovery. Refresh the cookie with option 4.")

        if attempt == 1 or attempt % 6 == 0:
            write_error("network recovery waiting", f"status={status} error={error} raw={str(raw)[:300]}")

        sleep_s = min(60.0, delay) + random.uniform(0.0, 3.0)
        print(f"[{short_now()}] RECOVER waiting for connection")
        time.sleep(sleep_s)
        delay = min(60.0, delay * 1.5)


def wait_for_connection_fast(label="FAST RECOVER"):
    """Fast online check used by same-shard fishing-zone recovery."""
    delay = 1.0
    attempt = 0
    stable_seen = 0
    last_payload = None
    while True:
        attempt += 1
        status, payload, raw = http("GET", "/api/auth/me", timeout=8)
        if status == 200 and isinstance(payload, dict) and payload.get("ok") and payload.get("player"):
            stable_seen += 1
            last_payload = payload
            if stable_seen >= FAST_RECOVERY_STABLE_CHECKS:
                print(f"[{short_now()}] {label} online. Resuming immediately.")
                return last_payload
            time.sleep(0.35)
            continue

        stable_seen = 0
        error = str(payload.get("error") if isinstance(payload, dict) else "")
        if is_auth_response(status, error):
            raise RuntimeError("Cookie/login problem during recovery. Refresh the cookie with option 4.")
        if attempt == 1 or attempt % 10 == 0:
            write_error("fast recovery waiting", f"status={status} error={error} raw={str(raw)[:300]}")
        sleep_s = min(FAST_RECOVERY_RETRY_MAX_SECONDS, delay) + random.uniform(0.0, 0.35)
        print(f"[{short_now()}] {label} waiting for connection")
        time.sleep(sleep_s)
        delay = min(FAST_RECOVERY_RETRY_MAX_SECONDS, delay * 1.4)




def open_presence_for_server_fast(server, max_queue_wait=8.0):
    name, shard, queue_len = server_display(server)
    ws_base = str(server.get("wsBaseUrl") or "")
    zone = server_connection_zone(server)
    presence_token = queue_until_ready(
        shard,
        ws_base,
        max_wait=max_queue_wait,
        zone=zone,
    )
    if not presence_token:
        presence_token = fetch_ws_connect_token(
            shard,
            "presence",
            ws_base=ws_base,
            zone=zone,
        )
    presence_url = append_ws_connect_token(
        ws_url(f"/ws/presence/s{shard}", ws_base),
        presence_token,
    )
    ws = open_ws(presence_url, timeout=4)
    reader_stop = start_presence_reader(ws)
    print(
        f"[{short_now()}] FAST reconnected: {name} | "
        f"route_shard={shard} zone={zone or '-'} queue={queue_len}"
    )
    return ws, reader_stop









def reconnect_session(realm_type, current_server, ws, reader_stop):
    close_presence(ws, reader_stop)
    me = wait_for_connection()
    outfit = me.get("outfit") or {}
    current_fish = count_raw_fish_from_backpack(me.get("backpack") or {})

    try:
        print(f"[{short_now()}] RECOVER trying the same server...")
        new_ws, new_reader_stop = open_presence_for_server(current_server)
        time.sleep(random.uniform(1.5, 3.0))
        wait_after_recovery("RECOVER")
        return current_server, new_ws, new_reader_stop, outfit, current_fish
    except KeyboardInterrupt:
        raise
    except Exception:
        write_error("same server reconnect failed", traceback.format_exc())
        print(f"[{short_now()}] RECOVER same server failed. Picking a server...")

    while True:
        try:
            wait_before_new_server("RECOVER")
            new_server = pick_server(realm_type)
            new_ws, new_reader_stop = open_presence_for_server(new_server)
            time.sleep(random.uniform(1.5, 3.0))
            wait_after_recovery("RECOVER")
            return new_server, new_ws, new_reader_stop, outfit, current_fish
        except KeyboardInterrupt:
            raise
        except Exception:
            write_error("reconnect failed", traceback.format_exc())
            print(f"[{short_now()}] RECOVER reconnect failed. Waiting again...")
            wait_for_connection()


def wait_after_recovery(label="RECOVER"):
    delay = random.uniform(RECOVERY_SETTLE_MIN_SECONDS, RECOVERY_SETTLE_MAX_SECONDS)
    print(f"[{short_now()}] RECOVER stable; continuing")
    time.sleep(delay)


def safe_deposit_raw_fish_to_bank(label="BANK"):
    while True:
        try:
            return deposit_raw_fish_to_bank(label)
        except KeyboardInterrupt:
            raise
        except Exception:
            detail = traceback.format_exc()
            if is_auth_problem_detail(detail):
                raise
            write_error(f"{label.lower()} deposit transient wait", detail)
            print(f"[{short_now()}] {label} state check failed. Waiting for stable server, then retrying...")
            wait_for_connection()
            time.sleep(random.uniform(2.0, 5.0))


def skip_raw_fish_bank_when_cooking(mode, auto_state, label="BANK"):
    """During an active cook cycle, raw fish in carry is cook fuel.
    Reconnect/recovery must not bank that fuel and immediately pull it
    back through the Cook refill path.
    """
    if is_cook_mode(mode) and bool(auto_state.get("cook_active")):
        try:
            me = get_me()
            carry_fish = count_raw_fish_from_backpack(me.get("backpack") or {})
        except Exception:
            carry_fish = 0
        print(f"[{short_now()}] {label} raw-fish deposit skipped during cook/recover | carry={carry_fish}")
        return {"ok": True, "skipped": True, "reason": "cook_active", "carry_fish": carry_fish}
    return None


def clone_spot(spot):
    cloned = {
        "x": float(spot["x"]),
        "y": float(spot["y"]),
        "z": float(spot["z"]),
        "ry": float(spot["ry"]),
        "fc": int(spot["fc"]),
        "fr": int(spot["fr"]),
        "region": str(spot.get("region") or "pond"),
    }
    if "fph" in spot:
        cloned["fph"] = int(spot.get("fph") or 0)
    return cloned


def wait_before_new_server(label="SERVER"):
    delay = random.uniform(NEW_SERVER_DELAY_MIN_SECONDS, NEW_SERVER_DELAY_MAX_SECONDS)
    pass
    time.sleep(delay)


def fish_location_kind(location):
    if not isinstance(location, dict):
        return "base"
    explicit = str(location.get("kind") or "").strip().lower()
    if explicit in ("base", "sea"):
        return explicit
    first_hook = (location.get("hooks") or [{}])[0]
    return "sea" if str(first_hook.get("region") or "pond") == "beach" else "base"


def fish_location_is_sea(location):
    return fish_location_kind(location) == "sea"


def location_state_is_sea(location_state):
    try:
        return fish_location_is_sea(current_location(location_state))
    except Exception:
        return False


def location_allows_cook(location_state):
    return not location_state_is_sea(location_state)


def selected_sea_location(location_state):
    selected = location_state.get("selected_sea_location") if isinstance(location_state, dict) else None
    return selected if isinstance(selected, dict) else None


def sea_cycle_enabled(location_state, mode):
    return (
        is_cook_mode(mode)
        and selected_sea_location(location_state) is not None
    )


def sea_cycle_base_candidates():
    by_key = {
        str(location.get("key")): location
        for location in BASE_FISH_LOCATIONS
        if isinstance(location, dict)
    }
    return [
        by_key[key]
        for key in SEA_COOK_BASE_KEYS
        if key in by_key
    ]


def set_active_fish_location(location_state, location):
    location_state["locations"] = [location]
    location_state["location_index"] = 0
    location_state["hook_index"] = 0
    location_state["fish_since_hook_switch"] = 0
    location_state["active_location_kind"] = fish_location_kind(location)
    location_state["active_location_key"] = str(location.get("key") or "")


def sea_cycle_transition_target(location_state, mode, total_raw_fish):
    """Return the next location for the Sea<->Base cook cycle, or None."""
    if not sea_cycle_enabled(location_state, mode):
        return None

    if total_raw_fish is None:
        return None
    total_raw_fish = max(0, int(total_raw_fish or 0))
    active = current_location(location_state)

    if fish_location_is_sea(active):
        if total_raw_fish < SEA_COOK_START_RAW_FISH:
            return None
        candidates = sea_cycle_base_candidates()
        if not candidates:
            raise RuntimeError("Sea cycle has no Base 1/Base 3 candidates.")
        return random.choice(candidates)

    if total_raw_fish <= SEA_COOK_STOP_RAW_FISH:
        return selected_sea_location(location_state)

    return None


def current_total_raw_fish_fast(label="SEA CYCLE"):
    """One-shot total raw-fish read; transient failures postpone switching."""
    try:
        me = get_me_fast(label)
        backpack = me.get("backpack") or {}
        return count_total_item(backpack, "fish")
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        if is_auth_problem_detail(str(exc)):
            raise
        write_error(
            "sea cycle raw-fish status temporary",
            f"label={label} error={exc}",
        )
        return None


def prime_current_fish_location(ws, outfit, location_state):
    """Prime the active fishing zone after a clean same-shard reconnect."""
    location = current_location(location_state)
    land = location.get("land") if isinstance(location, dict) else None
    if isinstance(land, dict):
        send_land_presence(ws, land, outfit)
        time.sleep(FISH_ZONE_PRIME_GAP_SECONDS)
    send_presence(ws, 0, current_spot(location_state), outfit)


def switch_fish_location_same_shard(
    server,
    ws,
    reader_stop,
    outfit,
    current_fish,
    auto_state,
    location_state,
    target_location,
):
    """Switch Base<->Sea through a clean close and same-shard reconnect."""
    source_location = current_location(location_state)
    source_kind = fish_location_kind(source_location).upper()
    target_kind = fish_location_kind(target_location).upper()
    label = f"FISH {source_kind}->{target_kind}"

    clean_close_presence_for_zone_change(ws, reader_stop, label)
    set_active_fish_location(location_state, target_location)

    server, ws, reader_stop = open_presence_for_same_server_controlled(
        server,
        label,
        fast=True,
    )
    prime_current_fish_location(ws, outfit, location_state)

    auto_state["join_cook_done"] = 0
    auto_state["_cook_bank_skip_logged"] = False
    auto_state["cook_next_at"] = 0.0

    if location_allows_cook(location_state):
        auto_state["cook_active"] = False
        run_join_cook_if_needed(
            auto_state.get("mode"),
            auto_state,
            ws=ws,
            outfit=outfit,
            location_state=location_state,
        )
    else:
        auto_state["cook_active"] = False
        auto_state["cook_cycle_done"] = 0
        auto_state["cook_cycle_start_raw"] = 0

    try:
        me = get_me_fast(label)
        outfit = me.get("outfit") or outfit or {}
        current_fish = count_raw_fish_from_backpack(me.get("backpack") or {})
        total_raw = count_total_item(me.get("backpack") or {}, "fish")
    except Exception:
        total_raw = None

    print(
        f"[{short_now()}] LOCATION switched on SAME shard | "
        f"{source_location.get('name')} -> {target_location.get('name')} | "
        f"raw_total={total_raw if total_raw is not None else '?'}"
    )
    return server, ws, reader_stop, outfit, current_fish


def location_hook_count(location):
    hooks = location.get("hooks") if isinstance(location, dict) else []
    return len(hooks) if isinstance(hooks, list) else 0


def location_summary(location):
    hooks = location_hook_count(location)
    first = location["hooks"][0]
    return (
        f"{location['name']} | hooks={hooks} | "
        f"stand=({first['x']},{first['y']},{first['z']})"
    )


def choose_int_with_default(prompt, default_value, min_value=1):
    raw = input(f"{prompt} [{default_value}]: ").strip()
    if not raw:
        return int(default_value)
    try:
        return max(int(min_value), int(float(raw)))
    except Exception:
        print(f"Invalid number. Using {default_value}.")
        return int(default_value)


def build_location_state(
    mode,
    locations,
    switch_every=FISH_HOOK_SWITCH_EVERY,
    location_index=None,
):
    locations = [loc for loc in locations if location_hook_count(loc) > 0]
    if not locations:
        locations = [FISH_LOCATIONS[0]]

    if location_index is None:
        location_index = 0
    location_index = max(0, min(int(location_index), len(locations) - 1))

    selected_location = locations[location_index]
    selected_sea = selected_location if fish_location_is_sea(selected_location) else None

    return {
        "mode": mode,
        "locations": locations,
        "location_index": location_index,
        "hook_index": 0,
        "fish_since_hook_switch": 0,
        "switch_every": max(1, int(switch_every)),
        "selected_sea_location": selected_sea,
        "active_location_kind": fish_location_kind(selected_location),
        "active_location_key": str(selected_location.get("key") or ""),
    }


def current_location(location_state):
    locations = location_state.get("locations") or [FISH_LOCATIONS[0]]
    index = int(location_state.get("location_index", 0) or 0) % len(locations)
    location_state["location_index"] = index
    return locations[index]


def current_spot(location_state):
    location = current_location(location_state)
    hooks = location.get("hooks") or [SPOT]
    hook_index = int(location_state.get("hook_index", 0) or 0) % len(hooks)
    location_state["hook_index"] = hook_index
    return clone_spot(hooks[hook_index])


def current_location_label(location_state):
    location = current_location(location_state)
    hooks = location.get("hooks") or [SPOT]
    hook_index = int(location_state.get("hook_index", 0) or 0) % len(hooks)
    return f"{location['name']} | hook {hook_index + 1}/{len(hooks)}"


def advance_hook(location_state, reason="fish threshold"):
    location = current_location(location_state)
    hooks = location.get("hooks") or [SPOT]
    if len(hooks) <= 1:
        location_state["hook_index"] = 0
        return
    location_state["hook_index"] = (int(location_state.get("hook_index", 0) or 0) + 1) % len(hooks)
    spot = current_spot(location_state)
    print(f"[{short_now()}] FISH hook switched: {current_location_label(location_state)}")


def record_location_catch(location_state, fish_delta):
    gained = max(0, int(fish_delta or 0))
    if gained <= 0:
        return

    location_state["fish_since_hook_switch"] = int(location_state.get("fish_since_hook_switch", 0) or 0) + gained
    switch_every = max(1, int(location_state.get("switch_every", FISH_HOOK_SWITCH_EVERY) or FISH_HOOK_SWITCH_EVERY))
    while location_state["fish_since_hook_switch"] >= switch_every:
        location_state["fish_since_hook_switch"] -= switch_every
        advance_hook(location_state, reason=f"{switch_every} fish")


def add_location_active_seconds(location_state, seconds):
    return


def start_presence_reader(ws):
    stop = {"value": False}

    def run():
        ws.settimeout(1.0)
        while not stop["value"]:
            try:
                ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return stop


def send_presence(ws, phase, spot, outfit):
    msg = {
        "t": "pos",
        "region": str(spot.get("region") or "pond"),
        "x": float(spot["x"]),
        "y": float(spot["y"]),
        "z": float(spot["z"]),
        "ry": float(spot["ry"]),
        "mov": False,
        "outfit": outfit or {},
        "le": 0,
        "act": "fish",
        "fc": int(spot["fc"]),
        "fr": int(spot["fr"]),
        "fph": int(phase),
        "eq": "tool_fishing_rod",
    }
    ws.send(json.dumps(msg, separators=(",", ":")))


def prime_join_cook_location(ws, outfit, location_state):
    for index in range(1, JOIN_LOCATION_PRIME_MESSAGES + 1):
        prime_current_fish_location(ws, outfit, location_state)
        if index < JOIN_LOCATION_PRIME_MESSAGES:
            time.sleep(JOIN_LOCATION_PRIME_DELAY_SECONDS)


def cook_after_server_join(auto_state=None, count=SERVER_JOIN_COOK_COUNT, ws=None, outfit=None, location_state=None):
    target = int(count or 0)
    if target <= 0:
        return 0

    already_done = int(auto_state.get("join_cook_done", 0) or 0) if auto_state is not None else 0
    if already_done >= target:
        return already_done


    attempts = 0
    while already_done < target and attempts < JOIN_COOK_ATTEMPTS:
        attempts += 1
        wait_for_cook_cooldown(auto_state)
        status, payload, raw = cook_raw_fish_once()
        ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is not False
        err = payload.get("error") if isinstance(payload, dict) else None

        if ok:
            already_done += 1
            if auto_state is not None:
                auto_state["cook_done"] = int(auto_state.get("cook_done", 0) or 0) + 1
                auto_state["join_cook_done"] = already_done
                set_cook_cooldown(auto_state)
            print(f"[{short_now()}] COOK location ready")
        else:
            write_error("join cook failed", f"attempt={attempts} status={status} error={err}", raw)
            if status == 429:
                set_cook_cooldown(auto_state)
            if is_cook_location_error(err) and ws is not None and location_state is not None:
                try:
                    prime_join_cook_location(ws, outfit, location_state)
                except Exception:
                    write_error("join cook location refresh failed", traceback.format_exc())

            if err in ("unauthorized", "forbidden"):
                break

        if already_done < target and attempts < JOIN_COOK_ATTEMPTS:
            time.sleep(JOIN_COOK_ATTEMPT_DELAY_SECONDS)

    if already_done < target:
        print(f"[{short_now()}] JOIN COOK not confirmed. Details saved to {ERROR_LOG.name}.")
    return already_done


def join_cook_needed(mode, auto_state):
    if not is_cook_mode(mode):
        return False
    return int(auto_state.get("join_cook_done", 0) or 0) < SERVER_JOIN_COOK_COUNT


def run_join_cook_if_needed(mode, auto_state, ws=None, outfit=None, location_state=None):
    if not location_allows_cook(location_state):
        return int(auto_state.get("join_cook_done", 0) or 0)
    if not join_cook_needed(mode, auto_state):
        return 0
    return cook_after_server_join(
        auto_state=auto_state,
        count=SERVER_JOIN_COOK_COUNT,
        ws=ws,
        outfit=outfit,
        location_state=location_state,
    )


def send_phase(ws, phase, seconds, spot, outfit, auto_state=None, location_state=None):
    end_at = time.time() + float(seconds)
    while time.time() < end_at:
        fish_daily_guard(auto_state)
        if not ws.connected:
            raise RuntimeError("Presence websocket was closed.")
        send_presence(ws, phase, spot, outfit)
        run_auto_features(auto_state, allow_sell=False, ws=ws, outfit=outfit, location_state=location_state, allow_cook=True)
        base_sleep = random.uniform(1.65, 2.35)
        sleep_time = min(base_sleep, max(0.05, end_at - time.time()))
        time.sleep(fish_daily_sleep_slice(auto_state, sleep_time))
    fish_daily_guard(auto_state)
    send_presence(ws, phase, spot, outfit)


def random_cast_times(last_post_ts=None):
    strike_s = random.uniform(STRIKE_MIN, STRIKE_MAX)
    reel_s = random.uniform(REEL_MIN, REEL_MAX)
    post_delay_s = random.uniform(POST_DELAY_MIN, POST_DELAY_MAX)
    target_gap = random.uniform(MIN_POST_GAP, MAX_POST_GAP)

    if last_post_ts:
        elapsed = time.time() - last_post_ts
        desired_total = target_gap - elapsed
        wait_s = desired_total - strike_s - reel_s - post_delay_s
        wait_s = max(WAIT_MIN, min(WAIT_MAX, wait_s))
    else:
        wait_s = random.uniform(WAIT_MIN, WAIT_MAX)

    return wait_s, strike_s, reel_s, post_delay_s, target_gap


def sleep_auto_watch(seconds, auto_state=None, ws=None, outfit=None, location_state=None, allow_cook=True):
    end_at = time.time() + max(0.0, float(seconds or 0.0))
    while time.time() < end_at:
        run_auto_features(auto_state, allow_sell=False, ws=ws, outfit=outfit, location_state=location_state, allow_cook=allow_cook)
        time.sleep(min(1.0, max(0.05, end_at - time.time())))


def guard_min_post_gap(last_post_ts, planned_total, target_gap, auto_state=None, ws=None, outfit=None, location_state=None):
    if not last_post_ts:
        return 0.0
    predicted_gap = (time.time() - last_post_ts) + planned_total
    if predicted_gap >= target_gap:
        return 0.0
    sleep_s = target_gap - predicted_gap + random.uniform(0.10, 0.35)
    sleep_s = fish_daily_sleep_slice(auto_state, sleep_s)
    sleep_auto_watch(sleep_s, auto_state=auto_state, ws=ws, outfit=outfit, location_state=location_state, allow_cook=False)
    fish_daily_guard(auto_state)
    return sleep_s


def cast_once(
    ws,
    outfit,
    before_fish,
    cast_no,
    last_post_ts,
    auto_state=None,
    spot=None,
    location_label="",
    location_state=None,
):
    spot = clone_spot(spot or SPOT)
    wait_s, strike_s, reel_s, post_delay_s, target_gap = random_cast_times(last_post_ts)
    planned_total = wait_s + strike_s + reel_s + post_delay_s
    guard_min_post_gap(last_post_ts, planned_total, target_gap, auto_state=auto_state, ws=ws, outfit=outfit, location_state=location_state)

    if auto_state is not None:
        cast_started_at = time.time()
        auto_state["fish_cast_started_at"] = cast_started_at
        auto_state["fish_expected_post_at"] = cast_started_at + planned_total
        # Let cook run shortly after the cast begins, but never exactly on the
        # fish action itself.  This normally gives room for 3 cook attempts in a
        # ~40s fish cycle, depending on COOK_DELAY_SECONDS and HTTP latency.
        auto_state["fish_cook_allowed_from"] = max(
            float(auto_state.get("fish_cook_allowed_from", 0.0) or 0.0),
            cast_started_at + FISH_COOK_AFTER_CAST_START_SECONDS,
        )
        auto_state["fish_post_in_progress"] = False

    # Compact logs: no per-cast timing details.
    send_phase(ws, 0, wait_s, spot, outfit, auto_state=auto_state, location_state=location_state)
    send_phase(ws, 1, strike_s, spot, outfit, auto_state=auto_state, location_state=location_state)
    send_phase(ws, 2, reel_s, spot, outfit, auto_state=auto_state, location_state=location_state)
    # Keep automatic cook checks active during this sub-second delay.
    post_delay_s = fish_daily_sleep_slice(auto_state, post_delay_s)
    sleep_auto_watch(post_delay_s, auto_state=auto_state, ws=ws, outfit=outfit, location_state=location_state, allow_cook=False)

    # Mandatory final cap check immediately before every grant-fish-xp request.
    fish_daily_guard(auto_state)
    if auto_state is not None:
        auto_state["fish_post_in_progress"] = True
    post_ts = time.time()
    actual_post_gap = post_ts - last_post_ts if last_post_ts else None
    try:
        status, payload, raw = http("POST", "/api/auth/grant-fish-xp", {"mountCatch": True})
    finally:
        if auto_state is not None:
            auto_state["fish_post_in_progress"] = False
            auto_state["fish_last_post_at"] = post_ts
            auto_state["fish_expected_post_at"] = 0.0
            auto_state["fish_cook_allowed_from"] = post_ts + FISH_COOK_AFTER_FISH_POST_SECONDS
    ok = status == 200 and payload.get("ok") is True
    error = payload.get("error")

    if ok and isinstance(payload.get("backpack"), dict):
        after_fish = count_raw_fish_from_backpack(payload.get("backpack"))
    else:
        time.sleep(0.8)
        after_fish = count_raw_fish_from_backpack(get_me().get("backpack") or {})

    raw_delta = after_fish - before_fish
    # cooking/bank bulk-refill can change the raw-fish carry count by hundreds/thousands
    # between casts. A successful grant-fish-xp call represents this cast succeeding, not that
    # whole inventory-count delta. Count one catch per successful cast and keep raw_delta only
    # for diagnostics.
    delta = 1 if ok else raw_delta
    gap_text = "first" if actual_post_gap is None else f"{actual_post_gap:.1f}s"

    if ok and delta > 0:
        if abs(raw_delta) > 3:
            print(f"[{short_now()}] FISH #{cast_no:03d} +1 | carry={after_fish} | raw_delta={raw_delta}")
        else:
            print(f"[{short_now()}] FISH #{cast_no:03d} +{delta} | carry={after_fish}")
    else:
        print(f"[{short_now()}] FISH #{cast_no:03d} failed | {error or status}")
        write_error(
            "catch failed",
            f"cast={cast_no} status={status} error={error} before={before_fish} after={after_fish} gap={gap_text}",
            raw,
        )

    return {
        "ok": ok,
        "status": status,
        "error": error,
        "before": before_fish,
        "after": after_fish,
        "delta": delta,
        "raw_delta": raw_delta,
        "post_ts": post_ts,
        "actual_post_gap": actual_post_gap,
    }


def choose_realm_type():
    clear_screen()
    print("=========== Server Type ===========")
    print("1) Normal / Free Server")
    print("2) Club")
    print("===================================")
    choice = input("Choose [1]: ").strip()
    return "club" if choice == "2" else "free"


def choose_farm_target():
    print("\n=========== Start Farm ===========")
    print("1) Unlimited (default)")
    print("2) Choose amount")
    print("==================================")
    choice = input("Choose [1]: ").strip()
    if choice != "2":
        return None

    raw = input("Raw fish amount: ").strip()
    try:
        return max(1, int(float(raw)))
    except Exception:
        print("Invalid amount. Running unlimited.")
        return None


def choose_farm_mode():
    print("\n=========== Farm Mode ===========")
    print("1) Farm raw fish only")
    print(f"2) Farm + cook raw fish {COOK_START_RAW_FISH} -> {COOK_STOP_RAW_FISH}")
    print("3) Sell 500 cooked fish when cooked reaches 2500")
    print("4) Full auto: farm + cook + sell")
    print("=================================")
    choice = input("Choose [1]: ").strip()
    if choice == "2":
        return "farm_cook"
    if choice == "3":
        return "sell_only"
    if choice == "4":
        return "full_auto"
    return "farm_only"


def choose_location_state():
    saved_settings = _read_location_settings()
    saved_fish_key = str(saved_settings.get("fish_location_key") or "")
    default_location_index = next(
        (index for index, location in enumerate(FISH_LOCATIONS) if str(location.get("key") or "") == saved_fish_key),
        0,
    )
    try:
        default_switch_every = max(
            1,
            int(saved_settings.get("fish_switch_every", FISH_HOOK_SWITCH_EVERY)),
        )
    except Exception:
        default_switch_every = FISH_HOOK_SWITCH_EVERY

    print("\n=========== Fish Location ===========")
    print("--- Base / old cook locations ---")
    for index, location in enumerate(BASE_FISH_LOCATIONS, start=1):
        print(f"{index}) {location_summary(location)}")
    print("--- Sea / new beach locations ---")
    offset = len(BASE_FISH_LOCATIONS)
    for sea_index, location in enumerate(SEA_FISH_LOCATIONS, start=1):
        print(f"{offset + sea_index}) {location_summary(location)}")
    print("=====================================")
    raw = input(f"Choose location [{default_location_index + 1}]: ").strip()
    try:
        location_index = max(
            0,
            min(
                len(FISH_LOCATIONS) - 1,
                int(float(raw or str(default_location_index + 1))) - 1,
            ),
        )
    except Exception:
        location_index = default_location_index

    switch_every = choose_int_with_default(
        "Change hook after how many caught fish?",
        default_switch_every,
        min_value=1,
    )
    state = build_location_state("manual", [FISH_LOCATIONS[location_index]], switch_every=switch_every)
    _update_location_settings({
        "fish_location_key": str(FISH_LOCATIONS[location_index].get("key") or ""),
        "fish_switch_every": int(switch_every),
    })
    print(f"[{short_now()}] LOCATION selected: {current_location_label(state)} | switch_every={switch_every}")
    return state


def mode_label(mode):
    labels = {
        "farm_only": "Farm raw fish only",
        "farm_cook": f"Farm + cook {COOK_START_RAW_FISH}->{COOK_STOP_RAW_FISH}",
        "sell_only": "Sell cooked fish x500",
        "full_auto": "Full auto farm + cook + sell",
    }
    return labels.get(mode, str(mode))


def build_auto_state(mode):
    state = {
        "mode": mode,
        "cook_active": False,
        "cook_done": 0,
        "cook_cycle_done": 0,
        "cook_cycle_start_raw": 0,
        "join_cook_done": 0,
        "cook_next_at": 0.0,
        "_cook_bank_skip_logged": False,
        "sell_done": 0,
        "sell_next_at": 0.0,
        "fish_cast_started_at": 0.0,
        "fish_last_post_at": 0.0,
        "fish_expected_post_at": 0.0,
        "fish_cook_allowed_from": 0.0,
        "fish_post_in_progress": False,
    }
    fish_daily_initialize(state)
    return state


def fish_cook_timing_allows(auto_state):
    """Allow cook between fish actions, but not on top of the fish POST.

    The fish and cook endpoints are separate, but this scheduler keeps their
    HTTP actions from firing in the same unsafe moment.  Cook can run after the
    cast starts, then repeatedly during the middle of the fish interval, and it
    is skipped only when we are too close to the next grant-fish-xp POST.
    """
    if not auto_state:
        return True
    now_ts = time.time()
    if bool(auto_state.get("fish_post_in_progress")):
        return False
    allowed_from = float(auto_state.get("fish_cook_allowed_from", 0.0) or 0.0)
    if allowed_from > 0 and now_ts < allowed_from:
        return False
    expected_post_at = float(auto_state.get("fish_expected_post_at", 0.0) or 0.0)
    if expected_post_at > 0 and (expected_post_at - now_ts) <= FISH_COOK_BEFORE_FISH_POST_GUARD_SECONDS:
        return False
    return True


def sleep_with_auto(seconds, auto_state=None, allow_sell=False, ws=None, outfit=None, location_state=None, allow_cook=True):
    end_at = time.time() + max(0.0, float(seconds))
    while time.time() < end_at:
        run_auto_features(auto_state, allow_sell=allow_sell, ws=ws, outfit=outfit, location_state=location_state, allow_cook=allow_cook)
        time.sleep(min(1.0, max(0.05, end_at - time.time())))


def is_recoverable_catch_error(error, status):
    error = str(error or "")
    if error in (
        "fish_action_stale",
        "fish_action_required",
        "fish_action_missing",
        "bad_fish_action",
        "stale",
    ):
        return True
    return int(status or 0) in (0, 400, 408, 409, 425, 429, 500, 502, 503, 504)


def farm_loop(realm_type, location_state, forced_mode=None):
    ensure_dependency()
    mode = forced_mode or choose_farm_mode()
    if forced_mode:
        print(f"\n=========== Quick Start Mode ===========")
        print(f"Mode: {mode_label(mode)}")
        print("========================================")
    if mode == "sell_only":
        print("\n=========== Market Sell ===========")
        print("Item: cooked_fish_meat")
        print(f"Quantity: {SELL_COOKED_QTY}")
        print(f"Start selling at cooked_fish_meat: {SELL_START_COOKED_FISH}")
        print("Currency: token")
        print("Strategy: balanced")
        print("===================================\n")
        sell_cooked_fish_once()
        pause()
        return

    target = choose_farm_target()
    auto_state = build_auto_state(mode)
    fish_daily_wait_before_start_if_needed(auto_state)

    me = get_me()
    outfit = me.get("outfit") or {}
    before_fish = count_raw_fish_from_backpack(me.get("backpack") or {})
    before_bank_fish = count_bank_fish(me.get("backpack") or {})
    start_total_fish = before_fish + before_bank_fish

    # in cook modes, do not bank all raw fish right before cooking starts.
    # Startup banking could move fish to bank and immediately
    # pull it back for cooking. If total raw fish is already enough to cook, keep the carry
    # state as-is and let the cook refill logic pull only what is needed from bank.
    if (
        is_cook_mode(mode)
        and location_allows_cook(location_state)
        and start_total_fish >= COOK_START_RAW_FISH
    ):
        initial_deposit = {
            "ok": True,
            "skipped": True,
            "reason": "cook_mode_ready",
            "carry_fish": before_fish,
            "bank_fish": before_bank_fish,
        }
        print(f"[{short_now()}] BANK startup deposit skipped: cook mode will use raw fish carry={before_fish} bank={before_bank_fish}")
    else:
        initial_deposit = safe_deposit_raw_fish_to_bank("BANK")
        if initial_deposit.get("ok"):
            before_fish = int(initial_deposit.get("carry_fish", before_fish) or 0)
            before_bank_fish = int(initial_deposit.get("bank_fish", before_bank_fish) or 0)
        elif initial_deposit.get("error") == "bank_full" and not initial_deposit.get("inventory_has_room"):
            wait_result = wait_for_storage_space()
            before_fish = int(wait_result.get("carry_fish", before_fish) or 0)
            before_bank_fish = int(wait_result.get("bank_fish", before_bank_fish) or 0)

    server = pick_server(realm_type)
    server_name, shard, queue_len = server_display(server)

    print("\n=========== Farm Started ===========")
    print(f"Mode: {mode_label(mode)}")
    print(f"Server type: {'Club' if realm_type == 'club' else 'Normal / Free'}")
    print(f"Server: {server_name} | queue={queue_len}")
    print(f"Target: {'Unlimited' if target is None else target}")
    print(f"Fish location: {current_location_label(location_state)}")
    print(f"Start raw fish: carry={before_fish} bank={before_bank_fish} total={start_total_fish}")
    if sea_cycle_enabled(location_state, mode):
        selected_sea = selected_sea_location(location_state)
        print(
            f"Sea cycle: {selected_sea.get('name')} until raw={SEA_COOK_START_RAW_FISH} "
            f"-> random Base 1/3 Fish+Cook until raw={SEA_COOK_STOP_RAW_FISH} "
            f"-> return to the same Sea"
        )
    elif is_cook_mode(mode):
        print(f"Cook: {COOK_START_RAW_FISH}->{COOK_STOP_RAW_FISH}")
    if is_sell_mode(mode):
        print(f"Sell: {SELL_COOKED_QTY} cooked fish when total reaches {SELL_START_COOKED_FISH}")
    print("Stop with Ctrl+C.")
    print("====================================\n")

    server, ws, reader_stop = open_presence_for_server_with_retry(realm_type, server, "START")


    caught = 0
    casts = 0
    errors = 0
    last_post_ts = None
    current_fish = before_fish

    try:
        time.sleep(random.uniform(1.5, 3.0))
        if location_state_is_sea(location_state):
            prime_current_fish_location(ws, outfit, location_state)
        elif join_cook_needed(mode, auto_state):
            prime_join_cook_location(ws, outfit, location_state)
        run_join_cook_if_needed(mode, auto_state, ws=ws, outfit=outfit, location_state=location_state)
        try:
            current_fish = count_raw_fish_from_backpack(get_me().get("backpack") or {})
        except Exception:
            pass
        while target is None or caught < target:
            try:

                if sea_cycle_enabled(location_state, mode):
                    raw_total = current_total_raw_fish_fast("SEA CYCLE")
                    target_location = (
                        sea_cycle_transition_target(
                            location_state,
                            mode,
                            raw_total,
                        )
                        if raw_total is not None
                        else None
                    )
                    if target_location is not None:
                        server, ws, reader_stop, outfit, current_fish = (
                            switch_fish_location_same_shard(
                                server,
                                ws,
                                reader_stop,
                                outfit,
                                current_fish,
                                auto_state,
                                location_state,
                                target_location,
                            )
                        )
                        last_post_ts = time.time()
                        continue

                casts += 1
                spot = current_spot(location_state)
                location_label = current_location_label(location_state)
                cast_started_ts = time.time()
                fish_daily_start(auto_state)
                try:
                    result = cast_once(
                        ws,
                        outfit,
                        current_fish,
                        casts,
                        last_post_ts,
                        auto_state=auto_state,
                        spot=spot,
                        location_label=location_label,
                        location_state=location_state,
                    )
                finally:
                    fish_daily_pause(auto_state)
            except KeyboardInterrupt:
                print("\n[STOP] Stopped by user.")
                break
            except FishDailyLimitReached:
                casts = max(0, casts - 1)
                try:
                    server, ws, reader_stop, outfit, current_fish = rebuild_fish_after_daily_limit(
                        realm_type,
                        server,
                        ws,
                        reader_stop,
                        auto_state,
                    )
                    last_post_ts = None
                except KeyboardInterrupt:
                    print("\n[STOP] Stopped by user.")
                    break
                continue
            except Exception:
                errors += 1
                detail = traceback.format_exc()
                write_error("runtime exception", detail)
                print(f"[{short_now()}] Error saved to {ERROR_LOG.name}")

                if is_recoverable_connection_error(detail):
                    print(f"[{short_now()}] RECOVER connection lost. Rebuilding session...")
                    try:
                        server, ws, reader_stop, outfit, current_fish = reconnect_session(
                            realm_type,
                            server,
                            ws,
                            reader_stop,
                        )
                        storage = skip_raw_fish_bank_when_cooking(mode, auto_state, "BANK")
                        if storage is None:
                            storage = safe_deposit_raw_fish_to_bank("BANK")
                            if storage.get("ok"):
                                current_fish = int(storage.get("carry_fish", current_fish) or 0)
                            elif storage.get("error") == "bank_full" and not storage.get("inventory_has_room"):
                                storage = wait_for_storage_space()
                                current_fish = int(storage.get("carry_fish", current_fish) or 0)
                        else:
                            current_fish = int(storage.get("carry_fish", current_fish) or 0)
                        if location_state_is_sea(location_state):
                            prime_current_fish_location(ws, outfit, location_state)
                        elif join_cook_needed(mode, auto_state):
                            prime_join_cook_location(ws, outfit, location_state)
                        run_join_cook_if_needed(mode, auto_state, ws=ws, outfit=outfit, location_state=location_state)
                        try:
                            current_fish = count_raw_fish_from_backpack(get_me().get("backpack") or {})
                        except Exception:
                            pass
                        last_post_ts = time.time()
                        print(f"[{short_now()}] RECOVER done. Continuing from fish={current_fish}.")
                    except KeyboardInterrupt:
                        print("\n[STOP] Stopped by user.")
                        break
                    except Exception:
                        write_error("recovery failed", traceback.format_exc())
                        print(f"[{short_now()}] RECOVER failed. Waiting before retry...")
                        time.sleep(random.uniform(20.0, 40.0))
                    continue

                time.sleep(random.uniform(10.0, 20.0))
                continue

            last_post_ts = result["post_ts"]
            add_location_active_seconds(location_state, result["post_ts"] - cast_started_ts)

            if result["ok"] and result["delta"] > 0:
                caught += result["delta"]
                current_fish = result["after"]
                record_location_catch(location_state, result["delta"])
                if mode in ("farm_cook", "full_auto") and int(auto_state.get("join_cook_done", 0) or 0) < SERVER_JOIN_COOK_COUNT:
                    run_join_cook_if_needed(mode, auto_state, ws=ws, outfit=outfit, location_state=location_state)
                    try:
                        current_fish = count_raw_fish_from_backpack(get_me().get("backpack") or {})
                    except Exception:
                        pass

                # while the cook cycle is active, raw fish in carry is the cook fuel.
                # Do not bank it after every catch; otherwise BANK and COOK_BULK_FISH fight each other
                # and the bot keeps moving the same fish bank<->carry.
                if is_cook_mode(mode) and bool(auto_state.get("cook_active")):
                    current_fish = result["after"]
                    if not auto_state.get("_cook_bank_skip_logged"):
                        print(f"[{short_now()}] BANK raw-fish deposit skipped while cook is active | carry={current_fish}")
                        auto_state["_cook_bank_skip_logged"] = True
                else:
                    storage = safe_deposit_raw_fish_to_bank("BANK")
                    if storage.get("ok"):
                        current_fish = int(storage.get("carry_fish", current_fish) or 0)
                    elif storage.get("error") == "bank_full":
                        current_fish = int(storage.get("carry_fish", current_fish) or 0)
                        if not storage.get("inventory_has_room"):
                            storage = wait_for_storage_space()
                            current_fish = int(storage.get("carry_fish", current_fish) or 0)
                        else:
                            print(f"[{short_now()}] BANK full, but inventory still has room.")
                    else:
                        write_error("bank deposit after catch failed", json.dumps(storage, separators=(",", ":")))
                        print(f"[{short_now()}] BANK deposit failed. Details saved to {ERROR_LOG.name}.")

                if caught % 20 == 0:
                    print(f"[{short_now()}] STATUS caught={caught} casts={casts} errors={errors} carry={current_fish}")

                if target is not None and caught >= target:
                    break

                run_auto_features(auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
                extra_gap = random.uniform(EXTRA_GAP_MIN, EXTRA_GAP_MAX)
                sleep_with_auto(extra_gap, auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
                add_location_active_seconds(location_state, extra_gap)
                continue

            errors += 1
            current_fish = result["after"]
            error = str(result.get("error") or "")

            if error == "fish_action_too_fast":
                print(f"[{short_now()}] Too fast. Backoff {TOO_FAST_BACKOFF:.0f}s, then continue.")
                sleep_with_auto(TOO_FAST_BACKOFF, auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state, allow_cook=False)
                continue
            if is_recoverable_catch_error(error, result.get("status")):
                delay = random.uniform(8.0, 16.0)
                print(f"[{short_now()}] Recoverable catch error: {error or result.get('status')}. Rebuilding session...")
                sleep_with_auto(delay, auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
                try:
                    server, ws, reader_stop, outfit, current_fish = reconnect_session(
                        realm_type,
                        server,
                        ws,
                        reader_stop,
                    )
                    storage = skip_raw_fish_bank_when_cooking(mode, auto_state, "BANK")
                    if storage is None:
                        storage = safe_deposit_raw_fish_to_bank("BANK")
                        if storage.get("ok"):
                            current_fish = int(storage.get("carry_fish", current_fish) or 0)
                        elif storage.get("error") == "bank_full" and not storage.get("inventory_has_room"):
                            storage = wait_for_storage_space()
                            current_fish = int(storage.get("carry_fish", current_fish) or 0)
                    else:
                        current_fish = int(storage.get("carry_fish", current_fish) or 0)
                    if location_state_is_sea(location_state):
                        prime_current_fish_location(ws, outfit, location_state)
                    elif join_cook_needed(mode, auto_state):
                        prime_join_cook_location(ws, outfit, location_state)
                    run_join_cook_if_needed(mode, auto_state, ws=ws, outfit=outfit, location_state=location_state)
                    try:
                        current_fish = count_raw_fish_from_backpack(get_me().get("backpack") or {})
                    except Exception:
                        pass
                    last_post_ts = time.time()
                    print(f"[{short_now()}] RECOVER done. Continuing from fish={current_fish}.")
                except KeyboardInterrupt:
                    print("\n[STOP] Stopped by user.")
                    break
                except Exception:
                    write_error("recoverable catch recovery failed", traceback.format_exc())
                    print(f"[{short_now()}] RECOVER failed. Waiting before retry...")
                    sleep_with_auto(random.uniform(20.0, 40.0), auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
                continue
            if error == "inventory_full":
                skip_storage = skip_raw_fish_bank_when_cooking(mode, auto_state, "BANK")
                if skip_storage is not None:
                    current_fish = int(skip_storage.get("carry_fish", current_fish) or 0)
                    print(f"[{short_now()}] Inventory full while cooking; waiting briefly instead of banking cook fuel...")
                    sleep_with_auto(random.uniform(8.0, 14.0), auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
                    continue
                print(f"[{short_now()}] Inventory full. Emergency raw-fish bank move will run if bank has space...")
                storage = safe_deposit_raw_fish_to_bank("BANK")
                current_fish = int(storage.get("carry_fish", current_fish) or 0)
                if storage.get("ok") and storage.get("inventory_has_room"):
                    print(f"[{short_now()}] Inventory has room again. Continuing.")
                    continue
                wait_result = wait_for_storage_space()
                current_fish = int(wait_result.get("carry_fish", current_fish) or 0)
                continue
            if error in ("unauthorized", "forbidden"):
                print("[STOP] Cookie/login problem. Use option 4 and refresh the cookie.")
                break

            print(f"[{short_now()}] Unhandled catch failure. Waiting, then continuing. Details saved to {ERROR_LOG.name}.")
            sleep_with_auto(random.uniform(30.0, 60.0), auto_state=auto_state, allow_sell=True, ws=ws, outfit=outfit, location_state=location_state)
            continue
    finally:
        fish_daily_pause(auto_state)
        close_presence(ws, reader_stop)

    try:
        end_me = get_me()
        end_backpack = end_me.get("backpack") or {}
        end_fish = count_raw_fish_from_backpack(end_backpack)
        end_bank_fish = count_bank_fish(end_backpack)
    except Exception:
        end_fish = current_fish
        end_bank_fish = 0

    print("\n=========== Finished ===========")
    print(f"Caught this run: {caught}")
    print(f"Casts: {casts}")
    print(f"Errors: {errors}")
    print(f"Start total fish: {start_total_fish}")
    print(f"End carry fish: {end_fish}")
    print(f"End bank fish: {end_bank_fish}")
    print(f"End total fish: {end_fish + end_bank_fish}")
    print(f"Real increase: {(end_fish + end_bank_fish) - start_total_fish}")
    print(f"Final location: {current_location_label(location_state)}")
    print(f"Fish since last hook switch: {int(location_state.get('fish_since_hook_switch', 0) or 0)}")
    if is_cook_mode(auto_state.get("mode")):
        print(f"Cooked this run: {int(auto_state.get('cook_done', 0) or 0)}")
    if is_sell_mode(auto_state.get("mode")):
        print(f"Market listings this run: {int(auto_state.get('sell_done', 0) or 0)}")
    print("================================")
    pause()


def connection_mode_label():
    return "Direct / no proxy"


def choose_connection_mode():
    global CONNECTION_MODE
    CONNECTION_MODE = "direct"
    clear_screen()
    print("=========== Connection Mode ===========")
    print("Proxy is disabled in this build.")
    print("Current: Direct / no proxy")
    print("=======================================")
    pause()



# ==================== Anonymous Ember Spectator ====================
# This monitor follows the same official /ws/spectate pattern used by the
# Boss watcher.  The spectator WebSockets are intentionally anonymous and
# therefore do not create a visible player/character in The Emberstone.
EMBER_SPECTATOR_REGION = "ember"
EMBER_SPECTATOR_REGISTER_EVERY_SECONDS = 2.0
EMBER_SPECTATOR_STALE_AFTER_SECONDS = 7.0
EMBER_SPECTATOR_REFRESH_SECONDS = 1.0


def ember_server_number(server):
    match = re.fullmatch(r"Server\s+(\d+)", str((server or {}).get("name") or ""))
    return int(match.group(1)) if match else -1


def ember_get_numbered_servers():
    """Read every currently advertised numbered server.

    The HTTP server-list request uses the configured account cookie, but the
    spectator WebSockets opened later never receive that cookie.
    """
    status, payload, raw = http("GET", "/api/servers", timeout=20)
    if status != 200 or not isinstance(payload, dict) or payload.get("ok") is False:
        error = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(
            f"Ember server list failed status={status} error={error} raw={str(raw)[:250]}"
        )

    rows = []
    for server in payload.get("servers") or []:
        if not isinstance(server, dict):
            continue
        if ember_server_number(server) < 1:
            continue
        rows.append(dict(server))
    rows.sort(key=ember_server_number)
    return rows


def ember_spectate_url(server):
    shard = server_route_shard_id(server)
    if shard <= 0:
        raise RuntimeError("Invalid spectator shard")
    return ws_url(
        f"/ws/spectate/s{shard}",
        str((server or {}).get("wsBaseUrl") or ""),
    )


def ember_decode_spectator_payload(raw):
    """Decode normal JSON and Kintara binary+gzip spectator frames."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if data and data[0] == 1:
                data = gzip.decompress(data[1:])
            text_value = data.decode("utf-8", errors="replace")
        else:
            text_value = str(raw)
        payload = json.loads(text_value)
    except Exception:
        return []

    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def ember_is_human_player(player):
    """Count account-shaped human records only; ignore NPCs/mobs/pets."""
    if not isinstance(player, dict):
        return False
    try:
        if int(float(player.get("id"))) <= 0:
            return False
    except Exception:
        return False

    if any(
        bool(player.get(key))
        for key in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")
    ):
        return False

    marker = " ".join(
        str(player.get(key) or "").strip().lower()
        for key in (
            "type",
            "kind",
            "entityType",
            "entity_type",
            "npcType",
            "mobType",
            "species",
        )
    )
    nonhuman_words = (
        "npc",
        "mob",
        "boss",
        "enemy",
        "monster",
        "creature",
        "spider",
        "pet",
        "companion",
        "minion",
        "summon",
        "animal",
    )
    return not any(word in marker for word in nonhuman_words)


class EmberSpectatorWatcher:
    """One anonymous Ember watcher for one advertised server."""

    def __init__(self, server):
        self.server = dict(server or {})
        self.name = str(self.server.get("name") or "?")
        self.number = ember_server_number(self.server)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.connected = False
        self.player_count = 0
        self.snapshots = 0
        self.last_snapshot_at = 0.0
        self.error = ""
        self.ws = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    def state(self):
        with self.lock:
            age = (
                None
                if self.last_snapshot_at <= 0
                else time.time() - self.last_snapshot_at
            )
            return {
                "server": self.name,
                "number": self.number,
                "display_id": server_global_display_id(self.server),
                "route_shard": server_route_shard_id(self.server),
                "zone": server_connection_zone(self.server),
                "membership": bool(self.server.get("requiresMembership")),
                "full": bool(self.server.get("full")),
                "connected": bool(self.connected),
                "live": bool(
                    age is not None
                    and age <= EMBER_SPECTATOR_STALE_AFTER_SECONDS
                ),
                "count": int(self.player_count),
                "snapshots": int(self.snapshots),
                "age": age,
                "error": str(self.error or ""),
            }

    def _connect_anonymous(self):
        # Deliberately no cookie and no connect-token: this is the official
        # invisible spectator channel, not an authenticated Presence channel.
        return websocket.create_connection(
            ember_spectate_url(self.server),
            timeout=12,
            origin=BASE,
            enable_multithread=True,
            header=[
                f"User-Agent: {UA}",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ],
            http_no_proxy=["*"],
        )

    def _run(self):
        retry_delay = 1.0
        while not self.stop_event.is_set():
            try:
                self.ws = self._connect_anonymous()
                self.ws.settimeout(0.5)
                with self.lock:
                    self.connected = True
                    self.error = ""
                retry_delay = 1.0
                last_register_at = 0.0

                while not self.stop_event.is_set():
                    now_ts = time.time()
                    if (
                        now_ts - last_register_at
                        >= EMBER_SPECTATOR_REGISTER_EVERY_SECONDS
                    ):
                        # The only WebSocket message sent by this monitor.
                        self.ws.send(
                            json.dumps(
                                {
                                    "t": "spec_reg",
                                    "region": EMBER_SPECTATOR_REGION,
                                },
                                separators=(",", ":"),
                            )
                        )
                        last_register_at = now_ts

                    try:
                        raw = self.ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue

                    if raw in (None, ""):
                        raise RuntimeError("spectator socket closed")

                    for message in ember_decode_spectator_payload(raw):
                        if str(message.get("t") or "") != "snap":
                            continue
                        if (
                            str(message.get("region") or "").strip().lower()
                            != EMBER_SPECTATOR_REGION
                        ):
                            continue

                        humans = [
                            player
                            for player in (message.get("players") or [])
                            if ember_is_human_player(player)
                        ]
                        with self.lock:
                            self.player_count = len(humans)
                            self.snapshots += 1
                            self.last_snapshot_at = time.time()
                            self.error = ""

            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.error = str(exc)[:180]
            finally:
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.ws = None
                with self.lock:
                    self.connected = False

            if not self.stop_event.is_set():
                self.stop_event.wait(
                    retry_delay + random.uniform(0.0, 0.7)
                )
                retry_delay = min(20.0, retry_delay * 1.7)


def ember_spectator_save_latest(output_file, states):
    live = [state for state in states if state.get("live")]
    leaders = sorted(
        [state for state in live if int(state.get("count") or 0) > 0],
        key=lambda state: (
            -int(state.get("count") or 0),
            int(state.get("number") or 999999),
        ),
    )[:3]
    payload = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "region": EMBER_SPECTATOR_REGION,
        "monitored": len(states),
        "live": len(live),
        "total_players": sum(int(state.get("count") or 0) for state in live),
        "top3": leaders,
        "servers": states,
    }
    temp_file = output_file.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_file.replace(output_file)


def ember_spectator_display(output_dir, states):
    live = [state for state in states if state.get("live")]
    leaders = sorted(
        [state for state in live if int(state.get("count") or 0) > 0],
        key=lambda state: (
            -int(state.get("count") or 0),
            int(state.get("number") or 999999),
        ),
    )[:3]

    clear_screen()
    print("=" * 92)
    print("KINTARA EMBER LIVE MONITOR | ALL NUMBERED SERVERS")
    print("Anonymous /ws/spectate | no character presence")
    print("=" * 92)
    print(
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"monitored={len(states)} | live={len(live)} | "
        f"total Ember players={sum(int(row.get('count') or 0) for row in live)}"
    )
    print(f"Output: {output_dir}")

    print("\nTOP EMBER SERVERS")
    print("-" * 92)
    if not leaders:
        print("No human player is currently detected in The Emberstone.")
    else:
        for rank, state in enumerate(leaders, start=1):
            print(
                f"{rank}) {state['server']}: "
                f"{state['count']} player(s)"
            )

    print("\nALL SERVERS")
    print("-" * 92)
    print(
        f"{'SERVER':<12} {'COUNT':>5} {'STATUS':<10} "
        f"{'ZONE':<8} {'FLAGS':<22} ERROR"
    )
    for state in states:
        if state.get("live"):
            status = "LIVE"
            count_text = str(state.get("count", 0))
        elif state.get("connected"):
            status = "WAIT"
            count_text = "?"
        elif int(state.get("snapshots") or 0) > 0:
            status = "STALE"
            count_text = "?"
        else:
            status = "RECONNECT"
            count_text = "?"

        flags = []
        if state.get("membership"):
            flags.append("membership")
        if state.get("full"):
            flags.append("full")

        print(
            f"{state.get('server', '?'):<12} "
            f"{count_text:>5} "
            f"{status:<10} "
            f"{(state.get('zone') or '-'):<8} "
            f"{(','.join(flags) or '-'):<22} "
            f"{str(state.get('error') or '')[:42]}"
        )

    print("\nOnly spec_reg(region=ember) is sent on anonymous spectator sockets.")
    print("No pos, movement, fishing, mining, attack, inventory action or character join.")
    print("Press Ctrl+C to stop the monitor and return to the main menu.")


def run_ember_spectator_all_servers():
    ensure_dependency()
    get_cookie(required=True)

    servers = ember_get_numbered_servers()
    if not servers:
        raise RuntimeError("No numbered servers were returned for Ember monitoring.")

    output_dir = Path(__file__).resolve().with_name(
        f"EMBER_SPECTATOR_ALL_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_json = output_dir / "latest.json"

    watchers = [EmberSpectatorWatcher(server).start() for server in servers]
    for _watcher in watchers:
        time.sleep(0.04)

    try:
        while True:
            states = [watcher.state() for watcher in watchers]
            states.sort(key=lambda state: int(state.get("number") or 999999))
            ember_spectator_save_latest(latest_json, states)
            ember_spectator_display(output_dir, states)
            time.sleep(EMBER_SPECTATOR_REFRESH_SECONDS)
    finally:
        for watcher in watchers:
            watcher.stop()
        for watcher in watchers:
            try:
                watcher.thread.join(timeout=1.5)
            except Exception:
                pass


def main_menu(realm_type):
    saved_settings = _read_location_settings()
    saved_fish_key = str(saved_settings.get("fish_location_key") or "")
    saved_fish_location = next(
        (location for location in FISH_LOCATIONS if str(location.get("key") or "") == saved_fish_key),
        FISH_LOCATIONS[0],
    )
    try:
        saved_switch_every = max(1, int(saved_settings.get("fish_switch_every", FISH_HOOK_SWITCH_EVERY)))
    except Exception:
        saved_switch_every = FISH_HOOK_SWITCH_EVERY
    location_state = build_location_state(
        "manual",
        [saved_fish_location],
        switch_every=saved_switch_every,
    )

    while True:
        clear_screen()
        print("=========== Farm Mahi ===========")
        print(f"Server type: {'Club' if realm_type == 'club' else 'Normal / Free'}")
        print(f"Fish location: {current_location_label(location_state)}")
        print(f"Hook switch: every {int(location_state.get('switch_every', FISH_HOOK_SWITCH_EVERY) or FISH_HOOK_SWITCH_EVERY)} fish")
        print(f"Connection: {connection_mode_label()}")
        print("1) Farm + cook")
        print("2) Live Ember player monitor | all servers")
        print("3) Market / Manual Sell")
        print("4) Create/update .env cookie")
        print("5) Change server type")
        print("6) Change fish location")
        print("8) Change connection mode")
        print("9) Start farming")
        print("0) Exit")
        print("=================================")
        choice = input("Choose: ").strip()

        if choice == "1":
            try:
                farm_loop(realm_type, location_state, forced_mode="farm_cook")
            except Exception as exc:
                write_error("quick farm cook error", traceback.format_exc())
                print(f"[ERR] {exc}")
                print(f"Details were saved to {ERROR_LOG.name}.")
                pause()
        elif choice == "2":
            try:
                run_ember_spectator_all_servers()
            except KeyboardInterrupt:
                print("\n[STOP] Ember monitor stopped. Returning to menu...")
                time.sleep(0.8)
            except Exception as exc:
                write_error("ember spectator monitor error", traceback.format_exc())
                print(f"[ERR] Ember monitor failed: {exc}")
                print(f"Details were saved to {ERROR_LOG.name}.")
                pause()
        elif choice == "3":
            try:
                from kintara_trade_root import run_trade_menu

                run_trade_menu(
                    cookie=get_cookie(),
                    base_url=BASE,
                    user_agent=UA,
                    env_file=ENV_FILE,
                )
            except KeyboardInterrupt:
                print("\n[STOP] Market stopped by user.")
                pause()
            except Exception as exc:
                write_error("market option error", traceback.format_exc())
                print(f"[ERR] {exc}")
                pause()
        elif choice == "4":
            setup_env_menu()
        elif choice == "5":
            realm_type = choose_realm_type()
        elif choice == "6":
            location_state = choose_location_state()
            pause()
        elif choice == "8":
            choose_connection_mode()
            pause()
        elif choice == "9":
            try:
                farm_loop(realm_type, location_state)
            except Exception as exc:
                write_error("main farm error", traceback.format_exc())
                print(f"[ERR] {exc}")
                print(f"Details were saved to {ERROR_LOG.name}.")
                pause()
        elif choice == "0":
            return
        else:
            print("Invalid option.")
            time.sleep(1.0)



def main():
    try:
        get_cookie(required=False)
        realm_type = choose_realm_type()
        main_menu(realm_type)
    except KeyboardInterrupt:
        print("\nExit.")
    except Exception:
        write_error("fatal error", traceback.format_exc())
        print(f"[ERR] Fatal error saved to {ERROR_LOG.name}.")
        pause()


if __name__ == "__main__":
    main()
