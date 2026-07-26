"""
Генератор скриптов рилсов в стиле конкретного пользователя. Строит промпт из трёх
источников данных пользователя: профиля стиля (app/style_profile.py), топ-рилсов (winners)
и худших рилсов (losers) — и просит Claude писать в этом голосе, а не обобщённо.
"""
import re

import anthropic

from app.ai_standard import HONESTY_AND_ACTION_RULES
from app.i18n import t

MODEL_INFO = {
    "opus": {
        "id": "claude-opus-4-8",
        "label": "Opus",
        "description": (
            "Максимальное качество. Самые сильные, живые скрипты, лучше держит стиль и логику. "
            "Самый дорогой — баланс тратится быстрее. Для финальных скриптов под публикацию."
        ),
        "input_price_per_mtok": 5.0,
        "output_price_per_mtok": 25.0,
    },
    "sonnet": {
        "id": "claude-sonnet-4-6",
        "label": "Sonnet",
        "description": "Почти как Opus, но дешевле и быстрее. Золотая середина для повседневной генерации.",
        "input_price_per_mtok": 3.0,
        "output_price_per_mtok": 15.0,
    },
    "haiku": {
        "id": "claude-haiku-4-5",
        "label": "Haiku",
        "description": (
            "Самая быстрая и дешёвая, качество ниже. Для черновиков и массовой классификации хуков. "
            "Максимальная экономия."
        ),
        "input_price_per_mtok": 1.0,
        "output_price_per_mtok": 5.0,
    },
}
MODEL_CHOICES = {key: info["id"] for key, info in MODEL_INFO.items()}
DEFAULT_MODEL_KEY = "opus"

HOOK_TYPES = ("вопрос", "боль", "провокация", "цифра", "утверждение")

FORMAT_CHOICES = ("reels", "carousel")
DEFAULT_FORMAT = "reels"


def select_winners_losers(posts: list, transcripts: dict, max_each: int = 3, allowed_media_ids: set = None):
    """Топ и худшие органические Reels по ER среди тех, что уже транскрибированы —
    нужны и метрики, и реальный текст хука, иначе нечего анализировать.
    allowed_media_ids — если задано (выбрана рубрика), ограничивает выборку только
    рилсами этой рубрики, чтобы winner-паттерны были специфичны для темы."""
    ad_ids = {p["id"] for p in posts if p.get("is_ad")}

    candidates = []
    for p in posts:
        if p.get("media_product_type") != "REELS":
            continue
        if p["id"] in ad_ids:
            continue
        if allowed_media_ids is not None and p["id"] not in allowed_media_ids:
            continue
        if p.get("insights_status") != "ok" or p.get("engagement_rate") is None:
            continue
        t = transcripts.get(p["id"])
        if not t or not ((t.get("hook_text") or "").strip() or (t.get("text") or "").strip()):
            continue
        candidates.append(
            {
                "id": p["id"],
                "caption": p.get("caption", ""),
                "permalink": p.get("permalink"),
                "engagement_rate": p["engagement_rate"],
                "saved": p.get("saved"),
                "hook_text": t.get("hook_text") or "",
                "hook_type": t.get("hook_type"),
            }
        )

    candidates.sort(key=lambda c: c["engagement_rate"], reverse=True)
    n = len(candidates)
    if n == 0:
        return [], [], 0
    if n == 1:
        return candidates, [], n

    pick = min(max_each, n // 2)
    winners = candidates[:pick]
    losers = list(reversed(candidates[-pick:]))
    return winners, losers, n


def _zero_saves(posts: list) -> bool:
    organic = [
        p
        for p in posts
        if p.get("media_product_type") == "REELS" and not p.get("is_ad") and p.get("insights_status") == "ok"
    ]
    if not organic:
        return False
    return all((p.get("saved") or 0) == 0 for p in organic)


def _format_examples(items: list, label: str) -> str:
    if not items:
        return f"{label}: данных пока нет."
    lines = [f"{label}:"]
    for it in items:
        hook = it.get("hook_text") or "(без речи/не распознано)"
        er = it.get("engagement_rate")
        er_text = f"{er}%" if er is not None else "?"
        source_tag = " [ваш опубликованный сгенерированный скрипт]" if it.get("source") == "generated" else ""
        lines.append(f'- ER {er_text}, тип хука "{it.get("hook_type") or "?"}": "{hook}"{source_tag}')
    return "\n".join(lines)


def _generated_feedback_examples(saved_scripts: list, posts: list, exclude_ids: set, category_id: str = None):
    """Опубликованные скрипты с вычисленным вердиктом становятся дополнительными
    примерами winner/loser — генератор учится на реальных результатах публикаций,
    а не только на органическом анализе. Берём текст хука из самой генерации
    (он точнее, чем повторная транскрипция опубликованного видео).
    Если выбрана рубрика — учитываем только скрипты, сгенерированные для этой же рубрики."""
    posts_by_id = {p["id"]: p for p in posts}
    gen_winners, gen_losers = [], []

    for s in saved_scripts:
        media_id = s.get("linked_media_id")
        verdict = s.get("verdict")
        if not media_id or not verdict or media_id in exclude_ids:
            continue
        if category_id is not None and s.get("category_id") != category_id:
            continue
        post = posts_by_id.get(media_id)
        hook_text = (s.get("script") or {}).get("hook") or s.get("topic") or ""
        item = {
            "id": media_id,
            "engagement_rate": post.get("engagement_rate") if post else None,
            "hook_text": hook_text,
            "hook_type": s.get("hook_type_pref"),
            "source": "generated",
        }
        # "зашло"/"не зашло" — легаси-значения verdict, сохранённые до перехода на коды
        # good/bad/neutral (см. app/script_verdict.py); saved_scripts.json может ещё
        # содержать старые записи, которые не проходят через normalize_verdict().
        if verdict in ("good", "зашло"):
            gen_winners.append(item)
        elif verdict in ("bad", "не зашло"):
            gen_losers.append(item)

    return gen_winners, gen_losers


def build_generation_prompt(
    topic: str,
    hook_type_pref: str,
    style_profile: dict,
    winners: list,
    losers: list,
    clean_for_ads: bool,
    zero_saves: bool,
    category_name: str = None,
    niche: str = "",
    sample_size: int = 0,
    format_: str = DEFAULT_FORMAT,
):
    is_carousel = format_ == "carousel"

    style_text = (
        style_profile["profile_text"]
        if style_profile
        else "Профиль стиля ещё не посчитан — пиши в живом разговорном тоне для контента о SMM/маркетинге, без канцелярита."
    )

    niche_block = f"НИША АККАУНТА:\n{niche or 'не указана в Настройках'}\n\n"

    winners_label = "ТОП-РИЛСЫ ПОЛЬЗОВАТЕЛЯ (что зашло — повторяй паттерн хука/подачи)"
    losers_label = "ХУДШИЕ РИЛСЫ ПОЛЬЗОВАТЕЛЯ (что флопнуло — НЕ повторяй этот паттерн)"
    if category_name:
        winners_label += f", рубрика «{category_name}»"
        losers_label += f", рубрика «{category_name}»"

    winners_block = _format_examples(winners, winners_label)
    losers_block = _format_examples(losers, losers_label)

    category_block = f"РУБРИКА КОНТЕНТА: «{category_name}» — пиши в рамках этой тематической серии.\n\n" if category_name else ""

    low_sample_notes = []
    if sample_size < 6:
        low_sample_notes.append(
            f"Примеров пока мало ({sample_size}) — не изображай уверенность в паттерне/стиле, "
            "которой нет. Опирайся больше на нишу и общие принципы хорошего Reels-хука, чем на "
            "статистику по этим нескольким примерам."
        )
    if style_profile and style_profile.get("low_sample_warning"):
        low_sample_notes.append(
            "Профиль стиля посчитан по маленькой выборке транскриптов — не копируй его буквально "
            "как железное правило, используй как ориентир тона."
        )
    low_sample_block = ("\n".join(low_sample_notes) + "\n\n") if low_sample_notes else ""

    constraints = []
    if hook_type_pref:
        constraints.append(f"Тип хука для этого скрипта: {hook_type_pref}.")
    if clean_for_ads:
        constraints.append(
            "ЧИСТАЯ ВЕРСИЯ ДЛЯ РЕКЛАМЫ: никакого мата и грубой лексики — контент должен пройти модерацию Meta Ads."
        )
    if zero_saves:
        constraints.append(
            "У пользователя ноль сохранений на органических рилсах. Если тема позволяет — "
            'заверни CTA как прямой призыв сохранить видео ("сохрани, чтобы не потерять" и т.п.), '
            "но только если это естественно ложится в контекст, не притягивай силой."
        )

    constraints_block = ("\n".join(constraints) + "\n\n") if constraints else ""

    if is_carousel:
        intro = (
            "Ты пишешь сценарий карусели (пост из нескольких слайдов) для конкретного автора, "
            "используя ЕГО реальный стиль и данные о том, что у него уже сработало и что провалилось "
            "в Reels (паттерны хука и подачи переносятся и на первый слайд карусели). Пиши так, будто "
            "ты этот автор — не пиши обобщённый нейтральный контент.\n\n"
        )
        hook_requirement = "- Хук — текст ПЕРВОГО слайда карусели, должен цеплять с первой фразы, без разгона и предисловий.\n"
        extra_requirement = (
            "- Слайды между хуком и CTA (от 2 до 4 слайдов) — конкретное поэтапное раскрытие темы: "
            "каждый слайд — самостоятельная законченная мысль с конкретикой (цифры, примеры, шаги), "
            "без воды и без повторов между слайдами.\n"
        )
        output_format = (
            "- Ответь СТРОГО в этом формате, без markdown-разметки и без пояснений от себя:\n"
            "ХУК: <текст слайда 1 — хук>\n"
            "СЛАЙД: <текст слайда 2 — раскрытие темы>\n"
            "СЛАЙД: <текст следующего слайда>\n"
            "(строк «СЛАЙД:» должно быть от 2 до 4 — по одной на каждый средний слайд)\n"
            "CTA: <текст последнего слайда — призыв к действию>\n"
            "ЧОМУ: <1 предложение — на какой реальный паттерн из топ-рилсов/ниши опирается этот хук/структура>"
        )
    else:
        intro = (
            "Ты пишешь сценарий рилса для конкретного автора, используя ЕГО реальный стиль и данные о "
            "том, что у него уже сработало и что провалилось. Пиши так, будто ты этот автор — не пиши "
            "обобщённый нейтральный контент.\n\n"
        )
        hook_requirement = "- Хук — первые 3 секунды, должен цеплять с первой фразы, без разгона и предисловий.\n"
        extra_requirement = ""
        output_format = (
            "- Ответь СТРОГО в этом формате, без markdown-разметки и без пояснений от себя:\n"
            "ХУК: <текст хука>\n"
            "ТЕЛО: <основной текст>\n"
            "CTA: <призыв к действию>\n"
            "ЧОМУ: <1 предложение — на какой реальный паттерн из топ-рилсов/ниши опирается этот хук/структура>"
        )

    system_prompt = (
        intro
        + f"{niche_block}"
        + f"ПРОФИЛЬ СТИЛЯ АВТОРА:\n{style_text}\n\n"
        + f"{category_block}"
        + f"{winners_block}\n\n"
        + f"{losers_block}\n\n"
        + f"{low_sample_block}"
        + f"{constraints_block}"
        + "ЖЁСТКИЕ ТРЕБОВАНИЯ К ВЫХОДУ:\n"
        + "- Никаких банальных вводных вроде «В этом видео я расскажу» или «Сегодня поговорим о».\n"
        + "- Конкретика: цифры, примеры, чёткие формулировки — без общих слов ни о чём.\n"
        + hook_requirement
        + extra_requirement
        + "- Пиши в стиле автора из профиля выше (тон, жёсткость, характерные словечки), а не нейтрально.\n\n"
        + HONESTY_AND_ACTION_RULES + "\n\n"
        + output_format
    )

    user_message = f"Тема {'карусели' if is_carousel else 'рилса'}: {topic}"
    return system_prompt, user_message


def parse_script_response(text: str) -> dict:
    m_hook = re.search(r"ХУК:\s*(.+?)(?=\n(?:ТЕЛО|CTA|ЧОМУ):|\Z)", text, re.S)
    m_body = re.search(r"ТЕЛО:\s*(.+?)(?=\n(?:CTA|ЧОМУ):|\Z)", text, re.S)
    m_cta = re.search(r"CTA:\s*(.+?)(?=\nЧОМУ:|\Z)", text, re.S)
    m_why = re.search(r"ЧОМУ:\s*(.+)", text, re.S)

    hook = m_hook.group(1).strip() if m_hook else None
    body = m_body.group(1).strip() if m_body else None
    cta = m_cta.group(1).strip() if m_cta else None
    why = m_why.group(1).strip() if m_why else None

    if not (hook or body or cta):
        return {"hook": None, "body": text.strip(), "cta": None, "why": None}
    return {"hook": hook, "body": body, "cta": cta, "why": why}


def parse_carousel_response(text: str) -> dict:
    m_hook = re.search(r"ХУК:\s*(.+?)(?=\nСЛАЙД:|\nCTA:|\nЧОМУ:|\Z)", text, re.S)
    slides = re.findall(r"СЛАЙД:\s*(.+?)(?=\nСЛАЙД:|\nCTA:|\nЧОМУ:|\Z)", text, re.S)
    m_cta = re.search(r"CTA:\s*(.+?)(?=\nЧОМУ:|\Z)", text, re.S)
    m_why = re.search(r"ЧОМУ:\s*(.+)", text, re.S)

    hook = m_hook.group(1).strip() if m_hook else None
    slides = [s.strip() for s in slides if s.strip()]
    cta = m_cta.group(1).strip() if m_cta else None
    why = m_why.group(1).strip() if m_why else None

    if not (hook or slides or cta):
        return {"hook": None, "slides": [], "cta": None, "why": None}
    return {"hook": hook, "slides": slides, "cta": cta, "why": why}


def _build_notes(winners: list, losers: list, sample_size: int, category_name: str = None) -> list:
    notes = []
    if category_name and not winners and not losers:
        notes.append(t("generator.note.category_no_data", category=category_name))
    if winners:
        w = winners[0]
        er_text = f'{w["engagement_rate"]}%' if w.get("engagement_rate") is not None else "?"
        source = t("generator.note.source_generated_good") if w.get("source") == "generated" else ""
        notes.append(t(
            "generator.note.winner_pattern",
            er=er_text, hook_type=w.get("hook_type") or "?", source=source, hook_text=(w.get("hook_text") or "")[:80],
        ))
    if losers:
        l = losers[0]
        er_text = f'{l["engagement_rate"]}%' if l.get("engagement_rate") is not None else "?"
        source = t("generator.note.source_generated_bad") if l.get("source") == "generated" else ""
        notes.append(t(
            "generator.note.loser_pattern",
            er=er_text, hook_type=l.get("hook_type") or "?", source=source, hook_text=(l.get("hook_text") or "")[:80],
        ))
    if sample_size < 6:
        notes.append(t("generator.note.small_sample", n=sample_size))
    return notes


def estimate_cost_usd(model_key: str, input_tokens: int = 1200, output_tokens: int = 400) -> float:
    info = MODEL_INFO.get(model_key, MODEL_INFO[DEFAULT_MODEL_KEY])
    return (input_tokens / 1_000_000) * info["input_price_per_mtok"] + (
        output_tokens / 1_000_000
    ) * info["output_price_per_mtok"]


def generate_script(
    topic: str,
    hook_type_pref: str,
    model_key: str,
    clean_for_ads: bool,
    api_key: str,
    posts: list,
    transcripts: dict,
    style_profile: dict,
    saved_scripts: list = None,
    category_id: str = None,
    category_name: str = None,
    category_assignments: dict = None,
    niche: str = "",
    format_: str = DEFAULT_FORMAT,
) -> dict:
    if model_key not in MODEL_CHOICES:
        model_key = DEFAULT_MODEL_KEY
    model_id = MODEL_CHOICES[model_key]
    if format_ not in FORMAT_CHOICES:
        format_ = DEFAULT_FORMAT

    allowed_media_ids = None
    if category_id and category_assignments is not None:
        allowed_media_ids = {mid for mid, cid in category_assignments.items() if cid == category_id}

    winners, losers, sample_size = select_winners_losers(
        posts, transcripts, allowed_media_ids=allowed_media_ids
    )

    exclude_ids = {w["id"] for w in winners} | {l["id"] for l in losers}
    gen_winners, gen_losers = _generated_feedback_examples(
        saved_scripts or [], posts, exclude_ids, category_id=category_id
    )
    winners = (winners + gen_winners)[:4]
    losers = (losers + gen_losers)[:4]
    sample_size += len(gen_winners) + len(gen_losers)

    zero_saves = _zero_saves(posts)

    system_prompt, user_message = build_generation_prompt(
        topic, hook_type_pref, style_profile, winners, losers, clean_for_ads, zero_saves, category_name,
        niche=niche, sample_size=sample_size, format_=format_,
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_id,
        # Карусель отвечает 2-4 слайдами вместо одного блока ТЕЛО — нужен запас токенов побольше.
        max_tokens=900 if format_ == "carousel" else 700,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    script = parse_carousel_response(raw_text) if format_ == "carousel" else parse_script_response(raw_text)

    return {
        "script": script,
        "raw_text": raw_text,
        "category_id": category_id,
        "category_name": category_name,
        "notes": _build_notes(winners, losers, sample_size, category_name),
        "model_key": model_key,
        "model_id": model_id,
        "format": format_,
        "sample_size": sample_size,
        "clean_for_ads": clean_for_ads,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
