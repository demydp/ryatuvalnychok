"""
Переводы интерфейса (ru/uk) — единый источник: app/static/lang/{ru,uk}.json.
Одни и те же ключи используются и на фронтенде (через data-i18n / window.I18N.t()),
и на бэкенде — для текстов, которые формирует сервер (сообщения статусов/ошибок).
Бэкенд определяет язык по заголовку X-Lang, который i18n.js прозрачно
проставляет на каждый fetch() (см. app/static/js/i18n.js).
"""
import json
import os

from flask import request

LANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "lang")
DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "uk")

_cache = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        path = os.path.join(LANG_DIR, f"{lang}.json")
        with open(path, "r", encoding="utf-8") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def load_translations() -> dict:
    """Оба словаря целиком — встраиваются в index.html при рендере (см. app/__init__.py)."""
    return {lang: _load(lang) for lang in SUPPORTED_LANGS}


def current_lang() -> str:
    lang = (request.headers.get("X-Lang") or "").strip()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def t(key: str, **template_vars) -> str:
    lang = current_lang()
    text = _load(lang).get(key) or _load(DEFAULT_LANG).get(key) or key
    for k, v in template_vars.items():
        text = text.replace(f"{{{k}}}", str(v))
    return text
