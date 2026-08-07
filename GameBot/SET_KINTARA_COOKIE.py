#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import getpass
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "https://kintara.gg"

# همیشه پوشه‌ای که خود این فایل داخل آن قرار دارد
WORK_DIR = Path(__file__).resolve().parent
ENV_FILE = WORK_DIR / ".env"

COOKIE_NAME = "__Host-kintara_session"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def validate_cookie_value(value: str) -> str:
    value = str(value or "").strip()

    if not value:
        raise ValueError("Cookie value is empty.")

    invalid_prefixes = (
        "KINTARA_COOKIE=",
        "__Host-kintara_session=",
        "FISH_DAILY_",
    )

    if value.startswith(invalid_prefixes):
        raise ValueError(
            "فقط مقدار ستون Value را وارد کن؛ "
            "نام کوکی یا KINTARA_COOKIE= را وارد نکن."
        )

    if any(character in value for character in ("\r", "\n", "\t", " ")):
        raise ValueError("Cookie value contains whitespace or multiple lines.")

    if len(value) < 20:
        raise ValueError("Cookie value is too short.")

    return value


def backup_env() -> Path | None:
    if not ENV_FILE.exists():
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_file = WORK_DIR / f".env.backup_{timestamp}"

    shutil.copy2(ENV_FILE, backup_file)

    return backup_file


def save_cookie(cookie_value: str) -> None:
    full_cookie = f"{COOKIE_NAME}={cookie_value}"

    existing_lines = []

    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines()

    updated_lines = []
    cookie_added = False

    for raw_line in existing_lines:
        line = raw_line.strip()

        # تمام KINTARA_COOKIEهای قبلی یا خراب حذف می‌شوند
        if line.startswith("KINTARA_COOKIE="):
            if not cookie_added:
                updated_lines.append(f"KINTARA_COOKIE={full_cookie}")
                cookie_added = True

            continue

        updated_lines.append(raw_line)

    if not cookie_added:
        updated_lines.insert(0, f"KINTARA_COOKIE={full_cookie}")

    ENV_FILE.write_text(
        "\n".join(updated_lines).rstrip() + "\n",
        encoding="utf-8",
    )


def test_cookie(cookie_value: str) -> tuple[int, dict, str]:
    full_cookie = f"{COOKIE_NAME}={cookie_value}"

    request = urllib.request.Request(
        BASE + "/api/auth/me",
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Origin": BASE,
            "Referer": BASE + "/play",
            "Cookie": full_cookie,
            "Cache-Control": "no-cache",
        },
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read().decode(
                "utf-8",
                errors="replace",
            )

            try:
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {}

            return int(response.status), payload, raw

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {}

        return int(exc.code), payload, raw

    except Exception as exc:
        return 0, {}, str(exc)


def main() -> None:
    print("=" * 64)
    print("KINTARA COOKIE SETUP")
    print("=" * 64)
    print("Directory:", WORK_DIR)
    print("ENV file :", ENV_FILE)
    print()
    print("Chrome:")
    print("F12 > Application > Cookies > https://kintara.gg")
    print()
    print("Cookie name:")
    print(COOKIE_NAME)
    print()
    print("فقط مقدار ستون Value را وارد کن.")
    print("هنگام Paste چیزی نمایش داده نمی‌شود؛ طبیعی است.")
    print()

    try:
        cookie_value = getpass.getpass(
            "Paste cookie VALUE only: "
        )

        cookie_value = validate_cookie_value(cookie_value)

    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    except ValueError as exc:
        print()
        print("ERROR:", exc)
        return

    print()
    print("Testing cookie before saving...")

    status, payload, raw = test_cookie(cookie_value)

    if status != 200:
        error = (
            payload.get("error")
            if isinstance(payload, dict)
            else None
        )

        print()
        print("=" * 64)
        print("COOKIE FAILED")
        print("HTTP :", status)
        print("Error:", error or raw[:300])
        print()
        print("Nothing was saved.")
        print("=" * 64)
        return

    if not isinstance(payload, dict) or not payload.get("player"):
        print()
        print("COOKIE FAILED")
        print("Server returned HTTP 200 but player data was missing.")
        print("Nothing was saved.")
        return

    backup_file = backup_env()
    save_cookie(cookie_value)

    player = payload.get("player") or {}

    player_name = (
        player.get("username")
        or player.get("name")
        or player.get("displayName")
        or player.get("id")
        or "detected"
    )

    print()
    print("=" * 64)
    print("COOKIE OK")
    print("HTTP  : 200")
    print("Player:", player_name)
    print("Saved :", ENV_FILE)

    if backup_file:
        print("Backup:", backup_file)

    print("=" * 64)


if __name__ == "__main__":
    main()
