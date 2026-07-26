"""
Пункт E ТЗ — этап лестницы Ханта (Ben Hunt's Awareness Ladder) и "температура" зрителя
по транскрипту рилса. В отличие от hook_classifier.py (одно слово по короткому хуку),
здесь нужен весь текст ролика — стадию осознания и готовность купить нельзя понять
по первой фразе, это выводится из содержания целиком.

Честность превыше всего (см. общую философию проекта): если текста мало, он нерелевантен
(например, это не продающий контент, а мем без всякого отношения к продукту) или Claude
сам не уверен — возвращаем "не определено", а не гадаем. Заведомо ложная стадия хуже
отсутствия классификации: на неё будут опираться реальные решения о контент-стратегии.

Модель — Haiku: то же обоснование, что в hook_classifier.py (дешёвая классификация,
не открытая генерация).
"""
import json
import re

import anthropic

from app.i18n import t

MODEL_ID = "claude-haiku-4-5"
INPUT_PRICE_PER_MTOK = 1.0
OUTPUT_PRICE_PER_MTOK = 5.0

HUNT_STAGES = (
    "не осознаёт",
    "осознаёт проблему",
    "ищет решение",
    "выбирает",
    "покупает",
)
TEMPERATURES = ("холодная", "тёплая", "горячая")
UNDETERMINED = "не определено"

MIN_WORDS_FOR_CLASSIFICATION = 8

_REASONING_LANG_LABEL = {"ru": "по-русски", "uk": "українською"}

# Категории (stage/temperature) — канонические строки на русском независимо от языка
# интерфейса, см. HUNT_STAGES/TEMPERATURES ниже и app/static/js/app.js (HUNT_STAGE_KEYS/
# HUNT_TEMP_KEYS переводят их для показа). А вот "reasoning" — свободный текст от Claude,
# который показывается пользователю как есть, поэтому язык этого поля должен совпадать
# с языком интерфейса — иначе UK-режим всегда получал бы русское предложение.
def _build_system_prompt(lang: str) -> str:
    reasoning_lang = _REASONING_LANG_LABEL.get(lang, _REASONING_LANG_LABEL["ru"])
    return (
        "Ты анализируешь транскрипт короткого видео Reels и определяешь два параметра зрителя, "
        "на которого нацелен ролик, по лестнице осознанности Бена Ханта.\n\n"
        "СТАДИЯ (ровно одна из списка):\n"
        "не осознаёт — зритель не подозревает о проблеме или потребности, ролик развлекательный/образовательный без привязки к боли\n"
        "осознаёт проблему — ролик называет проблему/боль зрителя, но не предлагает решение\n"
        "ищет решение — ролик показывает, что решения существуют, сравнивает подходы, объясняет «как вообще решать»\n"
        "выбирает — ролик сравнивает конкретные продукты/бренды/варианты между собой, помогает выбрать\n"
        "покупает — ролик прямо продаёт: оффер, цена, призыв купить/записаться/оставить заявку\n\n"
        "ТЕМПЕРАТУРА (ровно одна из списка):\n"
        "холодная — зритель ещё не задумывался о покупке, чисто информационный контакт\n"
        "тёплая — зритель заинтересован темой, взаимодействует, но открытого призыва купить нет\n"
        "горячая — ролик явно подталкивает к действию прямо сейчас (заявка, покупка, запись)\n\n"
        "Если текста слишком мало, он не по теме продукта/услуги, или ты не уверен — "
        "честно верни \"не определено\" для соответствующего поля. Не выдумывай, если не хватает данных.\n\n"
        "Ответь СТРОГО в формате JSON одной строкой, без markdown и пояснений:\n"
        '{"stage": "...", "temperature": "...", "reasoning": "одно короткое предложение '
        + reasoning_lang + '"}'
    )


class HuntClassificationError(Exception):
    """Понятная причина, почему классификация не удалась — для UI."""


def _parse_response(raw_text: str) -> dict | None:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None

    stage = data.get("stage")
    temperature = data.get("temperature")
    reasoning = data.get("reasoning")

    stage = stage if stage in HUNT_STAGES else UNDETERMINED
    temperature = temperature if temperature in TEMPERATURES else UNDETERMINED

    return {"stage": stage, "temperature": temperature, "reasoning": reasoning or None}


def classify_hunt_stage(text: str, api_key: str, lang: str = "ru") -> dict:
    """
    Возвращает {"stage": ..., "temperature": ..., "reasoning": ...|None, "note": ...|None}.
    stage/temperature — либо честное значение из списка, либо UNDETERMINED.
    "note" объясняет ПОЧЕМУ не определено (нет ключа / мало текста / ошибка API / не распарсили ответ) —
    честность важнее красивого UI: пользователь должен понимать, что программа не выдумала данные.
    lang — язык интерфейса на момент транскрипции: определяет, на каком языке Claude напишет
    "reasoning" (свободный текст, в отличие от stage/temperature это не код, а видимый пользователю
    текст). Результат кэшируется вместе с транскриптом, поэтому смена языка позже не переведёт
    уже сохранённые reasoning задним числом — только новые транскрипции.
    """
    words = (text or "").split()
    if len(words) < MIN_WORDS_FOR_CLASSIFICATION:
        return {
            "stage": UNDETERMINED,
            "temperature": UNDETERMINED,
            "reasoning": None,
            "note": t("hunt.note.too_little_text", count=len(words), min_words=MIN_WORDS_FOR_CLASSIFICATION),
        }

    if not api_key:
        return {
            "stage": UNDETERMINED,
            "temperature": UNDETERMINED,
            "reasoning": None,
            "note": t("hunt.note.no_api_key"),
        }

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=200,
            system=_build_system_prompt(lang),
            messages=[{"role": "user", "content": text.strip()}],
        )
    except anthropic.APIError as e:
        return {
            "stage": UNDETERMINED,
            "temperature": UNDETERMINED,
            "reasoning": None,
            "note": t("hunt.note.api_error", error=e),
        }

    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    parsed = _parse_response(raw_text)
    if parsed is None:
        return {
            "stage": UNDETERMINED,
            "temperature": UNDETERMINED,
            "reasoning": None,
            "note": t("hunt.note.parse_failed"),
        }

    parsed["note"] = None
    return parsed


def estimate_cost_usd(input_tokens: int = 400, output_tokens: int = 60) -> float:
    """Грубая оценка стоимости одной классификации — для показа пользователю в UI."""
    return (input_tokens / 1_000_000) * INPUT_PRICE_PER_MTOK + (
        output_tokens / 1_000_000
    ) * OUTPUT_PRICE_PER_MTOK
