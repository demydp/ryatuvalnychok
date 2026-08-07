"""
Мульти-проєкт — тонкий фасад зі СТАРИМИ сигнатурами (load_projects(), get_active_project(),
create_project(name), project_data_dir(project_id) тощо) над app/db_store.py (Этап 1 веб-версії:
джерело істини тепер БД — Postgres/Railway або SQLite локально, — а не projects.json).

Кожен виклик неявно прив'язаний до flask_login.current_user — раніше "активний проєкт" був
одним глобальним файлом-вказівником на весь (однокористувацький desktop) застосунок, тепер це
прапорець Project.is_active, унікальний У МЕЖАХ ОДНОГО ЮЗЕРА (див. app/db_store.py). Ці функції
МАЮТЬ сенс лише всередині активного HTTP-запиту залогіненого юзера. Фоновим job'ам
(app/scheduler.py) без сесії — app/db_store.py напряму з явним user_id.

project_data_dir() — ЄДИНЕ, що навмисно НЕ переїхало в БД цієї стадії (рішення власника,
Этап 2): дані проєкту (рубрики, медіа-кеш, скрипти, звіти тощо) і далі фізичні файли на диску
під DATA_DIR/projects/<id>/, просто <id> тепер видає БД, а не projects.json.
"""
import os

from flask_login import current_user

from app import db_store
from app.paths import DATA_DIR

PROJECTS_DIR = os.path.join(DATA_DIR, "projects")

DEFAULT_PROJECT_NAME = db_store.DEFAULT_PROJECT_NAME


def load_projects() -> list:
    return db_store.load_user_projects(current_user.id)


def get_active_project_id() -> str | None:
    return db_store.get_active_project_id(current_user.id)


def set_active_project_id(project_id: str):
    db_store.set_active_project_id(current_user.id, project_id)


def get_project(project_id: str) -> dict | None:
    return db_store.get_project(current_user.id, project_id)


def get_active_project() -> dict | None:
    return db_store.get_active_project(current_user.id)


def create_project(name: str) -> dict:
    project = db_store.create_project(current_user.id, name)
    os.makedirs(project_data_dir(project["id"]), exist_ok=True)
    return project


def update_project(project_id: str, updates: dict) -> dict | None:
    return db_store.update_project(current_user.id, project_id, updates)


def update_active_project(updates: dict) -> dict | None:
    return db_store.update_active_project(current_user.id, updates)


def delete_project(project_id: str) -> bool:
    return db_store.delete_project(current_user.id, project_id)


def project_data_dir(project_id: str | None = None) -> str:
    project_id = project_id or get_active_project_id()
    path = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_effective_config() -> dict:
    return db_store.get_effective_config(current_user.id)


def ensure_migrated():
    """Стадія 1: тут більше нема чого мігрувати (файлів config.json/projects.json, з яких
    раніше піднімався перший проєкт, у веб-версії просто нема) — схему БД створює/оновлює
    Alembic (flask db upgrade), а перший проєкт кожного юзера створюється при реєстрації
    (app/db_store.py::ensure_user_initialized(), викликається з app/routes/auth.py).
    Лишається no-op заради сумісності сигнатури з app/__init__.py."""
    return None
