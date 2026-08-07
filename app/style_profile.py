"""
Профиль стиля пользователя — считается из транскриптов его рилсов через Claude,
чтобы Генератор скриптов (Этап 3) писал ЕГО голосом, а не обобщённым нейтральным тоном.

Модель для профилирования — Sonnet (не Opus): это аналитическая задача, а не финальная
генерация скрипта под публикацию, экономим баланс на дорогой модели по просьбе пользователя.
"""
from datetime import datetime, timezone

import anthropic

from app.project_data_store import get_json, set_json

PROFILE_MODEL_ID = "claude-sonnet-4-6"

_KEY = "style_profile.json"

MAX_TRANSCRIPTS_FOR_PROFILE = 20
MAX_CHARS_PER_TRANSCRIPT = 1500
LOW_SAMPLE_THRESHOLD = 5

SYSTEM_PROMPT = (
    "Ты анализируешь набор транскриптов рилсов одного автора и извлекаешь профиль его "
    "речевого стиля — коротко, конкретно, без общих фраз, с примерами слов/выражений "
    "из самого текста. Верни ТОЛЬКО профиль строго в этом формате:\n\n"
    "ТОН: <общий тон — дружеский/агрессивный/ироничный/экспертный и т.п.>\n"
    "ЖЁСТКОСТЬ: <есть ли мат/грубая лексика, насколько часто, конкретные примеры из текста>\n"
    "ЭНЕРГИЯ: <темп — короткие рубленые фразы или длинные, много ли восклицаний>\n"
    "СЛЕНГ: <характерные словечки, обращения к зрителю, повторяющиеся выражения — с примерами>\n"
    "ДЛИНА ФРАЗ: <короткие/средние/длинные предложения, оценка>\n"
    "ОТКРЫТИЕ РИЛСОВ: <как обычно начинает — с вопроса, восклицания, обращения, факта>\n\n"
    "Не выдумывай то, чего нет в тексте. Если данных мало для какого-то пункта — так и напиши."
)


def load_style_profile():
    return get_json(_KEY, default=None)


def save_style_profile(profile: dict):
    set_json(_KEY, profile)


def compute_style_profile(transcripts: dict, posts: list, api_key: str) -> dict:
    """transcripts: media_id -> запись из transcripts.json. posts: посты из media_cache.json
    (нужны, чтобы исключить рекламные — реклама может писаться не голосом автора)."""
    ad_ids = {p["id"] for p in posts if p.get("is_ad")}

    usable = [
        (media_id, t)
        for media_id, t in transcripts.items()
        if media_id not in ad_ids and (t.get("text") or "").strip()
    ]

    if not usable:
        raise ValueError(
            "Нет ни одного органического транскрипта с текстом — сначала транскрибируйте "
            "рилсы на вкладке «Хук-анализ»."
        )

    usable = usable[:MAX_TRANSCRIPTS_FOR_PROFILE]

    blocks = []
    for i, (_media_id, t) in enumerate(usable, 1):
        text = (t.get("text") or "").strip()[:MAX_CHARS_PER_TRANSCRIPT]
        blocks.append(f"--- Рилс {i} ---\n{text}")
    combined = "\n\n".join(blocks)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=PROFILE_MODEL_ID,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": combined}],
    )
    profile_text = "".join(b.text for b in response.content if b.type == "text").strip()

    profile = {
        "profile_text": profile_text,
        "transcripts_used": len(usable),
        "model": PROFILE_MODEL_ID,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "low_sample_warning": len(usable) < LOW_SAMPLE_THRESHOLD,
    }
    save_style_profile(profile)
    return profile
