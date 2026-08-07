"""
Історія чату "Напарника" (Фаза 2, доробка). Раніше історія жила ЛИШЕ в пам'яті браузера
(JS-масив у app/static/js/companion.js) — перезавантаження сторінки миттєво губило весь діалог,
бо ніде вона не зберігалась. Тепер пишеться в БД (ProjectData, ключ "companion_history.json")
одним зростаючим списком повідомлень {role, content, ts}, той самий патерн запису "все й одразу",
що app/ideas_bank.py/app/saved_scripts.py.

get_json()/set_json() без явного project_id (див. app/project_data_store.py) самі резолвляться
в АКТИВНИЙ проєкт поточної сесії — тому історія автоматично прив'язана до проєкту без додаткової
логіки тут: перемкнув проєкт — і /api/companion/history вже дивиться на інший рядок.
"""
from datetime import datetime, timezone

from app.project_data_store import get_json, set_json

_KEY = "companion_history.json"

# Скільки повідомлень тримати — не безмежно, щоб рядок не розростався роками щоденного
# спілкування. Для контексту, який реально йде в Opus, і так береться значно менший хвіст
# (MAX_HISTORY_MESSAGES в app/routes/companion.py) — це ліміт лише проти розбухання, а не
# проти вартості виклику.
MAX_STORED_MESSAGES = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_companion_history() -> list:
    data = get_json(_KEY, default={})
    return data.get("messages", [])


def _save(messages: list):
    set_json(_KEY, {"messages": messages})


def append_exchange(user_message: str, assistant_reply: str) -> list:
    """Дописує пару питання+відповідь одразу після успішного виклику Opus (app/routes/companion.py)
    — джерело правди для діалогу лежить на диску, а не в браузері, тому кілька вкладок/пристроїв
    і перезавантаження сторінки бачать один і той самий чат."""
    messages = load_companion_history()
    messages.append({"role": "user", "content": user_message, "ts": _now_iso()})
    messages.append({"role": "assistant", "content": assistant_reply, "ts": _now_iso()})
    messages = messages[-MAX_STORED_MESSAGES:]
    _save(messages)
    return messages


def clear_companion_history():
    _save([])
