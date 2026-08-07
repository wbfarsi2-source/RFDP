import ast
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERSIAN_PATTERN = re.compile(r"[\u0600-\u06ff]")


def test_python_source_is_english_only() -> None:
    offending: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        if PERSIAN_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
            offending.append(str(path.relative_to(PROJECT_ROOT)))
    assert offending == []


def test_all_localized_literals_exist() -> None:
    catalog = json.loads((PROJECT_ROOT / "locales" / "fa_literals.json").read_text(encoding="utf-8"))
    missing: set[str] = set()
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id not in {"localized_literal", "tr"}:
                continue
            if node.func.id == "tr" and len(node.args) < 3:
                continue
            key_index = 0 if node.func.id == "localized_literal" else 1
            if len(node.args) <= key_index or not isinstance(node.args[key_index], ast.Constant):
                continue
            key = node.args[key_index].value
            if isinstance(key, str) and key not in catalog:
                missing.add(key)
    assert missing == set()
