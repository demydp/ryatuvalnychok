"""Скачивание модели Whisper с прогрессом для мастера настройки.

transcription.py грузит модель лениво (при первой транскрипции) без прогресса — это
нормально для обычного использования, но в мастере настройки пользователь должен видеть
прогресс-бар, а не молча ждущую кнопку. Логика скачивания та же самая (whisper.load_model
с download_root=WHISPER_MODELS_DIR, см. transcription.py) — этот модуль лишь параллельно
следит за размером файла на диске, чтобы отдать проценты через отдельный статус-эндпоинт.
"""
import os
import threading

from app.transcription import DEFAULT_MODEL, WHISPER_MODELS_DIR, _get_model

_state_lock = threading.Lock()
_state = {"status": "idle", "percent": 0, "model": None, "error": None}


def _target_path(model_name: str) -> str:
    import whisper

    url = whisper._MODELS[model_name]
    return os.path.join(WHISPER_MODELS_DIR, os.path.basename(url))


def _expected_size(model_name: str) -> int:
    import requests
    import whisper

    url = whisper._MODELS[model_name]
    try:
        resp = requests.head(url, timeout=15, allow_redirects=True)
        return int(resp.headers.get("Content-Length") or 0)
    except requests.RequestException:
        return 0


def _watch_progress(model_name: str, total: int, stop_event: threading.Event):
    target = _target_path(model_name)
    while not stop_event.is_set():
        try:
            size = os.path.getsize(target) if os.path.exists(target) else 0
        except OSError:
            size = 0
        if total:
            with _state_lock:
                if _state["status"] == "downloading":
                    _state["percent"] = min(99, int(size * 100 / total))
        stop_event.wait(0.5)


def start_download(model_name: str = DEFAULT_MODEL):
    with _state_lock:
        if _state["status"] == "downloading":
            return
        _state.update(status="downloading", percent=0, model=model_name, error=None)

    def run():
        stop_event = threading.Event()
        total = _expected_size(model_name)
        watcher = threading.Thread(target=_watch_progress, args=(model_name, total, stop_event), daemon=True)
        watcher.start()
        try:
            _get_model(model_name)
            with _state_lock:
                _state.update(status="done", percent=100)
        except Exception as e:
            with _state_lock:
                _state.update(status="error", error=str(e))
        finally:
            stop_event.set()

    threading.Thread(target=run, daemon=True).start()


def get_download_status() -> dict:
    with _state_lock:
        return dict(_state)
