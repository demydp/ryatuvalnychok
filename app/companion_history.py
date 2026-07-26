"""
Історія чату "Напарника" (Фаза 2, доробка). Раніше історія жила ЛИШЕ в пам'яті браузера
(JS-масив у app/static/js/companion.js) — перезавантаження сторінки миттєво губило весь діалог,
бо ніде на диску вона не зберігалась. Тепер пишеться по одному файлу на проєкт
(data/projects/<id>/companion_history.json) — той самий патерн запису "все й одразу", що
app/ideas_bank.py/app/saved_scripts.py, але тут не список карток, а один зростаючий список
повідомлень {role, content, ts}.

project_data_dir() без явного project_id (див. app/project_store.py) сама резолвиться в
АКТИВНИЙ проєкт — тому історія автоматично прив'язана до проєкту без додаткової логіки тут:
перемкнув проєкт — і /api/companion/history вже дивиться у інший файл.
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from app.project_store import project_data_dir

_lock = threading.Lock()

# Скільки повідомлень тримати на диску — не безмежно, щоб файл не розростався роками
# щоденного спілкування. Для контексту, який реально йде в Opus, і так береться значно
# менший хвіст (MAX_HISTORY_MESSAGES в app/routes/companion.py) — це ліміт лише проти
# розбухання файлу, а не проти вартості виклику.
MAX_STORED_MESSAGES = 200


def _history_path() -> str:
    return os.path.join(project_data_dir(), "companion_history.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_companion_history() -> list:
    path = _history_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("messages", [])


def _save(messages: list):
    path = _history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".companion_history_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"messages": messages}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


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
