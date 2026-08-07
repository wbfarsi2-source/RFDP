from __future__ import annotations
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
