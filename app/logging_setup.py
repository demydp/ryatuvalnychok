"""
Логирование в файл — единственный способ увидеть, что реально произошло при сбое, т.к.
приложение запускается через pythonw.exe (start.bat), у которого нет консоли: любой
traceback, не записанный в файл, просто исчезает, и пользователь видит только "программа
не работает" без единой зацепки для диагностики.

RotatingFileHandler ограничивает размер лога (5 МБ x 3 файла) — при активном использовании
за месяцы лог не разрастётся до гигабайтов.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from app.paths import DATA_DIR

LOG_PATH = os.path.join(DATA_DIR, "app.log")

_configured = False


def setup_logging():
    global _configured
    if _configured:
        return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    logger = logging.getLogger("reels_dashboard")
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(handler)

    # Модуль werkzeug логирует каждый HTTP-запрос — тоже полезно иметь в файле при разборе
    # "что происходило перед сбоем", без этого видно только наши собственные сообщения.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.addHandler(handler)
    werkzeug_logger.setLevel(logging.INFO)

    _configured = True
    logger.info("=== Рятувальничок запущен, логирование настроено ===")
    return logger
