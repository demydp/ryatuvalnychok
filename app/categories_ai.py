"""
AI-висновок для вкладки "Рубрики" — той самий контракт, що вже працює в app/ideas.py /
app/companion.py / app/hooks_ai.py / app/insights_ai.py: реальний контекст (ніша, стиль, вже
порахована статистика compute_category_stats()), чесність щодо малої вибірки, причинно-
наслідкове пояснення і дія. app/categories.py лишається чистою статистикою (та одноразовою
класифікацією назв через app/category_classifier.py) — цей модуль лише СПОЖИВАЄ порахований
результат.
"""
from app.ads_opus import _lang_instruction, call_opus
from app.ai_standard import HONESTY_AND_ACTION_RULES
from app.project_store import get_effective_config
from app.style_profile import load_style_profile

MAX_TOKENS = 600
LOW_SAMPLE_THRESHOLD = 8


def _niche_section(niche: str) -> str:
    return "=== НИША АККАУНТА ===\n" + (niche or "Ниша не указана в Настройках.")


def _style_section(style_profile) -> str:
    if not style_profile:
        return (
            "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n"
            "Профиль стиля ещё не посчитан (вкладка «Генератор») — пиши в живом разговорном тоне."
        )
    return "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n" + (style_profile.get("profile_text") or "нет данных")


def _categories_section(cat_stats: list) -> list:
    lines = ["=== РУБРИКИ (эффективность по органическим Reels) ==="]
    if not cat_stats:
        lines.append("Рубрики не настроены.")
        return lines
    for c in cat_stats:
        er = f'{c["avg_er"]}%' if c["avg_er"] is not None else "нет данных"
        saves = f'{c["avg_saves_rate"]}%' if c["avg_saves_rate"] is not None else "нет данных"
        hook = f'{c["avg_hook_indicator"]}%' if c["avg_hook_indicator"] is not None else "нет данных"
        low_sample = " (маленькая выборка)" if c["organic_count"] < LOW_SAMPLE_THRESHOLD else ""
        lines.append(
            f'- «{c["name"]}»: {c["organic_count"]} органических рилсов{low_sample}, '
            f"средний ER {er}, saves rate {saves}, индикатор хука {hook}"
        )
    return lines


def build_context_text(cat_stats: list) -> str:
    cfg = get_effective_config()
    niche = (cfg.get("account_niche") or "").strip()
    style_profile = load_style_profile()

    lines = [_niche_section(niche), "", _style_section(style_profile), ""]
    lines.extend(_categories_section(cat_stats))
    return "\n".join(lines)


CATEGORIES_AI_PERSONA = (
    "Ты — контент-стратег, специализирующийся на рубриках/тематических сериях Reels. Тебе "
    "передан срез реальных данных аккаунта: нишу, профиль стиля автора и уже посчитанную "
    "эффективность каждой рубрики (средний ER, saves rate, индикатор хука, количество рилсов). "
    "Напиши короткий связный вывод (4-7 предложений): какая рубрика тянет показатели вверх/вниз "
    "и почему (в контексте ниши, а не только по цифрам), и что делать — усилить, объединить с "
    "другой или закрыть конкретную рубрику."
)


def build_prompt(context_text: str, lang: str) -> tuple:
    system_prompt = (
        CATEGORIES_AI_PERSONA + "\n\n" + HONESTY_AND_ACTION_RULES + "\n\n" + _lang_instruction(lang)
    )
    return system_prompt, context_text


def generate_categories_summary(api_key: str, lang: str, cat_stats: list) -> str:
    context_text = build_context_text(cat_stats)
    system_prompt, user_message = build_prompt(context_text, lang)
    return call_opus(api_key, system_prompt, user_message, max_tokens=MAX_TOKENS)
