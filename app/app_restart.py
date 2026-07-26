"""
Перезапуск застосунку прямо з UI (кнопка "Перезапустити" в Настройках) — та сама ідея, що
apply_update() в app/update_checker.py: піднімаємо новий процес і тихо виходимо з поточного,
щоб після правок у коді не треба було вручну шукати й вбивати pythonw.exe або запускати
start.bat з провідника.

У встановленій (frozen) збірці самоперезапуск ризикований через мьютекс
RyatuvalnychokSingleInstance в run.py: новий процес стартує за секунду до того, як старий
встигне його звільнити, бачить "вже запущено" і просто відкриває браузер, НЕ піднявши сервер —
тоді після виходу старого процесу застосунок лишається зовсім без сервера. Тому в frozen-режимі
чесно просимо скористатись ярликом замість самоперезапуску (can_restart() -> False).
"""
import logging
import os
import subprocess
import sys
import threading

from app.paths import INSTALL_DIR

logger = logging.getLogger("reels_dashboard")


def can_restart() -> bool:
    return not getattr(sys, "frozen", False)


def restart_app():
    pythonw = os.path.join(INSTALL_DIR, ".venv", "Scripts", "pythonw.exe")
    runpy = os.path.join(INSTALL_DIR, "run.py")
    logger.info("Перезапуск застосунку з UI: %s %s", pythonw, runpy)
    subprocess.Popen([pythonw, runpy], cwd=INSTALL_DIR, close_fds=True)

    def _exit_soon():
        os._exit(0)

    threading.Timer(1.0, _exit_soon).start()
