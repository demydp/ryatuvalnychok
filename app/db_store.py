"""
DB-бекенд для налаштувань/проєктів (Этап 1 веб-версії) — явно параметризований user_id,
БЕЗ прив'язки до flask_login.current_user. Дві причини тримати це окремо від
config_store.py/project_store.py (тонких фасадів зі старими сигнатурами, див. ті файли):

1. app/scheduler.py — фонові job'и APScheduler виконуються ПОЗА HTTP-запитом, там немає
   current_user (немає сесії взагалі) — їм потрібен прямий доступ "дані ЦЬОГО user_id",
   а не "дані поточного залогіненого юзера".
2. Ізоляція даних між юзерами тримається в ОДНОМУ місці (тут, у WHERE-умовах), а не
   розмазана по роутах — get_project()/update_project()/delete_project() ніколи не
   поверне/не змінить чужий проєкт, навіть якщо викликач помилково передасть чужий id.

Секрети (IG-токен, Anthropic-ключі) шифруються прозоро на рівні колонки (EncryptedText,
див. app/models.py + app/crypto.py) — тут з ними працюють як зі звичайними рядками.
Ніде в цьому файлі значення секретів не потрапляють у logger.
"""
import logging
import uuid
from datetime import datetime, timezone

from app.db import db
from app.models import Project, User, UserSettings

logger = logging.getLogger("reels_dashboard")

DEFAULT_PROJECT_NAME = "Мій проєкт"

# Той самий набір per-project полів, що раніше жив у app/project_store.py::PROJECT_FIELDS —
# форма словника, яку повертають get_project()/get_active_project()/create_project() тут,
# має лишитись такою самою, бо десятки місць коду читають ці ключі напряму.
PROJECT_FIELDS = (
    "ig_access_token",
    "ig_user_id",
    "ig_username",
    "ig_token_obtained_at",
    "ig_token_expires_at",
    "ads_account_id",
    "account_niche",
    "anthropic_api_key",
    "anthropic_key_verified",
)

# Той самий набір, що раніше був у config_store.py::DEFAULTS (без per-project полів —
# вони тепер завжди в Project, див. PROJECT_FIELDS вище).
USER_SETTINGS_FIELDS = (
    "anthropic_api_key",
    "anthropic_key_verified",
    "setup_completed",
    "max_media",
    "content_language",
    "whisper_model",
    "daily_report_hour",
    "auto_refresh_interval_hours",
)


def _now():
    return datetime.now(timezone.utc)


def _project_to_dict(project: Project) -> dict:
    d = {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }
    for field in PROJECT_FIELDS:
        d[field] = getattr(project, field)
    return d


def _settings_to_dict(settings: UserSettings) -> dict:
    return {field: getattr(settings, field) for field in USER_SETTINGS_FIELDS}


def get_or_create_user_settings(user_id: int) -> UserSettings:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        return settings
    settings = UserSettings(user_id=user_id)
    db.session.add(settings)
    db.session.commit()
    return settings


def ensure_user_initialized(user_id: int):
    """Викликається одразу після реєстрації (і захисно — на початку будь-якого читання
    налаштувань/проєктів): гарантує, що в юзера є UserSettings і хоча б один активний
    проєкт — той самий інваріант, що раніше тримав project_store.py::ensure_migrated()
    для однокористувацької версії, лише тепер на реєстрацію кожного юзера, а не один раз
    на весь застосунок."""
    get_or_create_user_settings(user_id)
    has_project = Project.query.filter_by(user_id=user_id).first() is not None
    if not has_project:
        create_project(user_id, DEFAULT_PROJECT_NAME)


def load_user_config(user_id: int) -> dict:
    settings = get_or_create_user_settings(user_id)
    return _settings_to_dict(settings)


def save_user_config(user_id: int, updates: dict) -> dict:
    settings = get_or_create_user_settings(user_id)
    for key, value in updates.items():
        if key in USER_SETTINGS_FIELDS:
            setattr(settings, key, value)
    settings.updated_at = _now()
    db.session.commit()
    return _settings_to_dict(settings)


def load_user_projects(user_id: int) -> list:
    ensure_user_initialized(user_id)
    projects = Project.query.filter_by(user_id=user_id).order_by(Project.created_at).all()
    return [_project_to_dict(p) for p in projects]


def get_active_project_id(user_id: int):
    ensure_user_initialized(user_id)
    active = Project.query.filter_by(user_id=user_id, is_active=True).first()
    if active:
        return active.id
    first = Project.query.filter_by(user_id=user_id).order_by(Project.created_at).first()
    return first.id if first else None


def set_active_project_id(user_id: int, project_id: str) -> bool:
    """Повертає False, якщо project_id не належить цьому user_id (немає такого чужого
    проєкту в юзера) — ізоляція, не мовчазна відмова активувати чужі дані."""
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    if not project:
        return False
    Project.query.filter_by(user_id=user_id, is_active=True).update({"is_active": False})
    project.is_active = True
    db.session.commit()
    return True


def get_project(user_id: int, project_id: str):
    if not project_id:
        return None
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    return _project_to_dict(project) if project else None


def get_active_project(user_id: int):
    active_id = get_active_project_id(user_id)
    return get_project(user_id, active_id) if active_id else None


def create_project(user_id: int, name: str) -> dict:
    project = Project(
        user_id=user_id,
        name=(name or "").strip() or DEFAULT_PROJECT_NAME,
    )
    db.session.add(project)
    db.session.flush()  # потрібен project.id (генерується default'ом моделі) до commit
    # Перший проєкт юзера одразу активний — інакше get_active_project_id() довелося б
    # окремо ще раз ставити активність одразу після створення на кожному виклику.
    if Project.query.filter_by(user_id=user_id).count() == 1:
        project.is_active = True
    db.session.commit()
    return _project_to_dict(project)


def update_project(user_id: int, project_id: str, updates: dict):
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    if not project:
        return None
    for key, value in updates.items():
        if key == "name" or key in PROJECT_FIELDS:
            setattr(project, key, value)
    db.session.commit()
    return _project_to_dict(project)


def update_active_project(user_id: int, updates: dict):
    active_id = get_active_project_id(user_id)
    if not active_id:
        return None
    return update_project(user_id, active_id, updates)


def delete_project(user_id: int, project_id: str) -> bool:
    projects = Project.query.filter_by(user_id=user_id).all()
    if len(projects) <= 1:
        return False
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        return False
    was_active = project.is_active
    db.session.delete(project)
    db.session.commit()
    if was_active:
        remaining = Project.query.filter_by(user_id=user_id).order_by(Project.created_at).first()
        if remaining:
            set_active_project_id(user_id, remaining.id)
    return True


def get_effective_config(user_id: int) -> dict:
    """Сумісна заміна старого project_store.py::get_effective_config(): глобальні (per-user)
    налаштування + поля активного проєкту зверху, з тим самим правилом для anthropic-ключа
    (оверайд проєкту, якщо заданий, інакше спільний ключ юзера)."""
    cfg = load_user_config(user_id)
    project = get_active_project(user_id)
    if not project:
        cfg.update({f: ("" if f != "anthropic_key_verified" else False) for f in PROJECT_FIELDS})
        return cfg
    for field in PROJECT_FIELDS:
        cfg[field] = project.get(field)
    if not project.get("anthropic_api_key"):
        user_cfg = load_user_config(user_id)
        cfg["anthropic_api_key"] = user_cfg.get("anthropic_api_key", "")
        cfg["anthropic_key_verified"] = user_cfg.get("anthropic_key_verified", False)
    return cfg


def get_user_by_email(email: str):
    return User.query.filter_by(email=(email or "").strip().lower()).first()


def create_user(email: str, password: str) -> User:
    user = User(email=(email or "").strip().lower())
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    ensure_user_initialized(user.id)
    return user


def create_anonymous_user() -> User:
    """Анонімна сесія (Этап 3): без реєстрації/пароля юзер отримує "порожній" User-рядок
    з синтетичним email/паролем, які ніде не показуються і не використовуються для входу —
    User.email/password_hash лишились NOT NULL у схемі, тому це найдешевший спосіб завести
    рядок без міграції. Прив'язка юзера до браузера — довгоживучий remember-cookie
    Flask-Login (див. login_user(..., remember=True) в app/__init__.py), а не ці поля."""
    token = uuid.uuid4().hex
    user = User(email=f"anon-{token}@ryatuvalnychok.local")
    user.set_password(uuid.uuid4().hex)
    db.session.add(user)
    db.session.commit()
    ensure_user_initialized(user.id)
    return user
