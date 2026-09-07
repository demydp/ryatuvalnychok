"""
Синглтони SQLAlchemy/Flask-Migrate + резолюція рядка підключення до БД (Этап 1 веб-версії).

Джерело істини для юзерів/проєктів/налаштувань тепер Postgres (Neon/Render, змінна
DATABASE_URL — стандартна назва, яку дають і Neon, і Render) — файловий режим
(config.json/projects.json) прибирається повністю, а не лишається паралельним шляхом
(свідоме рішення власника — файловий desktop-режим більше не окремий продукт).
DATABASE_PUBLIC_URL лишається як legacy-alias (мав пріоритет над DATABASE_URL, коли
застосунок був на Railway) — новий деплой його просто ніколи не задає.

Локальна розробка без піднятого Postgres — SQLite-файл під USER_DATA_DIR: та сама
модель/міграції, той самий db_store.py, просто інший движок, щоб `flask run` можна було
перевірити без DATABASE_URL. На проді DATABASE_URL обов'язковий (Render/Neon).
"""
import os

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from app.paths import USER_DATA_DIR

db = SQLAlchemy()
migrate = Migrate()


def get_database_uri() -> str:
    uri = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not uri:
        sqlite_path = os.path.join(USER_DATA_DIR, "app.db")
        return "sqlite:///" + sqlite_path.replace("\\", "/")
    # Деякі хостинги (Railway, Heroku) віддають URI зі схемою "postgres://", а сучасні
    # SQLAlchemy/psycopg2 вимагають "postgresql://" — без цієї підміни create_engine падає
    # на самому старті. Neon вже віддає "postgresql://" сам, підміна тут просто no-op.
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    migrate.init_app(app, db)
