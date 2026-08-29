"""
Моделі БД для веб-версії. Джерело істини — Postgres (Railway, DATABASE_PUBLIC_URL) /
SQLite локально (app/db.py::get_database_uri). Замінює файлові config.json/projects.json/
project_data_dir() — див. app/config_store.py, app/project_store.py, app/db_store.py.

ProjectData (Этап 2): дженерик KV per-project, всі ~15 колишніх файлових модулів (категорії/
медіа-кеш/скрипти/профіль стилю/звіти тощо) читають/пишуть сюди через app/project_data_store.py
замість файлів на диску — на Railway ФС ефемерна, файли не пережили б рестарт/редеплой.

AiUsageDaily — лічильник БЕЗ блокування використання: кожен юзер вводить власний Anthropic-ключ,
тому ліміт витрат — його особиста відповідальність, а не привід зупиняти застосунок.
"""
import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from sqlalchemy.types import Text, TypeDecorator
from werkzeug.security import check_password_hash, generate_password_hash

from app.crypto import decrypt, encrypt
from app.db import db


def _now():
    return datetime.now(timezone.utc)


def _new_project_id() -> str:
    # Той самий формат id, що раніше генерував app/project_store.py::create_project() —
    # десятки модулів по всьому коду вже трактують project_id як непрозорий hex-рядок,
    # змінювати формат немає причини.
    return uuid.uuid4().hex[:10]


class EncryptedText(TypeDecorator):
    """Прозоре шифрування колонки через app/crypto.py (Fernet) — модель/виклики працюють зі
    звичайним рядком, у БД лежить лише шифротекст. Порожній рядок/None не шифруються
    (див. app/crypto.py::encrypt) — інакше "нема токена" виглядало б як непорожній шифротекст."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)

    settings = db.relationship("UserSettings", backref="user", uselist=False, cascade="all, delete-orphan")
    projects = db.relationship("Project", backref="user", cascade="all, delete-orphan", order_by="Project.created_at")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class UserSettings(db.Model):
    """Аналог старого глобального config.json (app/config_store.py DEFAULTS) — тепер per-user,
    а не per-машина: спільні для всіх проєктів ЦЬОГО юзера налаштування."""

    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    anthropic_api_key = db.Column(EncryptedText, default="")
    anthropic_key_verified = db.Column(db.Boolean, default=False, nullable=False)
    setup_completed = db.Column(db.Boolean, default=False, nullable=False)
    max_media = db.Column(db.Integer, default=100, nullable=False)
    content_language = db.Column(db.String(8), default="", nullable=False)
    whisper_model = db.Column(db.String(16), default="small", nullable=False)
    daily_report_hour = db.Column(db.Integer, default=20, nullable=False)
    auto_refresh_interval_hours = db.Column(db.Integer, default=4, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class Project(db.Model):
    """Аналог запису в старому projects.json (app/project_store.py PROJECT_FIELDS) — тепер FK
    на User замість "єдиний глобальний файл на весь застосунок". is_active замінює старий
    файл-вказівник DATA_DIR/active_project: тепер це прапорець НА ПРОЄКТІ, унікальний у межах
    одного user_id (пильнується в app/db_store.py, не constraint'ом БД — той самий підхід, що
    й раніше, лише перенесений з файлу в колонку)."""

    __tablename__ = "projects"

    id = db.Column(db.String(20), primary_key=True, default=_new_project_id)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)

    ig_access_token = db.Column(EncryptedText, default="")
    ig_user_id = db.Column(db.String(64), default="")
    ig_username = db.Column(db.String(255), default="")
    ig_token_obtained_at = db.Column(db.String(64), default="")
    ig_token_expires_at = db.Column(db.String(64), default="")
    ads_account_id = db.Column(db.String(64), default="")
    account_niche = db.Column(db.Text, default="")
    # TikTok for Developers (Login Kit OAuth v2 + Display API) — Этап діагностики, серпень 2026.
    # access_token живе типово ~24 год, refresh_token — ~365 днів (див. app/tiktok_token_refresh.py);
    # обидва шифруються так само, як ig_access_token.
    tiktok_access_token = db.Column(EncryptedText, default="")
    tiktok_refresh_token = db.Column(EncryptedText, default="")
    tiktok_open_id = db.Column(db.String(128), default="")
    tiktok_username = db.Column(db.String(255), default="")
    tiktok_display_name = db.Column(db.String(255), default="")
    tiktok_avatar_url = db.Column(db.Text, default="")
    tiktok_token_obtained_at = db.Column(db.String(64), default="")
    tiktok_access_token_expires_at = db.Column(db.String(64), default="")
    tiktok_refresh_token_expires_at = db.Column(db.String(64), default="")
    # Опційний оверайд спільного UserSettings.anthropic_api_key на рівні одного проєкту —
    # та сама семантика, що була в PROJECT_FIELDS/get_effective_config() раніше.
    anthropic_api_key = db.Column(EncryptedText, default="")
    anthropic_key_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    data_entries = db.relationship("ProjectData", backref="project", cascade="all, delete-orphan")


class ProjectData(db.Model):
    """Стадія 1 — ЛИШЕ схема (свідоме рішення власника, TODO Этап 2): категорії, медіа-кеш,
    збережені скрипти, профіль стилю, звіти й PDF і досі читаються/пишуться файлами в
    project_data_dir() (app/project_store.py, ~15 файлів у ~10 модулях) — жоден з цих модулів
    у Стадії 1 на цю таблицю не переведений. key — те саме ім'я, що раніше було іменем файлу
    (наприклад "categories.json"), value — серіалізований JSON-текст."""

    __tablename__ = "project_data"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_project_data_project_key"),)

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(20), db.ForeignKey("projects.id"), nullable=False, index=True)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class AiUsageDaily(db.Model):
    """Лічильник звернень до Anthropic по днях — ТІЛЬКИ для спостереження (дашборд/діагностика
    власника застосунку), без жодного лімітування чи блокування: кожен юзер платить власним
    Anthropic-ключем, тому обмежувати його виклики немає підстави."""

    __tablename__ = "ai_usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_ai_usage_user_date"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    request_count = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
