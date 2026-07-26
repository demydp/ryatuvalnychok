"""Чтение и запись локального config.json — глобальные настройки, общие для всех проектов
(per-project токены/ключи см. app/project_store.py, projects.json).

Ключи должны переживать перезапуск/аварийное завершение процесса — поэтому запись всегда
атомарная (пишем во временный файл рядом и заменяем оригинал одним os.replace, что на Windows
и POSIX атомарно на уровне файловой системы), а битый/обрезанный config.json при чтении не
роняет приложение, а откатывается на последние значения по умолчанию с логом причины."""
import json
import logging
import os
import tempfile
import threading

from app.paths import USER_DATA_DIR

CONFIG_PATH = os.path.join(USER_DATA_DIR, "config.json")

logger = logging.getLogger("reels_dashboard")

DEFAULTS = {
    # ig_access_token / ig_user_id / ig_username / ads_account_id / account_niche и связанные
    # с ними поля токена теперь per-project (см. app/project_store.py, projects.json) —
    # здесь остаются только настройки, общие для всего приложения независимо от проекта.
    #
    # anthropic_api_key — «общий по умолчанию» ключ (см. ТЗ Фазы 5: проект может задать
    # свой собственный, но по умолчанию использует этот).
    "anthropic_api_key": "",
    # test-anthropic-key не сохраняет ключ сам по себе (см. app/routes/settings.py) —
    # этот флаг ставится только при успешной проверке ТЕКУЩЕГО сохранённого ключа и
    # сбрасывается, если ключ поменяли, но не перепроверили. Мастер настройки использует
    # его, чтобы понять, можно ли пускать пользователя дальше.
    "anthropic_key_verified": False,
    # Мастер настройки при первом запуске пройден полностью (все 3 ключа введены и
    # проверены) — пока False, index-роут отдаёт onboarding.html вместо index.html.
    "setup_completed": False,
    "max_media": 100,
    # "uk" / "ru" / "" (пусто = автоопределение языка в Whisper)
    "content_language": "",
    # "small" (быстрее) / "medium" (точнее, дольше качается и распознаёт)
    "whisper_model": "small",
    # Час (0-23, локальное время машины), в который планировщик собирает ежедневный
    # срез активной рекламы для истории отчётов.
    "daily_report_hour": 20,
    # Раз во сколько часов (3-6) планировщик сам обновляет метрики Instagram и структуру
    # рекламного кабинета активного проекта — чтобы не нажимать «Синхронизировать» вручную.
    "auto_refresh_interval_hours": 4,
}

_lock = threading.RLock()  # RLock — save_config держит лок на всё чтение+запись и внутри вызывает load_config()


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULTS)
    with _lock:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Битый config.json (например, процесс убили во время записи на старой,
            # неатомарной версии этого файла) — не роняем приложение, работаем на
            # дефолтах и громко логируем, чтобы это было видно в data/app.log.
            logger.error("config.json повреждён или недоступен (%s) — использую значения по умолчанию", e)
            return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_config(updates: dict):
    # Чтение и запись — под ОДНИМ и тем же логом, иначе два параллельных save_config
    # читают один и тот же "current" до того, как другой успел записать, и второй write
    # тихо затирает поле, изменённое первым (lost update).
    with _lock:
        current = load_config()
        current.update(updates)
        fd, tmp_path = tempfile.mkstemp(dir=USER_DATA_DIR, prefix=".config_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, CONFIG_PATH)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    return current


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
