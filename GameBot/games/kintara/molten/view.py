from __future__ import annotations

from typing import Any

from core.locale_text import localized_literal


def format_snapshot(snapshot: dict[str, Any], lang: str = "fa", *, channel: bool = False) -> str:
    top = snapshot.get("top3") if isinstance(snapshot.get("top3"), list) else []
    is_accurate = bool(snapshot.get("accurate"))

    if lang == "en" or channel:
        title = "<b>Come To Molten</b>"
        if not is_accurate:
            return title + "\n\nLive data is temporarily unavailable."
        lines = [title, ""]
        if not top:
            lines.append("No human player is currently detected in The Emberstone.")
            return "\n".join(lines)
        for index, row in enumerate(top[:3], start=1):
            count = int(row.get("count") or 0)
            label = "player" if count == 1 else "players"
            lines.append(f"{index}. <b>{row.get('server') or '?'}</b> — {count} {label}")
        return "\n".join(lines)

    if not is_accurate:
        return localized_literal("kintara.molten.not_ready")

    lines = [localized_literal("kintara.molten.title"), ""]
    if not top:
        lines.append(localized_literal("kintara.molten.no_players"))
        return "\n".join(lines)

    for index, row in enumerate(top[:3], start=1):
        lines.append(
            f"{index}. <b>{row.get('server') or '?'}</b> — "
            f"{int(row.get('count') or 0)} {localized_literal('kintara.molten.player')}"
        )
    return "\n".join(lines)
