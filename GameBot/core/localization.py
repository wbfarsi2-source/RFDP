from __future__ import annotations

from typing import Any

from core.locale_text import localized_literal


def tr(lang: str, key: str, english: str, **values: Any) -> str:
    template = english if lang == "en" else localized_literal(key)
    try:
        return template.format(**values)
    except Exception:
        return template
