"""
"Напарник" — багатоходовий ШІ-чат, що відповідає на питання власника акаунта, спираючись
ТІЛЬКИ на реальний зібраний зріз даних (органіка, рубрики, активна реклама, вердикти
скриптів). На відміну від інших викликів Opus у проєкті (app/ads_opus.py — завжди один
user-меседж), тут ведеться справжня розмова: історія повідомлень передається клієнтом і
йде в messages[], а свіжий контекст даних збирається наново при КОЖНОМУ виклику і кладеться
в system — так відповідь завжди на актуальних цифрах, а не на знімку початку розмови.
"""
import anthropic

from app.ads_api import DEFAULT_PERIOD
from app.ads_opus import _lang_instruction
from app.ai_standard import HONESTY_AND_ACTION_RULES, VOLUME_HONESTY_RULES
from app.analysis import compute_organic_analysis
from app.categories import compute_category_stats
from app.daily_report import build_daily_report
from app.home_summary import build_home_summary
from app.routes.metrics import load_cache
from app.saved_scripts import load_saved_scripts
from app.transcription import load_transcripts

DEFAULT_MODEL = "claude-opus-4-8"
ALLOWED_MODELS = {
    "claude-opus-4-8": "Opus",
    "claude-sonnet-4-6": "Sonnet",
    "claude-haiku-4-5": "Haiku",
}

MAX_TOKENS = 700

COMPANION_SYSTEM_PROMPT = (
    "Ты — «Напарник», ИИ-ассистент владельца этого Instagram-аккаунта прямо в его дашборде. "
    "Тебе передан свежий срез реальных данных аккаунта: органическая статистика, топ/аутсайдеры "
    "рилсов, рубрики, активная реклама (кампании и отдельные объявления), вердикты по "
    "сгенерированным сценариям. Отвечай на вопросы пользователя, опираясь СТРОГО на эти данные.\n\n"
    + HONESTY_AND_ACTION_RULES + "\n\n"
    + VOLUME_HONESTY_RULES + "\n\n"
    "Правила формата ответа:\n"
    "- Отвечай конкретно и по цифрам: указывай реальные значения ER/охвата/цены результата и т.п. "
    "из данных, а не общие фразы вроде «попробуйте разные форматы».\n"
    "- Если пользователь спрашивает про КОНКРЕТНОЕ объявление (по названию) — бери цифры из "
    "раздела «ОТДЕЛЬНЫЕ ОБЪЯВЛЕНИЯ», а не из итога по кампании: у кампании обычно несколько "
    "объявлений, и сумма по кампании — не то же число, что у одного объявления. Это те же цифры, "
    "что видит пользователь на карточке объявления на вкладке «Реклама», за тот же период — "
    "всегда явно называй этот период в ответе, чтобы цифры не выглядели расхождением.\n"
    "- Коротко, без вступлений и воды. Формат — как советует опытный таргетолог/smm-менеджер "
    "коллеге, а не как маркетинговая статья.\n"
    "- Если пользователь просит конкретное действие («что снять сегодня», «что вырезать из "
    "рекламы») — дай прямую рекомендацию с обоснованием по цифрам, а не список вариантов на выбор."
)


def _fmt(value, suffix=""):
    if value is None:
        return "нет данных"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _reel_line(r: dict) -> str:
    caption = (r.get("caption") or "").strip() or "(без подписи)"
    return f"- «{caption[:70]}» ER {_fmt(r.get('engagement_rate'), '%')}, охват {_fmt(r.get('reach'))}"


def _content_section(content: dict) -> list:
    lines = ["=== ОРГАНИКА: сводка за последние 7 дней ==="]
    if not content.get("posts_count"):
        lines.append("Данных по органике за последние 7 дней нет (возможно, ещё не было синка).")
        return lines
    lines.append(
        f"Рилсов за период: {content['posts_count']}, суммарный охват {_fmt(content['reach_total'])}, "
        f"средний ER {_fmt(content['engagement_rate_avg'], '%')}, средний skip rate "
        f"{_fmt(content['skip_rate_avg'], '%')}"
    )
    top = content.get("top_reel")
    if top:
        lines.append(
            f"Топ-рилс периода: «{(top.get('caption') or '').strip()[:70]}» "
            f"ER {_fmt(top.get('engagement_rate'), '%')}, охват {_fmt(top.get('reach'))}"
        )
    return lines


def _winners_losers_section(organic: dict) -> list:
    lines = ["", "=== ТОП / АУТСАЙДЕРЫ РИЛСОВ (по всей собранной истории) ==="]
    if organic.get("insufficient_data"):
        lines.append("Недостаточно данных, чтобы посчитать топ/аутсайдеров.")
        return lines
    if organic.get("low_sample_warning"):
        lines.append(f"Внимание: маленькая выборка ({organic['dataset_size']} рилсов) — выводы делай осторожно.")
    lines.append("Лучшие по ER:")
    lines.extend(_reel_line(r) for r in (organic.get("top_er") or []))
    lines.append("Худшие по ER:")
    lines.extend(_reel_line(r) for r in (organic.get("bottom_er") or []))
    best_hour = organic.get("best_hour")
    if best_hour:
        lines.append(f"Лучшее время публикации: {best_hour['label']} (средний ER {best_hour['avg_er']}%, n={best_hour['count']})")
    best_weekday = organic.get("best_weekday")
    if best_weekday:
        lines.append(f"Лучший день недели: {best_weekday['label']} (средний ER {best_weekday['avg_er']}%, n={best_weekday['count']})")
    return lines


def _categories_section(cat_stats: list) -> list:
    lines = ["", "=== РУБРИКИ ==="]
    if not cat_stats:
        lines.append("Рубрики не настроены.")
        return lines
    for c in cat_stats:
        lines.append(
            f"- «{c['name']}»: {c['organic_count']} рилсов, средний ER {_fmt(c['avg_er'], '%')}, "
            f"saves rate {_fmt(c['avg_saves_rate'], '%')}"
        )
    return lines


def _scripts_verdicts_section(scripts: list) -> list:
    lines = ["", "=== ВЕРДИКТЫ СЦЕНАРИЕВ, ПРИВЯЗАННЫХ К ОПУБЛИКОВАННЫМ РИЛСАМ ==="]
    linked = [s for s in scripts if s.get("linked_media_id") and s.get("verdict")]
    if not linked:
        lines.append("Нет сценариев, привязанных к опубликованному рилсу с посчитанным вердиктом.")
        return lines
    for s in linked[:15]:
        topic = (s.get("topic") or "").strip()[:60] or "(без темы)"
        lines.append(f"- «{topic}»: {s['verdict']} — {s.get('verdict_reason') or 'нет обоснования'}")
    return lines


# Подписи периодов — та же лексика, что и в шапке карточки объявления (app/templates/ads.html,
# ключи i18n ads.period.*), но без t(), т.к. весь контекст для Opus в этом файле принципиально
# на русском независимо от языка интерфейса (см. _lang_instruction ниже — язык ОТВЕТА берётся
# из настроек отдельно, а не из этих строк).
_PERIOD_LABELS_RU = {
    "today": "сегодня",
    "last_7d": "7 дней",
    "last_14d": "14 дней",
    "last_30d": "30 дней",
    "maximum": "максимум (весь период кабинета)",
}


def _period_label(period: str) -> str:
    return _PERIOD_LABELS_RU.get(period, period)


def _ads_section(report: dict) -> list:
    period_label = _period_label(report.get("period") or DEFAULT_PERIOD)
    lines = ["", f"=== АКТИВНАЯ РЕКЛАМА (период: {period_label} — ТОТ ЖЕ период, что по умолчанию открыт на карточке объявления) ==="]
    if "error" in report:
        lines.append(f"Данные рекламы недоступны: {report['error']}")
        return lines
    campaigns = report.get("campaigns") or []
    if not campaigns:
        lines.append(report.get("note") or "Активных кампаний нет.")
        return lines
    lines.append(
        f"Кампаний: {report['totals']['campaigns_count']}, потрачено за период: {_fmt(report['totals'].get('spend'))}"
    )
    for c in campaigns:
        m = c.get("metrics") or {}
        r = c.get("result") or {}
        lines.append(
            f"- Кампания «{c['name']}» ({c.get('objective_label') or c.get('objective')}) — ИТОГО по всем "
            f"её объявлениям: расход {_fmt(m.get('spend'))}, показы {_fmt(m.get('impressions'))}, "
            f"результат {r.get('label') or 'нет данных'}="
            f"{_fmt(r.get('value'))}, цена результата {_fmt(r.get('cost_per_result'))}"
        )
        if c.get("verdicts"):
            v_txt = "; ".join(f"{v['metric']}: {v['verdict']}" for v in c["verdicts"])
            lines.append(f"  KPI: {v_txt}")

    lines.append("")
    lines.append(
        f"=== ОТДЕЛЬНЫЕ ОБЪЯВЛЕНИЯ (период: {period_label}, те же цифры, что покажет карточка "
        "объявления по умолчанию — по каждому объявлению отдельно, а не сумма по кампании) ==="
    )
    if report.get("ads_error"):
        lines.append(f"Данные по отдельным объявлениям частично недоступны: {report['ads_error']}")
    ads = report.get("ads") or []
    if not ads:
        lines.append("Нет отдельных объявлений с данными за этот период.")
    else:
        for ad in ads:
            m = ad.get("metrics") or {}
            r = ad.get("result") or {}
            lines.append(
                f"- «{ad['name']}» (кампания «{ad['campaign_name']}», {ad.get('objective_label') or ad.get('objective')}): "
                f"расход {_fmt(m.get('spend'))}, показы {_fmt(m.get('impressions'))}, "
                f"результат {r.get('label') or 'нет данных'}={_fmt(r.get('value'))}, "
                f"цена результата {_fmt(r.get('cost_per_result'))}"
            )
    return lines


def build_context_text() -> str:
    """Собирает свежий срез данных аккаунта в один читаемый текстовый блок для system-промпта.
    Вызывается заново на КАЖДЫЙ вопрос в чате (см. chat() ниже), а не один раз на всю беседу."""
    cache = load_cache()
    posts = cache.get("posts") or []
    transcripts = load_transcripts()

    home = build_home_summary()
    organic = compute_organic_analysis(posts)
    cat_stats = compute_category_stats(posts, transcripts)
    report = build_daily_report(period=DEFAULT_PERIOD, include_ads=True)
    scripts = load_saved_scripts()

    lines = []
    lines.extend(_content_section(home["content"]))
    lines.extend(_winners_losers_section(organic))
    lines.extend(_categories_section(cat_stats))
    lines.extend(_scripts_verdicts_section(scripts))
    lines.extend(_ads_section(report))
    return "\n".join(lines)


def chat(api_key: str, model: str, lang: str, history: list) -> str:
    """history — список {"role": "user"/"assistant", "content": str}, последний элемент —
    новый вопрос пользователя. Контекст данных собирается заново при каждом вызове."""
    system_prompt = (
        COMPANION_SYSTEM_PROMPT
        + "\n\n=== ДАННЫЕ АККАУНТА (собраны прямо сейчас) ===\n"
        + build_context_text()
        + "\n\n"
        + _lang_instruction(lang)
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=history,
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()
