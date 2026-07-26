"""Определение локального IP в локальной сети (Wi-Fi/LAN) — чтобы показать пользователю
адрес, по которому дашборд открывается с телефона, когда сервер слушает 0.0.0.0."""
import socket

PORT = 5000


def get_local_ip() -> str:
    # UDP-сокет ничего никуда не отправляет (connect() на UDP только выбирает исходящий
    # интерфейс по таблице маршрутизации ОС) — самый надёжный кроссплатформенный способ
    # узнать IP машины в локальной сети без внешних зависимостей.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_lan_url() -> str:
    return f"http://{get_local_ip()}:{PORT}"
