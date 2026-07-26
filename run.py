import logging
import os
import sys
import threading
import webbrowser

from app.network_info import PORT, get_local_ip

# Совпадает с APP_MUTEX в app/update_checker.py и AppMutex в installer/ryatuvalnychok.iss —
# все три места должны называть один и тот же мьютекс, иначе проверка "уже запущено" и
# автозакрытие при тихом обновлении не будут находить процесс друг друга.
APP_MUTEX_NAME = "RyatuvalnychokSingleInstance"


def _already_running() -> bool:
    """Второй запуск .exe (второй клик по ярлыку) не должен поднимать второй Flask-процесс
    на том же порту — вместо падения с "Address already in use" просто открываем браузер
    на уже работающий сервер и выходим. Именованный мьютекс Windows — самый простой способ
    проверить это без стороннего пакета вроде pywin32."""
    if os.name != "nt":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def _open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    # frozen = собранный PyInstaller .exe (см. installer/ryatuvalnychok.spec). При обычном
    # запуске из исходников (python run.py, разработка) ведём себя как раньше — без
    # авто-открытия браузера и без mutex-проверки, чтобы не менять привычный workflow start.bat.
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen and _already_running():
        _open_browser()
        sys.exit(0)

    logger = logging.getLogger("reels_dashboard")
    from app import create_app

    app = create_app()

    local_ip = get_local_ip()
    logger.info("Дашборд слушает 0.0.0.0:%s (в локальной сети: http://%s:%s)", PORT, local_ip, PORT)
    print(f"Рятувальничок: http://127.0.0.1:{PORT}")
    print(f"С телефона (та же Wi-Fi): http://{local_ip}:{PORT}")

    if is_frozen:
        threading.Timer(1.2, _open_browser).start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
