from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _catalog() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "locales" / "fa_literals.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def localized_literal(key: str) -> str:
    return str(_catalog().get(str(key), key))
