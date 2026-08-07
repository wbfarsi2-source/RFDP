#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import datetime as dt
import json
import py_compile
import shutil
from pathlib import Path

MARKER_BEGIN = "# BEGIN KINTARA EMBER MANUAL PATCH V1"
MARKER_END = "# END KINTARA EMBER MANUAL PATCH V1"


def locate_paths() -> tuple[Path, Path]:
    patch_dir = Path(__file__).resolve().parent
    candidates = [patch_dir, patch_dir.parent]
    for root in candidates:
        if (root / "app.py").exists() and (root / "games" / "kintara" / "telegram" / "router.py").exists():
            return root, patch_dir
    raise SystemExit("[ERROR] Extract this patch folder inside Start, then run the BAT file again.")


def router_assignment(source: str) -> tuple[str, int]:
    tree = ast.parse(source)
    for node in tree.body:
        target_name = ""
        value = None
        if isinstance(node, ast.Assign):
            value = node.value
            if node.targets and isinstance(node.targets[0], ast.Name):
                target_name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            if isinstance(node.target, ast.Name):
                target_name = node.target.id
        if not target_name or not isinstance(value, ast.Call):
            continue
        func = value.func
        func_name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if func_name == "Router":
            return target_name, int(getattr(node, "end_lineno", node.lineno))
    raise RuntimeError("Could not find Router(...) assignment in Kintara router.")


def backup(project: Path, backup_dir: Path, path: Path, created: list[str]) -> None:
    rel = path.relative_to(project).as_posix()
    if not path.exists():
        created.append(rel)
        return
    target = backup_dir / "files" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def patch_router(project: Path, backup_dir: Path, created: list[str]) -> Path:
    path = project / "games" / "kintara" / "telegram" / "router.py"
    source = path.read_text(encoding="utf-8-sig", errors="strict")
    if MARKER_BEGIN in source:
        print("[OK] Router hook already exists.")
        return path
    router_name, end_line = router_assignment(source)
    injection = "\n".join([
        "",
        MARKER_BEGIN,
        "from aiogram.filters import Command as _EmberManualCommand",
        "from games.kintara.telegram.ember_manual_patch import (",
        "    ember_manual_callback_filter as _ember_manual_callback_filter,",
        "    handle_ember_manual_callback as _handle_ember_manual_callback,",
        "    handle_ember_manual_command as _handle_ember_manual_command,",
        ")",
        "",
        f"@{router_name}.callback_query(_ember_manual_callback_filter)",
        "async def _kintara_ember_manual_update_handler(callback):",
        "    await _handle_ember_manual_callback(callback)",
        "",
        f"@{router_name}.message(_EmberManualCommand(\"emberscan\"))",
        "async def _kintara_ember_manual_command_handler(message):",
        "    await _handle_ember_manual_command(message)",
        MARKER_END,
        "",
        "",
    ])
    backup(project, backup_dir, path, created)
    lines = source.splitlines(keepends=True)
    lines.insert(end_line, injection)
    path.write_text("".join(lines), encoding="utf-8")
    print(f"[OK] Patched {path.relative_to(project)}")
    return path


def write_restore_tools(project: Path) -> None:
    restore_py = project / "RESTORE_EMBER_MANUAL_PATCH.py"
    restore_py.write_text('''from __future__ import annotations
import json
import shutil
from pathlib import Path
root = Path.cwd().resolve()
base = root / "data" / "ember_manual_patch_backup"
backups = sorted((p for p in base.glob("*") if p.is_dir()), reverse=True)
if not backups:
    raise SystemExit("No Ember patch backup was found.")
backup = backups[0]
manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
for source in (backup / "files").rglob("*"):
    if source.is_file():
        relative = source.relative_to(backup / "files")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
for relative in manifest.get("created_files", []):
    target = root / relative
    if target.exists() and target.is_file():
        target.unlink()
print(f"Restored backup: {backup}")
print("Restart START_GAMEBOT.bat.")
''', encoding="utf-8")
    restore_bat = project / "RESTORE_EMBER_MANUAL_PATCH.bat"
    restore_bat.write_text('''@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PY=.venv\\Scripts\\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "RESTORE_EMBER_MANUAL_PATCH.py"
pause
''', encoding="utf-8")


def main() -> int:
    project, patch_dir = locate_paths()
    replacement = patch_dir / "replacement_files"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = project / "data" / "ember_manual_patch_backup" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    mapping = [
        (replacement / "games/kintara/services/ember/manual_scanner.py", project / "games/kintara/services/ember/manual_scanner.py"),
        (replacement / "games/kintara/services/ember/runner.py", project / "games/kintara/services/ember/runner.py"),
        (replacement / "games/kintara/telegram/ember_manual_patch.py", project / "games/kintara/telegram/ember_manual_patch.py"),
    ]
    for source, target in mapping:
        if not source.exists():
            raise RuntimeError(f"Missing replacement file: {source}")
        backup(project, backup_dir, target, created)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"[OK] Replaced {target.relative_to(project)}")

    router = patch_router(project, backup_dir, created)

    jobs = project / "data" / "ember_manual_jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.request.json", "*.running.json", "*.result.json", "*.tmp"):
        for path in jobs.glob(pattern):
            try:
                path.unlink()
            except Exception:
                pass

    (backup_dir / "manifest.json").write_text(
        json.dumps({"created_files": created}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_restore_tools(project)

    for _, target in mapping:
        py_compile.compile(str(target), doraise=True)
    py_compile.compile(str(router), doraise=True)

    print("\n============================================================")
    print("Kintara Ember manual patch V3 installed successfully.")
    print("- Telegram shows one short waiting message only")
    print("- Ember scan runs in its dedicated visible CMD runner")
    print("- The CMD shows all 25 server checks and TOP 3")
    print("- Server starts are spread between 6 and 8 seconds")
    print("- Failed servers receive one normal retry, then show as not detected")
    print("- Global cooldown after completion: 6 minutes")
    print("- Exact F12 Ember position is unchanged")
    print("- .env was not modified")
    print(f"- Backup: {backup_dir}")
    print("============================================================")
    print("Close all current bot CMD windows, then run START_GAMEBOT.bat again.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        raise
