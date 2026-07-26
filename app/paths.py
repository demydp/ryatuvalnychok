"""Расположение данных пользователя (config.json, кэш, история) отдельно от программы.

Установщик может в любой момент перезаписать папку программы (Program Files) свежей
версией — если бы конфиг и кэш лежали там же, обновление стирало бы токены и историю
пользователя. Поэтому все пользовательские данные живут в %LOCALAPPDATA%\\Ryatuvalnychok,
а INSTALL_DIR (папка программы/скрипта) используется только для чтения бандлованных
ресурсов (иконка и т.п.), никогда для записи.
"""
import os
import shutil
import sys

APP_DIR_NAME = "Ryatuvalnychok"


def _install_dir() -> str:
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: sys.executable — это сам .exe, рядом с ним лежат бандлованные
        # ресурсы (см. app/build/ryatuvalnychok.spec).
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


INSTALL_DIR = _install_dir()
USER_DATA_DIR = _user_data_dir()
DATA_DIR = os.path.join(USER_DATA_DIR, "data")


def _migrate_legacy_files():
    """Старые версии (до появления installer'а) держали config.json и data/ прямо в папке
    программы. Разово переносим их сюда, если новый файл ещё не существует — иначе
    пользователь, обновившись, увидел бы пустые настройки и историю."""
    legacy_config = os.path.join(INSTALL_DIR, "config.json")
    new_config = os.path.join(USER_DATA_DIR, "config.json")
    if os.path.exists(legacy_config) and not os.path.exists(new_config):
        try:
            shutil.move(legacy_config, new_config)
        except OSError:
            pass

    legacy_data = os.path.join(INSTALL_DIR, "data")
    if os.path.isdir(legacy_data) and legacy_data != DATA_DIR:
        for name in os.listdir(legacy_data):
            src = os.path.join(legacy_data, name)
            dst = os.path.join(DATA_DIR, name)
            if os.path.exists(dst):
                continue
            try:
                shutil.move(src, dst)
            except OSError:
                pass


os.makedirs(USER_DATA_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
_migrate_legacy_files()
