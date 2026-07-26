"""
AI-висновок для вкладки "Аналіз метрик" ("Що заходить") — той самий контракт, що вже працює
в app/ideas.py / app/companion.py / app/hooks_ai.py: реальний контекст (ніша, стиль, вже
порахована статистика compute_organic_analysis()), чесність щодо малої вибірки, причинно-
наслідкове пояснення і дія. app/analysis.py лишається чистою статистикою без LLM (як і
задумано в його докстрінгу) — цей модуль лише СПОЖИВАЄ порахований результат.
"""
from app.ads_opus import _lang_instruction, call_opus
from app.ai_standard import HONESTY_AND_ACTION_RULES
from app.project_store import get_effective_config
from app.style_profile import load_style_profile

MAX_TOKENS = 600


def _niche_section(niche: str) -> str:
    return "=== НИША АККАУНТА ===\n" + (niche or "Ниша не указана в Настройках.")


def _style_section(style_profile) -> str:
    if not style_profile:
        return (
            "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n"
            "Профиль стиля ещё не посчитан (вкладка «Генератор») — пиши в живом разговорном тоне."
        )
    return "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n" + (style_profile.get("profile_text") or "нет данных")


def _reel_line(p: dict, extra: tuple = ()) -> str:
    caption = (p.get("caption") or "").strip() or "(без подписи)"
    extra_text = "".join(f", {k}={p.get(k)}" for k in extra if p.get(k) is not None)
    return f"- «{caption[:80]}» ER {p.get('engagement_rate')}%, охват {p.get('reach')}{extra_text}"


def _analysis_section(analysis: dict) -> list:
    lines = ["=== СТАТИСТИКА ОРГАНИКИ (compute_organic_analysis) ==="]
    if analysis.get("insufficient_data"):
        lines.append(
            f"Недостаточно данных для анализа (проанализировано рилсов с инсайтами: "
            f"{analysis.get('reels_with_insights', 0)})."
        )
        return lines

    lines.append(
        f"Выборка: {analysis['dataset_size']} органических рилсов с инсайтами "
        f"(исключено рекламных: {analysis.get('ad_excluded_count', 0)}, без инсайтов: "
        f"{analysis.get('no_insights_excluded_count', 0)})."
    )
    if analysis.get("low_sample_warning"):
        lines.append(f"Внимание: выборка маленькая ({analysis['dataset_size']} рилсов) — рассуждай осторожно.")

    lines.append("")
    lines.append("Топ по ER:")
    lines.extend(_reel_line(p) for p in (analysis.get("top_er") or []))
    lines.append("Аутсайдеры по ER:")
    lines.extend(_reel_line(p) for p in (analysis.get("bottom_er") or []))

    if analysis.get("top_saves_rate"):
        lines.append("")
        lines.append("Топ по saves rate:")
        lines.extend(_reel_line(p, extra=("saves_rate",)) for p in analysis["top_saves_rate"])
    elif analysis.get("saves_note"):
        lines.append(analysis["saves_note"])

    if analysis.get("top_shares"):
        lines.append("")
        lines.append("Топ по репостам:")
        lines.extend(_reel_line(p, extra=("shares",)) for p in analysis["top_shares"])
    elif analysis.get("shares_note"):
        lines.append(analysis["shares_note"])

    if analysis.get("best_hour"):
        bh = analysis["best_hour"]
        lines.append(f"\nЛучшее время публикации: {bh['label']} (средний ER {bh['avg_er']}%, n={bh['count']})")
    if analysis.get("best_weekday"):
        bw = analysis["best_weekday"]
        lines.append(f"Лучший день недели: {bw['label']} (средний ER {bw['avg_er']}%, n={bw['count']})")

    return lines


def build_context_text(analysis: dict) -> str:
    cfg = get_effective_config()
    niche = (cfg.get("account_niche") or "").strip()
    style_profile = load_style_profile()

    lines = [_niche_section(niche), "", _style_section(style_profile), ""]
    lines.extend(_analysis_section(analysis))
    return "\n".join(lines)


INSIGHTS_AI_PERSONA = (
    "Ты — контент-аналитик Instagram Reels. Тебе передан срез реальных данных аккаунта: нишу, "
    "профиль стиля автора и уже посчитанную статистику органики (топ/аутсайдеры по ER, saves, "
    "репосты, лучшее время публикации). Напиши короткий связный вывод (4-7 предложений): почему "
    "топ-рилсы сработали, а аутсайдеры провалились (тема, подача, время публикации — то, что "
    "реально видно в данных), и что снимать дальше — конкретно, а не общими словами."
)


def build_prompt(context_text: str, lang: str) -> tuple:
    system_prompt = (
        INSIGHTS_AI_PERSONA + "\n\n" + HONESTY_AND_ACTION_RULES + "\n\n" + _lang_instruction(lang)
    )
    return system_prompt, context_text


def generate_insights_summary(api_key: str, lang: str, analysis: dict) -> str:
    context_text = build_context_text(analysis)
    system_prompt, user_message = build_prompt(context_text, lang)
    return call_opus(api_key, system_prompt, user_message, max_tokens=MAX_TOKENS)
