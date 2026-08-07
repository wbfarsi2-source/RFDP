from __future__ import annotations
from core.locale_text import localized_literal
from datetime import datetime
from typing import Any
SUPPORTED_LANGUAGES = {'fa', 'en'}

def normalize_language(value: str | None) -> str:
    return 'en' if str(value or '').lower().startswith('en') else 'fa'
_TEXTS: dict[str, dict[str, str]] = {'language_prompt': {'fa': localized_literal('core.i18n.0373243398f6'), 'en': localized_literal('core.i18n.aced002252a3')}, 'welcome': {'fa': localized_literal('core.i18n.47b487c7d93f'), 'en': '<b>GameBot Platform</b>\n\nManage game accounts, subscriptions, and automated services from one bot.'}, 'choose_game': {'fa': localized_literal('core.i18n.d45a10bf32a1'), 'en': 'Choose a game:'}, 'no_accounts': {'fa': localized_literal('core.i18n.9831b3167e40'), 'en': 'You have not added a game account yet.'}, 'start_first': {'fa': localized_literal('core.i18n.3588b8b0ea9c'), 'en': 'Send /start first.'}, 'invalid_access': {'fa': localized_literal('core.i18n.4a3e74bfeb30'), 'en': 'Invalid access'}, 'back': {'fa': localized_literal('core.i18n.296f695762f7'), 'en': '⬅️ Back'}, 'main_menu': {'fa': localized_literal('core.i18n.34648a0c3918'), 'en': '🏠 Main Menu'}, 'settings_saved': {'fa': localized_literal('core.i18n.ee4ced86e451'), 'en': '✅ Settings saved.'}}

def tr(key: str, lang: str='fa', **values: Any) -> str:
    language = normalize_language(lang)
    value = _TEXTS.get(key, {}).get(language) or _TEXTS.get(key, {}).get('fa') or key
    return value.format(**values)

def format_datetime(value: datetime | None, lang: str='fa') -> str:
    if value is None:
        return '-'
    local = value.astimezone()
    if normalize_language(lang) == 'en':
        return local.strftime('%Y-%m-%d %H:%M')
    return local.strftime('%Y/%m/%d - %H:%M')
