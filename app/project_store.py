"""Мульти-проєкт (Фаза 5): кілька клієнтів/акаунтів в одному дашборді з перемиканням.

Кожен проєкт має свій IG-токен, Ad Account ID, нішу і (опційно) свій Anthropic-ключ —
зберігаються в USER_DATA_DIR/projects.json. Активний проєкт — єдиний глобальний вказівник
на диску (DATA_DIR/active_project), не per-request контекст: це однокористувацький desktop-
застосунок, перемкнув проєкт — увесь дашборд і фонові job'и (планувальник) бачать нові дані.

Дані кожного проєкту (рубрики, ідеї, вердикти скриптів тощо) живуть в
DATA_DIR/projects/<project_id>/ — див. project_data_dir(). Спільні для всіх проєктів речі
(app.log, бінарник ffmpeg, скачані Whisper-моделі) лишаються прямо в DATA_DIR.
"""
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from app.config_store import CONFIG_PATH, load_config
from app.paths import DATA_DIR, USER_DATA_DIR

logger = logging.getLogger("reels_dashboard")

PROJECTS_PATH = os.path.join(USER_DATA_DIR, "projects.json")
ACTIVE_PROJECT_PATH = os.path.join(DATA_DIR, "active_project")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")

DEFAULT_PROJECT_NAME = "Мій блог"

# Поля, які живуть в проєкті (не в глобальному config.json) — той самий набір, що раніше
# лежав у config_store.DEFAULTS як "per-account".
PROJECT_FIELDS = {
    "ig_access_token": "",
    "ig_user_id": "",
    "ig_username": "",
    "ig_token_obtained_at": "",
    "ig_token_expires_at": "",
    "ads_account_id": "",
    "account_niche": "",
    # Порожній рядок = нема оверайду на цей проєкт, використовується глобальний ключ
    # з config.json (спільний за замовчуванням, див. ТЗ Фази 5).
    "anthropic_api_key": "",
    "anthropic_key_verified": False,
}

# Підмножина PROJECT_FIELDS, яка при міграції (ensure_migrated) реально переїжджає зі старого
# config.json в проєкт І прибирається з config.json. anthropic_api_key/anthropic_key_verified
# сюди НЕ входять — у старому config.json це був єдиний спільний ключ (без поняття "проєкт"),
# після міграції він лишається спільним ключем за замовчуванням, а не стає персональним
# оверайдом проєкту за замовчуванням.
MIGRATE_ONLY_FIELDS = {
    "ig_access_token",
    "ig_user_id",
    "ig_username",
    "ig_token_obtained_at",
    "ig_token_expires_at",
    "ads_account_id",
    "account_niche",
}

_lock = threading.RLock()  # той самий підхід, що config_store.py — лок на все читання+запис


def _atomic_write(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_projects() -> list:
    with _lock:
        if not os.path.exists(PROJECTS_PATH):
            return []
        try:
            with open(PROJECTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("projects.json повреждён или недоступен (%s) — использую пустой список", e)
            return []
        return data.get("projects", [])


def save_projects(projects: list):
    with _lock:
        _atomic_write(PROJECTS_PATH, {"projects": projects})


def get_active_project_id() -> str | None:
    with _lock:
        if not os.path.exists(ACTIVE_PROJECT_PATH):
            projects = load_projects()
            return projects[0]["id"] if projects else None
        try:
            with open(ACTIVE_PROJECT_PATH, "r", encoding="utf-8") as f:
                project_id = f.read().strip()
        except OSError:
            project_id = ""
        if project_id and any(p["id"] == project_id for p in load_projects()):
            return project_id
        projects = load_projects()
        return projects[0]["id"] if projects else None


def set_active_project_id(project_id: str):
    with _lock:
        _atomic_write(ACTIVE_PROJECT_PATH, project_id)


def get_project(project_id: str) -> dict | None:
    return next((p for p in load_projects() if p["id"] == project_id), None)


def get_active_project() -> dict | None:
    active_id = get_active_project_id()
    return get_project(active_id) if active_id else None


def create_project(name: str) -> dict:
    with _lock:
        projects = load_projects()
        project = {
            "id": uuid.uuid4().hex[:10],
            "name": name.strip() or DEFAULT_PROJECT_NAME,
            "created_at": _now_iso(),
            **PROJECT_FIELDS,
        }
        projects.append(project)
        save_projects(projects)
        os.makedirs(project_data_dir(project["id"]), exist_ok=True)
        return project


def update_project(project_id: str, updates: dict) -> dict | None:
    with _lock:
        projects = load_projects()
        project = next((p for p in projects if p["id"] == project_id), None)
        if not project:
            return None
        project.update(updates)
        save_projects(projects)
        return project


def update_active_project(updates: dict) -> dict | None:
    active_id = get_active_project_id()
    if not active_id:
        return None
    return update_project(active_id, updates)


def delete_project(project_id: str) -> bool:
    with _lock:
        projects = load_projects()
        if len(projects) <= 1:
            return False
        remaining = [p for p in projects if p["id"] != project_id]
        if len(remaining) == len(projects):
            return False
        save_projects(remaining)
        if get_active_project_id() == project_id:
            set_active_project_id(remaining[0]["id"])
        return True


def project_data_dir(project_id: str | None = None) -> str:
    project_id = project_id or get_active_project_id()
    path = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_effective_config() -> dict:
    """Сумісна заміна старого load_config(): глобальні поля + поля активного проєкту зверху
    (та сама форма dict, що й раніше повертав config_store.load_config(), тому більшість
    існуючих викликів можуть просто підмінити виклик без зміни логіки навколо)."""
    cfg = dict(load_config())
    project = get_active_project()
    if not project:
        cfg.update(PROJECT_FIELDS)
        return cfg
    for key in PROJECT_FIELDS:
        cfg[key] = project.get(key, PROJECT_FIELDS[key])
    # anthropic-ключ: якщо в проєкті задано оверайд — використовуємо його, інакше лишаємо
    # глобальний "спільний за замовчуванням" ключ з config.json.
    if not project.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = load_config().get("anthropic_api_key", "")
        cfg["anthropic_key_verified"] = load_config().get("anthropic_key_verified", False)
    return cfg


def ensure_migrated():
    """Одноразова міграція зі старої однотенантної версії: якщо projects.json ще нема —
    створити проєкт за замовчуванням "Мій блог" з поточних per-account полів config.json,
    перенести існуючі data/*.json (per-account файли) в data/projects/<id>/, зробити його
    активним і прибрати per-account поля з config.json (лишити тільки глобальні)."""
    if os.path.exists(PROJECTS_PATH):
        return

    cfg = load_config()
    project = {
        "id": uuid.uuid4().hex[:10],
        "name": DEFAULT_PROJECT_NAME,
        "created_at": _now_iso(),
        **PROJECT_FIELDS,
    }
    # anthropic_api_key/anthropic_key_verified ИСКЛЮЧЕНЫ намеренно: старый config.json хранил
    # ОДИН общий ключ (не было понятия "проект"), и после миграции он должен остаться именно
    # общим ключом по умолчанию (см. ниже), а не превратиться в персональный оверайд проекта —
    # иначе "общий ключ" в Настройках выглядел бы пустым сразу после миграции.
    for key in MIGRATE_ONLY_FIELDS:
        project[key] = cfg.get(key, PROJECT_FIELDS[key])
    save_projects([project])
    set_active_project_id(project["id"])

    target_dir = project_data_dir(project["id"])
    legacy_files = [
        "categories.json",
        "daily_plan.json",
        "daily_stats_history.json",
        "ideas_bank.json",
        "media_cache.json",
        "past_campaigns_history.json",
        "saved_scripts.json",
        "signals_state.json",
        "style_profile.json",
        "transcripts.json",
        "ads_kpi_targets.json",
    ]
    for name in legacy_files:
        src = os.path.join(DATA_DIR, name)
        dst = os.path.join(target_dir, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.replace(src, dst)
            except OSError as e:
                logger.error("Не удалось перенести %s в проект по умолчанию (%s)", name, e)

    # Оставляем в config.json только глобальные поля — per-account теперь только в projects.json.
    # anthropic_api_key/anthropic_key_verified НЕ трогаем (см. комментарий выше) — они остаются
    # в config.json общим ключом по умолчанию. Пишем напрямую (не через save_config, который
    # делает merge, а не замену) — иначе старые per-account ключи так и остались бы в файле
    # рядом с новыми глобальными.
    remaining = {k: v for k, v in cfg.items() if k not in MIGRATE_ONLY_FIELDS}
    _atomic_write(CONFIG_PATH, remaining)
    logger.info("Миграция на мульти-проект: создан проект по умолчанию '%s' (id=%s)", project["name"], project["id"])
