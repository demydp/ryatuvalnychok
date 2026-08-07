"""
Глобальні (per-user) налаштування — тонкий фасад зі СТАРИМИ сигнатурами (load_config(),
save_config(updates), mask_secret()) над app/db_store.py (Этап 1 веб-версії: джерело істини
тепер БД — Postgres/Railway або SQLite локально, див. app/db.py, — а не config.json).

Раніше config.json жив один на весь (однокористувацький desktop) застосунок; тепер БД одна
на всіх юзерів, тому кожен виклик неявно прив'язаний до flask_login.current_user — саме тому
десятки існуючих викликів (routes/settings.py, onboarding.py, project_store.py тощо) можуть
й далі викликати load_config()/save_config() БЕЗ user_id: раніше "юзер" був один на весь
застосунок, тепер ним неявно стає той, хто зараз залогінений у поточному HTTP-запиті.

Ці функції МАЮТЬ сенс лише всередині активного HTTP-запиту залогіненого юзера (усі існуючі
виклики саме такі). Фоновим job'ам (app/scheduler.py) без сесії — див. app/db_store.py напряму
з явним user_id, а не ці фасади.
"""
from flask_login import current_user

from app import db_store


def load_config() -> dict:
    return db_store.load_user_config(current_user.id)


def save_config(updates: dict) -> dict:
    return db_store.save_user_config(current_user.id, updates)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
