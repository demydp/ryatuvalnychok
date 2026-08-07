"""
Синглтони SQLAlchemy/Flask-Migrate + резолюція рядка підключення до БД (Этап 1 веб-версії).

Джерело істини для юзерів/проєктів/налаштувань тепер Postgres (Railway, DATABASE_PUBLIC_URL) —
файловий режим (config.json/projects.json) прибирається повністю, а не лишається паралельним
шляхом (свідоме рішення власника — файловий desktop-режим більше не окремий продукт).

Локальна розробка без піднятого Railway Postgres — SQLite-файл під USER_DATA_DIR: та сама
модель/міграції, той самий db_store.py, просто інший движок, щоб `flask run` можна було
перевірити без DATABASE_PUBLIC_URL. На проді DATABASE_PUBLIC_URL обов'язковий (Railway).
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
    # Railway (як і Heroku) віддає URI зі схемою "postgres://", а сучасні SQLAlchemy/psycopg2
    # вимагають "postgresql://" — без цієї підміни create_engine падає на самому старті.
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    migrate.init_app(app, db)
