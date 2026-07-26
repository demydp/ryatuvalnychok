"""
Авто-определение рубрик (тематических серий контента) через Claude: анализирует подписи
и транскрипты органических рилсов и группирует их в тематические кластеры.

Модель — Sonnet (не Haiku): это содержательная кластеризация и придумывание осмысленных
коротких названий тем, а не классификация в одну из готовых категорий — как и в профиле
стиля (app/style_profile.py), экономим на Opus, но не на Haiku, где качества не хватит.
"""
import json
import re

import anthropic

from app.i18n import t

MODEL_ID = "claude-sonnet-4-6"
MAX_REELS = 80
MAX_CAPTION_CHARS = 200
MAX_TRANSCRIPT_CHARS = 300

SYSTEM_PROMPT = (
    "Ты анализируешь список рилсов одного автора (подпись и, если есть, транскрипт/хук) и "
    "группируешь их в тематические рубрики — серии контента по смыслу, например «лайфхаки», "
    "«личные истории», «разбор мифов», «про заработок». Категории определяй ИЗ РЕАЛЬНОГО "
    "содержания списка, не подгоняй под примеры выше, если они не подходят.\n\n"
    "Правила:\n"
    "- От 3 до 8 рубрик. Название рубрики — 2-4 слова, на русском, конкретное и понятное.\n"
    "- Каждый рилс попадает РОВНО в одну рубрику.\n"
    "- Если рилс не подходит ни под одну содержательную тему — помести его в рубрику «Разное».\n"
    "- Используй все id из списка, ничего не пропускай и не выдумывай новых id.\n\n"
    "Ответь СТРОГО в виде JSON без markdown-разметки и без пояснений, в формате:\n"
    '{"categories": [{"name": "...", "media_ids": ["id1", "id2"]}]}'
)


def _build_reel_lines(posts: list, transcripts: dict) -> list:
    lines = []
    for p in posts:
        t = transcripts.get(p["id"]) or {}
        caption = (p.get("caption") or "").strip().replace("\n", " ")[:MAX_CAPTION_CHARS]
        text = (t.get("text") or t.get("hook_text") or "").strip().replace("\n", " ")[:MAX_TRANSCRIPT_CHARS]
        parts = [f'id={p["id"]}']
        if caption:
            parts.append(f'подпись: "{caption}"')
        if text:
            parts.append(f'текст: "{text}"')
        if len(parts) == 1:
            continue  # ни подписи, ни транскрипта — нечего анализировать
        lines.append(" | ".join(parts))
    return lines


def detect_categories(posts: list, transcripts: dict, api_key: str) -> dict:
    organic_reels = [p for p in posts if p.get("media_product_type") == "REELS" and not p.get("is_ad")]
    lines = _build_reel_lines(organic_reels, transcripts)
    if not lines:
        raise ValueError(t("categories.msg.no_data_to_analyze"))

    truncated = len(lines) > MAX_REELS
    lines = lines[:MAX_REELS]
    user_message = "Рилсы:\n" + "\n".join(lines)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    parsed = _parse_json(raw_text)

    categories = []
    assignments = {}
    for cat in parsed.get("categories") or []:
        name = (cat.get("name") or "").strip()
        media_ids = cat.get("media_ids") or []
        if not name or not media_ids:
            continue
        categories.append({"name": name})
        for mid in media_ids:
            assignments[mid] = name

    if not categories:
        raise ValueError(t("categories.msg.claude_no_categories"))

    return {
        "categories": categories,
        "assignments": assignments,
        "model": MODEL_ID,
        "analyzed_count": len(lines),
        "truncated": truncated,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(t("categories.msg.claude_parse_error"))
        return json.loads(m.group(0))


def estimate_cost_usd(input_tokens: int = 3000, output_tokens: int = 800) -> float:
    return (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
