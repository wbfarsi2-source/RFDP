from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = ROOT / ".venv" / ".gamebot_requirements.sha256"

REQUIRED_IMPORTS = (
    "aiogram",
    "sqlalchemy",
    "aiosqlite",
    "cryptography",
    "pydantic",
    "pydantic_settings",
    "psutil",
    "httpx",
    "tzdata",
    "websocket",
    "filelock",
    "aiohttp_socks",
    "socksio",
)


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def imports_available() -> bool:
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception:
            return False
    return True


def versions_satisfy_requirements() -> bool:
    try:
        from packaging.requirements import Requirement
    except Exception:
        return imports_available()

    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
            installed = importlib.metadata.version(requirement.name)
        except Exception:
            return False
        if requirement.specifier and installed not in requirement.specifier:
            return False
    return imports_available()


def write_marker(value: str) -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(value + "\n", encoding="ascii")


def main() -> int:
    if not REQUIREMENTS.exists():
        print("[ERROR] requirements.txt was not found.")
        return 2

    current_hash = requirements_hash()
    stored_hash = ""
    try:
        stored_hash = MARKER.read_text(encoding="ascii").strip()
    except OSError:
        pass

    if stored_hash == current_hash and imports_available():
        print("[DEPS] Dependencies are already ready. Skipping pip.")
        return 0

    # This also makes an upgraded launcher fast on an existing healthy venv.
    if versions_satisfy_requirements():
        write_marker(current_hash)
        print("[DEPS] Installed packages satisfy requirements. Cache created; pip skipped.")
        return 0

    print("[DEPS] Missing or changed packages detected. Installing once...")
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "-r",
        str(REQUIREMENTS),
    ]
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("[ERROR] Dependency installation failed.")
        return result.returncode or 1

    if not versions_satisfy_requirements():
        print("[ERROR] Dependencies were installed but the verification still failed.")
        return 3

    write_marker(current_hash)
    print("[DEPS] Installation completed and cached for future launches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
