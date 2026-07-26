"""
Вкладка "Ідеї" (Фаза 3) — генерація 6-7 готових ідей контенту через Opus на реальних даних
акаунта. Переиспользует сборщики секций контекста из app/companion.py (те же топ/аутсайдеры,
рубрики, вердикты сценариев), добавляя нишу, профиль стиля и сырые подписи за последние
30 дней — по ним Opus сам оценивает баланс типов контента (личность/польза/проблема/пруфы),
жёсткой классификации на эти 4 типа в проекте нет и заводить её отдельным полем избыточно.

В отличие от companion.py (многоходовой чат, свободный текст) — это одноразовая генерация со
строгим JSON-ответом, тот же паттерн разбора, что в app/category_classifier.py.

Доработка (Фаза 3, доробка): раньше идеи были короткими одностроками ("hook"/"script"/"cta"),
без разбивки по слайдам для карусели и без развёрнутого сценария для Reels — и не сверялись с
тем, что пользователь уже решил снимать. Теперь:
- у идей формата «Карусель» — поле "slides" (текст каждого СРЕДНЕГО слайда, между хуком-слайдом 1
  и CTA-слайдом последним);
- у идей формата «Reels» — поле "script_steps" (пошаговый рабочий каркас сценария между хуком и
  CTA, а не одно общее предложение);
- в контекст добавлена секция _content_plan_section() — темы из уже сохранённых сценариев
  (app/saved_scripts.py, ВСЕ, а не только привязанные к опубликованному рилсу — в отличие от
  companion.py:_scripts_verdicts_section, который фильтрует по вердикту) и уже сохранённых идей
  (app/ideas_bank.py) — это ближайший аналог "контент-плана" в проекте (отдельной сущности
  "контент-план" как таковой нет), и Opus прямо просят не дублировать эти темы/хуки.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import anthropic

from app.ads_opus import _lang_instruction
from app.ai_standard import HONESTY_AND_ACTION_RULES
from app.analysis import compute_organic_analysis
from app.categories import compute_category_stats, load_categories
from app.companion import (
    _categories_section,
    _content_section,
    _scripts_verdicts_section,
    _winners_losers_section,
)
from app.project_store import get_effective_config
from app.home_summary import build_home_summary
from app.i18n import t
from app.ideas_bank import load_ideas_bank
from app.routes.metrics import load_cache
from app.saved_scripts import load_saved_scripts
from app.style_profile import load_style_profile
from app.transcription import load_transcripts

DEFAULT_MODEL = "claude-opus-4-8"
ALLOWED_MODELS = {
    "claude-opus-4-8": "Opus",
    "claude-sonnet-4-6": "Sonnet",
    "claude-haiku-4-5": "Haiku",
}

# Было 3000 — с развёрнутыми slides/script_steps на 6-7 идей текст стал заметно длиннее, чем
# прежние однострочники, и 3000 токенов стало не хватать (ответ обрезался посреди JSON).
MAX_TOKENS = 4500
RECENT_DAYS = 30
MAX_RECENT_LINES = 40
MAX_PLAN_ITEMS = 40

IDEAS_SYSTEM_PROMPT = (
    "Ты — контент-стратег и сценарист Reels, работающий с конкретным Instagram-аккаунтом. Тебе "
    "передан свежий срез реальных данных аккаунта: нишу, профиль стиля автора (если посчитан), "
    "органическую статистику, топ/аутсайдеры рилсов, эффективность рубрик, вердикты по сценариям, "
    "привязанным к опубликованным рилсам, темы из уже сохранённых сценариев и банка идей "
    "(контент-план — что уже решено снимать), и подписи рилсов за последние 30 дней. На основе "
    "этих данных сгенерируй РОВНО 6 или 7 конкретных идей контента — что снять ПРЯМО СЕЙЧАС.\n\n"
    + HONESTY_AND_ACTION_RULES + "\n\n"
    "Правила по формату идей:\n"
    "- Ровно 6 или 7 идей — не меньше и не больше, стабильное количество при каждом запуске.\n"
    "- Каждая идея должна опираться на реальные переданные данные, а не быть абстрактным "
    "маркетинговым советом. В поле \"why\" явно укажи, на какие данные опираешься (например: "
    "«твой топ-рилс был про X с ER Y% — развиваем эту тему» или «рубрика Z даёт лучший ER — нужно "
    "больше контента в ней»).\n"
    "- Если в разделе «УЖЕ Є В КОНТЕНТ-ПЛАНІ / БАНКУ ІДЕЙ» есть тема или хук, по сути совпадающий "
    "с твоей идеей — НЕ предлагай её повторно, придумай другой ракурс, угол или тему. Это "
    "обязательное правило, а не пожелание.\n"
    "- \"hook\" — конкретный текст первых 3 секунд ролика (формат «Reels») или текст ПЕРВОГО "
    "слайда (формат «Карусель»), а не абстракция вроде «зацепляющий вопрос».\n"
    "- \"cta\" — конкретный текст финального призыва к действию (формат «Reels») или текст "
    "ПОСЛЕДНЕГО слайда (формат «Карусель»).\n"
    "- Если \"format\" = «Reels»: заполни \"script_steps\" — массив из 3-5 строк, конкретный "
    "рабочий каркас сценария МЕЖДУ хуком и CTA (что именно показываем/говорим на каждом шаге по "
    "порядку раскрытия темы) — НЕ одно общее предложение, а рабочий каркас, по которому реально "
    "можно снимать. Поле \"slides\" в этом случае оставь пустым массивом [].\n"
    "- Если \"format\" = «Карусель»: заполни \"slides\" — массив из 3-4 строк, конкретный ГОТОВЫЙ "
    "ТЕКСТ каждого среднего слайда (между хуком-слайдом 1 и CTA-слайдом последним) — то есть при "
    "4 элементах в массиве получится карусель на 6 слайдов всего (1 хук + 4 контент + 1 CTA). "
    "Поле \"script_steps\" в этом случае оставь пустым массивом [].\n"
    "- По подписям рилсов за последние 30 дней оцени баланс типов контента: личность/личные "
    "истории автора, польза/советы, проблема/боль аудитории, пруфы/результаты/кейсы. Если виден "
    "явный перекос в одну сторону — включи в идеи то, чего не хватает, и прямо скажи об этом в "
    "\"why\". Если по подписям баланс оценить нельзя (мало данных) — не выдумывай перекос.\n"
    "- Не повторяй паттерны аутсайдеров (что не зашло).\n"
    "- \"format\" — «Reels» или «Карусель», выбирай осмысленно под содержание идеи, не только "
    "Reels.\n\n"
    "Ответь СТРОГО в виде JSON без markdown-разметки и без пояснений от себя, в формате:\n"
    '{"ideas": [{"format": "...", "rubric": "...", "audience_segment": "...", "hook": "...", '
    '"script_steps": ["...", "..."], "slides": ["...", "..."], "cta": "...", "why": "..."}]}'
)


def _niche_section(niche: str) -> list:
    lines = ["", "=== НИША АККАУНТА ==="]
    lines.append(niche or "Ниша не указана в Настройках.")
    return lines


def _style_section(style_profile) -> list:
    lines = ["", "=== ПРОФИЛЬ СТИЛЯ АВТОРА ==="]
    if not style_profile:
        lines.append(
            "Профиль стиля ещё не посчитан (вкладка «Генератор») — пиши хуки в живом "
            "разговорном тоне, без канцелярита."
        )
        return lines
    lines.append(style_profile.get("profile_text") or "нет данных")
    return lines


def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _recent_content_section(posts: list, categories_data: dict) -> list:
    """Подписи органических рилсов за последние RECENT_DAYS дней с привязанной рубрикой (если
    есть) — сырой материал, по которому Opus сам оценивает баланс типов контента, а не жёсткая
    заранее посчитанная классификация, которой в проекте нет."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    assignments = categories_data.get("assignments") or {}
    cat_names = {c["id"]: c["name"] for c in categories_data.get("categories") or []}

    recent = []
    for p in posts:
        if p.get("is_ad") or p.get("media_product_type") != "REELS":
            continue
        dt = _parse_ts(p.get("timestamp"))
        if not dt or dt < cutoff:
            continue
        recent.append(p)
    recent.sort(key=lambda p: p.get("timestamp") or "", reverse=True)

    lines = ["", f"=== ПОДПИСИ ОРГАНИЧЕСКИХ РИЛСОВ ЗА ПОСЛЕДНИЕ {RECENT_DAYS} ДНЕЙ (для оценки баланса типов контента) ==="]
    if not recent:
        lines.append("За этот период органических рилсов нет.")
        return lines

    for p in recent[:MAX_RECENT_LINES]:
        caption = (p.get("caption") or "").strip().replace("\n", " ")[:150] or "(без подписи)"
        cat_id = assignments.get(p["id"])
        cat_name = cat_names.get(cat_id) if cat_id else None
        rubric_tag = f" [рубрика: {cat_name}]" if cat_name else ""
        lines.append(f"- «{caption}»{rubric_tag}")
    if len(recent) > MAX_RECENT_LINES:
        lines.append(f"...и ещё {len(recent) - MAX_RECENT_LINES} рилсов за этот период.")
    return lines


def _content_plan_section(scripts: list, bank_ideas: list) -> list:
    """Темы/хуки, которые уже "решены" — лежат в сохранённых сценариях (ВСЕ, а не только
    привязанные к опубликованному рилсу, в отличие от _scripts_verdicts_section выше) и в банке
    идей. Ближайший аналог "контент-плана" в проекте: отдельной сущности для него нет, но именно
    эти два места — то, что пользователь уже решил снимать. Честно говорим Opus, если и то,
    и другое пусто — "подключать" в проекте нечего, звериться не с чем."""
    lines = ["", "=== УЖЕ Є В КОНТЕНТ-ПЛАНІ / БАНКУ ІДЕЙ (НЕ пропонуй ідеї, що по суті дублюють ці теми/хуки) ==="]

    items = []
    for s in scripts:
        topic = (s.get("topic") or "").strip()
        if topic:
            items.append(topic)
    for idea in bank_ideas:
        hook = (idea.get("hook") or "").strip()
        if hook:
            items.append(hook)

    if not items:
        lines.append("Контент-план і банк ідей поки порожні — звірятись немає з чим.")
        return lines

    for item in items[:MAX_PLAN_ITEMS]:
        lines.append(f"- {item}")
    if len(items) > MAX_PLAN_ITEMS:
        lines.append(f"...і ще {len(items) - MAX_PLAN_ITEMS} тем.")
    return lines


def build_context_text() -> str:
    cfg = get_effective_config()
    niche = (cfg.get("account_niche") or "").strip()
    style_profile = load_style_profile()

    cache = load_cache()
    posts = cache.get("posts") or []
    transcripts = load_transcripts()

    home = build_home_summary()
    organic = compute_organic_analysis(posts)
    categories_data = load_categories()
    cat_stats = compute_category_stats(posts, transcripts)
    scripts = load_saved_scripts()
    bank_ideas = load_ideas_bank()

    lines = []
    lines.extend(_niche_section(niche))
    lines.extend(_style_section(style_profile))
    lines.extend(_content_section(home["content"]))
    lines.extend(_winners_losers_section(organic))
    lines.extend(_categories_section(cat_stats))
    lines.extend(_scripts_verdicts_section(scripts))
    lines.extend(_content_plan_section(scripts, bank_ideas))
    lines.extend(_recent_content_section(posts, categories_data))
    return "\n".join(lines)


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
            raise ValueError(t("ideas.msg.parse_error"))
        return json.loads(m.group(0))


def _sanitize_str_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [s for s in (str(v).strip() for v in value) if s]


def _sanitize_idea(item: dict):
    hook = (item.get("hook") or "").strip()
    # "script" — старое поле, оставляем разбор из бэкап-совместимости на случай, если модель
    # всё же вернёт его вместо script_steps/slides (например, старый закешированный ответ).
    script = (item.get("script") or "").strip()
    script_steps = _sanitize_str_list(item.get("script_steps"))
    slides = _sanitize_str_list(item.get("slides"))
    if not hook and not script and not script_steps and not slides:
        return None
    return {
        "format": (item.get("format") or "").strip() or None,
        "rubric": (item.get("rubric") or "").strip() or None,
        "audience_segment": (item.get("audience_segment") or "").strip() or None,
        "hook": hook or None,
        "script": script or None,
        "script_steps": script_steps,
        "slides": slides,
        "cta": (item.get("cta") or "").strip() or None,
        "why": (item.get("why") or "").strip() or None,
    }


def generate_ideas(api_key: str, model: str, lang: str) -> dict:
    system_prompt = (
        IDEAS_SYSTEM_PROMPT
        + "\n\n=== ДАННЫЕ АККАУНТА ===\n"
        + build_context_text()
        + "\n\n"
        + _lang_instruction(lang)
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": "Сгенерируй идеи контента."}],
    )
    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    parsed = _parse_json(raw_text)

    ideas = [i for i in (_sanitize_idea(item) for item in (parsed.get("ideas") or [])) if i]
    if not ideas:
        raise ValueError(t("ideas.msg.parse_error"))
    # Промпт просит ровно 6-7, но не полагаемся на модель на 100% — верхнюю границу подрезаем
    # сами, чтобы "стабильно 6-7" не съехало на 9-10 при перегенерации.
    ideas = ideas[:7]

    return {"ideas": ideas, "model": model}
