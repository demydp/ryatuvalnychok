"""
Локальная транскрипция рилсов (Whisper, офлайн) + определение длины ролика через ffmpeg
(Graph API длительность видео не отдаёт ни по одному полю).

Тяжёлая операция: скачивание видео + распознавание речи занимают время, поэтому
вызывается только по кнопке (см. app/routes/hooks.py), никогда автоматически при синке.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from statistics import mean

import requests

from app.hook_classifier import classify_hook_with_claude
from app.hunt_classifier import classify_hunt_stage
from app.i18n import current_lang
from app.instagram_api import get_media_url
from app.paths import DATA_DIR
from app.project_data_store import get_json, set_json

WHISPER_MODELS = ("small", "medium")
DEFAULT_MODEL = "small"
MODEL_SIZE_HINTS = {"small": "~460 МБ", "medium": "~1.5 ГБ"}

# Модели Whisper и ffmpeg — общие для всех проектов (тяжёлые бинарники/веса, не пользовательские
# данные), поэтому остаются в DATA_DIR (локальный диск, не БД). Кэш транскриптов — per-project,
# в БД (ProjectData, ключ "transcripts.json", см. app/project_data_store.py).
WHISPER_MODELS_DIR = os.path.join(DATA_DIR, "whisper-models")

_TRANSCRIPTS_KEY = "transcripts.json"

# Пороги — стандартные дефолты самого Whisper (decode_options: logprob_threshold=-1.0,
# no_speech_threshold=0.6, compression_ratio_threshold=2.4), не придуманы нами.
# Превышение сигнализирует типичные проблемы на музыке/пении/шуме: низкая уверенность
# модели, много "тишины" по её же оценке, или зацикленный/повторяющийся текст
# (частый признак галлюцинации модели на неречевом аудио).
LOGPROB_THRESHOLD = -1.0
NO_SPEECH_THRESHOLD = 0.6
COMPRESSION_RATIO_THRESHOLD = 2.4

_model_singletons = {}
_ffmpeg_path_ready = False


def _ensure_ffmpeg_on_path():
    """Whisper вызывает системную команду `ffmpeg` по имени (не по полному пути), поэтому
    bundled-бинарник из imageio_ffmpeg нужно один раз скопировать под именем ffmpeg.exe
    и добавить его папку в PATH процесса — иначе транскрипция падает с WinError 2."""
    global _ffmpeg_path_ready
    if _ffmpeg_path_ready:
        return
    import imageio_ffmpeg

    bin_dir = os.path.join(DATA_DIR, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    target = os.path.join(bin_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not os.path.exists(target):
        shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), target)
        if os.name != "nt":
            os.chmod(target, 0o755)
    if bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    _ffmpeg_path_ready = True

# Эвристика классификации хука по ключевым словам (RU/UA) — не NLP-модель, а быстрый
# приближённый разбор. Показываем пользователю как "предположительный тип", не как факт.
PROVOCATION_KEYWORDS = [
    "хватит", "перестань", "прекрати", "никогда не", "это ошибка", "неправильно",
    "бесит", "враньё", "обман", "не ведись", "досить", "перестань", "помилка", "брехня",
]
PAIN_KEYWORDS = [
    "болит", "боишься", "устал", "тяжело", "проблема", "не получается", "страшно",
    "сложно", "беспокоит", "переживаешь", "не хватает", "мучает", "втомився", "боляче",
    "проблема", "не виходить", "важко", "боїшся",
]


def is_model_downloaded(model_name: str = DEFAULT_MODEL) -> bool:
    return os.path.exists(os.path.join(WHISPER_MODELS_DIR, f"{model_name}.pt"))


def _get_model(model_name: str = DEFAULT_MODEL):
    if model_name not in _model_singletons:
        _ensure_stdio()
        _ensure_ffmpeg_on_path()
        import whisper

        os.makedirs(WHISPER_MODELS_DIR, exist_ok=True)
        _model_singletons[model_name] = whisper.load_model(model_name, download_root=WHISPER_MODELS_DIR)
    return _model_singletons[model_name]


def _ffmpeg_exe() -> str:
    _ensure_ffmpeg_on_path()
    return os.path.join(DATA_DIR, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")


class _NullWriter:
    """Заглушка для sys.stdout/sys.stderr, коли їх немає (див. _ensure_stdio)."""

    def write(self, *args, **kwargs):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False


def _ensure_stdio():
    """pythonw.exe (без консолі — саме так реально стартує start.bat, не через `python
    run.py` з консолі розробника) лишає sys.stdout/sys.stderr/sys.stdin рівними None.
    Whisper всередині показує прогрес через tqdm, який за замовчуванням пише в
    sys.stderr — виклик .write() на None валить транскрипцію з 'NoneType' object has
    no attribute 'write''. Підміняємо на no-op writer, лише якщо реально None — не
    чіпаємо справжній stdout/stderr при запуску з консолі (розробка)."""
    if sys.stdout is None:
        sys.stdout = _NullWriter()
    if sys.stderr is None:
        sys.stderr = _NullWriter()


def _download(url: str, dest_path: str):
    resp = requests.get(url, stream=True, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Не удалось скачать видео (HTTP {resp.status_code})")
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def _probe_duration(video_path: str):
    proc = subprocess.run(
        [_ffmpeg_exe(), "-i", video_path], capture_output=True, text=True, timeout=30
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def _extract_audio(video_path: str, audio_path: str):
    proc = subprocess.run(
        [_ffmpeg_exe(), "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", audio_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not os.path.exists(audio_path):
        raise RuntimeError("Не удалось извлечь аудио через ffmpeg: " + proc.stderr[-400:])


def classify_hook(text: str, anthropic_api_key: str = None) -> str:
    """5 категорий: вопрос/боль/провокация/цифра/утверждение. Сначала быстрые и бесплатные
    ключевые правила; если ни одно не сработало — просим Claude Haiku выбрать категорию
    (если задан ключ), иначе честно относим к "утверждение" (без выраженного признака)."""
    t = (text or "").lower()
    if "?" in t:
        return "вопрос"
    if re.search(r"\d", t):
        return "цифра"
    if any(k in t for k in PROVOCATION_KEYWORDS):
        return "провокация"
    if any(k in t for k in PAIN_KEYWORDS):
        return "боль"

    if anthropic_api_key:
        claude_label = classify_hook_with_claude(text, anthropic_api_key)
        if claude_label:
            return claude_label

    return "утверждение"


def _extract_hook_text(segments: list, full_text: str) -> str:
    """Первая смысловая фраза ролика. Whisper режет сегменты по паузам — иногда первый
    сегмент это одно междометие ("Йо!"), тогда добавляем следующий, чтобы хук был читаемым."""
    if not segments:
        return full_text.split(".")[0].strip() if full_text else ""
    hook = segments[0]["text"].strip()
    if len(hook.split()) < 4 and len(segments) > 1:
        hook = f"{hook} {segments[1]['text'].strip()}".strip()
    return hook


def _assess_quality(raw_segments: list) -> tuple:
    """Признаки низкой точности транскрипта (музыка/пение/шум) по стандартным порогам
    самого Whisper. Возвращает (low_confidence: bool, reason: str|None)."""
    logprobs = [s["avg_logprob"] for s in raw_segments if s.get("avg_logprob") is not None]
    no_speech = [s["no_speech_prob"] for s in raw_segments if s.get("no_speech_prob") is not None]
    compressions = [s["compression_ratio"] for s in raw_segments if s.get("compression_ratio") is not None]

    reasons = []
    if logprobs and mean(logprobs) < LOGPROB_THRESHOLD:
        reasons.append("низкая уверенность модели в распознанном тексте")
    if no_speech and mean(no_speech) > NO_SPEECH_THRESHOLD:
        reasons.append("модель считает, что в большей части ролика нет чёткой речи")
    if compressions and mean(compressions) > COMPRESSION_RATIO_THRESHOLD:
        reasons.append("текст похож на зацикленный/повторяющийся (частый признак музыки или шума)")

    if not reasons:
        return False, None
    return True, "; ".join(reasons)


def process_media(
    access_token: str,
    media_id: str,
    model_name: str = DEFAULT_MODEL,
    language: str = None,
    anthropic_api_key: str = None,
) -> dict:
    if model_name not in WHISPER_MODELS:
        model_name = DEFAULT_MODEL

    media_url = get_media_url(access_token, media_id)
    tmp_dir = tempfile.mkdtemp(prefix="reels_dash_")
    video_path = os.path.join(tmp_dir, "video.mp4")
    audio_path = os.path.join(tmp_dir, "audio.wav")
    try:
        _download(media_url, video_path)
        duration_sec = _probe_duration(video_path)
        _extract_audio(video_path, audio_path)

        model = _get_model(model_name)
        # verbose=False — не лише вимикає прогрес-бар (tqdm), а й прибирає print() з
        # текстом сегментів всередині Whisper: без консолі (pythonw.exe) обидва шляхи
        # писали б у sys.stdout/stderr, які _ensure_stdio() підмінює, але краще взагалі
        # не покладатись на це і не друкувати нічого зайвого.
        result = model.transcribe(audio_path, fp16=False, language=language or None, verbose=False)

        text = (result.get("text") or "").strip()
        raw_segments = result.get("segments", [])
        segments = [
            {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
            for s in raw_segments
        ]
        hook_text = _extract_hook_text(segments, text)
        low_confidence, quality_reason = _assess_quality(raw_segments)
        hunt = classify_hunt_stage(text, anthropic_api_key, lang=current_lang())

        return {
            "status": "ok",
            "duration_sec": round(duration_sec, 2) if duration_sec else None,
            "language": result.get("language"),
            "text": text,
            "segments": segments,
            "hook_text": hook_text,
            "hook_type": classify_hook(hook_text, anthropic_api_key),
            "low_confidence": low_confidence,
            "quality_reason": quality_reason,
            "hunt_stage": hunt["stage"],
            "hunt_temperature": hunt["temperature"],
            "hunt_reasoning": hunt["reasoning"],
            "hunt_note": hunt["note"],
            "model": model_name,
            "transcribed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def load_transcripts(project_id: str = None) -> dict:
    return get_json(_TRANSCRIPTS_KEY, default={}, project_id=project_id)


def save_transcript(media_id: str, record: dict):
    data = load_transcripts()
    data[media_id] = record
    set_json(_TRANSCRIPTS_KEY, data)
