"""Проверка обновлений через version.json на GitHub Releases + запуск нового установщика.

Формат version.json (публикуется как asset в GitHub Release вместе с самим установщиком):
    {"version": "1.2.0", "url": "https://.../RyatuvalnychokSetup.exe", "notes": "..."}

ВАЖНО: UPDATE_MANIFEST_URL ниже — плейсхолдер. Перед первым релизом его нужно заменить на
реальный адрес GitHub Release (создать репозиторий, включить Releases, публиковать туда
version.json + инсталлятор при каждом выпуске), см. installer/README.md.
"""
import logging
import os
import subprocess
import tempfile
import threading

import requests

from app.version import __version__

logger = logging.getLogger("reels_dashboard")

UPDATE_MANIFEST_URL = "https://github.com/OWNER/REPO/releases/latest/download/version.json"


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in (v or "0").strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update() -> dict:
    try:
        resp = requests.get(UPDATE_MANIFEST_URL, timeout=15)
        resp.raise_for_status()
        manifest = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Проверка обновлений не удалась: %s", e)
        return {"error": str(e)}

    latest = manifest.get("version", "0")
    update_available = _parse_version(latest) > _parse_version(__version__)
    return {
        "current_version": __version__,
        "latest_version": latest,
        "update_available": update_available,
        "download_url": manifest.get("url"),
        "notes": manifest.get("notes", ""),
    }


def _download_installer(url: str) -> str:
    dest = os.path.join(tempfile.gettempdir(), "RyatuvalnychokUpdateSetup.exe")
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return dest


def apply_update(url: str):
    """Скачивает установщик и запускает его в тихом режиме. /FORCECLOSEAPPLICATIONS
    поручает самому Inno Setup закрыть текущий запущенный процесс (по AppMutex) перед
    заменой файлов — не нужно вручную координировать, кто первым освободит файлы .exe."""
    installer_path = _download_installer(url)
    subprocess.Popen(
        [installer_path, "/SILENT", "/NORESTART", "/FORCECLOSEAPPLICATIONS", "/SUPPRESSMSGBOX"],
        close_fds=True,
    )

    def _exit_soon():
        os._exit(0)

    threading.Timer(1.5, _exit_soon).start()
