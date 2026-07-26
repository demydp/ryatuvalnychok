"""
AI-висновок для вкладки "Хук-аналіз" — той самий контракт, що вже працює в app/ideas.py /
app/companion.py: реальний контекст (ніша, стиль, вже порахована статистика хуків), чесність
щодо малої вибірки, причинно-наслідкове пояснення і дія. На відміну від hook_classifier.py /
hunt_classifier.py (вузькі одноразові класифікатори без контексту акаунта), це один зв'язний
висновок по всій вкладці, що рахується наживо з уже закешованих даних за явним кліком
користувача (POST /api/hooks/ai-summary), як і всі інші AI-виклики в проєкті.
"""
from collections import defaultdict
from statistics import mean

from app.ads_opus import _lang_instruction, call_opus
from app.ai_standard import HONESTY_AND_ACTION_RULES
from app.project_store import get_effective_config
from app.routes.metrics import load_cache
from app.style_profile import load_style_profile
from app.transcription import load_transcripts

MAX_TOKENS = 600


def compute_hook_stats(cache: dict, transcripts: dict) -> dict:
    """Ті самі 3 статистичні зведення, що раніше рахувались inline у get_hooks() (app/routes/
    hooks.py) — винесені сюди, щоб і роут (для таблиці), і generate_hook_summary() (для
    контексту промпту) використовували одну логіку, без дублювання."""
    reels = [p for p in cache.get("posts", []) if p.get("media_product_type") == "REELS"]

    items = []
    for p in reels:
        t = transcripts.get(p["id"])
        avg_watch_ms = p.get("avg_watch_time")
        duration_sec = t.get("duration_sec") if t else None

        hook_indicator = None
        if t and duration_sec and avg_watch_ms is not None and duration_sec > 0:
            hook_indicator = round((avg_watch_ms / 1000) / duration_sec * 100, 1)

        items.append(
            {
                "id": p["id"],
                "caption": p.get("caption", ""),
                "permalink": p.get("permalink"),
                "thumbnail_url": p.get("thumbnail_url"),
                "timestamp": p.get("timestamp"),
                "is_ad": p.get("is_ad", False),
                "avg_watch_time_ms": avg_watch_ms,
                "skip_rate": p.get("skip_rate"),
                "skip_rate_reason": p.get("skip_rate_reason"),
                "engagement_rate": p.get("engagement_rate"),
                "transcript_status": "ok" if t else "not_transcribed",
                "duration_sec": duration_sec,
                "hook_text": t.get("hook_text") if t else None,
                "hook_type": t.get("hook_type") if t else None,
                "text": t.get("text") if t else None,
                "language": t.get("language") if t else None,
                "hook_indicator": hook_indicator,
                "low_confidence": t.get("low_confidence") if t else None,
                "quality_reason": t.get("quality_reason") if t else None,
                "whisper_model": t.get("model") if t else None,
                "hunt_stage": t.get("hunt_stage") if t else None,
                "hunt_temperature": t.get("hunt_temperature") if t else None,
                "hunt_reasoning": t.get("hunt_reasoning") if t else None,
                "hunt_note": t.get("hunt_note") if t else None,
            }
        )

    buckets = defaultdict(list)
    skip_buckets = defaultdict(list)
    er_buckets = defaultdict(list)
    for it in items:
        if it["is_ad"] or it["low_confidence"] or not it["hook_type"]:
            continue
        if it["hook_indicator"] is not None:
            buckets[it["hook_type"]].append(it["hook_indicator"])
        if it["skip_rate"] is not None:
            skip_buckets[it["hook_type"]].append(it["skip_rate"])
        if it["engagement_rate"] is not None:
            er_buckets[it["hook_type"]].append(it["engagement_rate"])

    hook_type_summary = [
        {"type": k, "avg_indicator": round(mean(v), 1), "count": len(v)} for k, v in buckets.items()
    ]
    hook_type_summary.sort(key=lambda x: x["avg_indicator"], reverse=True)

    skip_rate_summary = [
        {"type": k, "avg_skip_rate": round(mean(v), 1), "count": len(v)} for k, v in skip_buckets.items()
    ]
    skip_rate_summary.sort(key=lambda x: x["avg_skip_rate"])

    engagement_rate_summary = [
        {"type": k, "avg_engagement_rate": round(mean(v), 2), "count": len(v)} for k, v in er_buckets.items()
    ]
    engagement_rate_summary.sort(key=lambda x: x["avg_engagement_rate"], reverse=True)

    transcribed_count = sum(1 for it in items if it["transcript_status"] == "ok" and not it["is_ad"])

    return {
        "items": items,
        "hook_type_summary": hook_type_summary,
        "skip_rate_summary": skip_rate_summary,
        "engagement_rate_summary": engagement_rate_summary,
        "transcribed_count": transcribed_count,
    }


def _niche_section(niche: str) -> str:
    return "=== НИША АККАУНТА ===\n" + (niche or "Ниша не указана в Настройках.")


def _style_section(style_profile) -> str:
    if not style_profile:
        return (
            "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n"
            "Профиль стиля ещё не посчитан (вкладка «Генератор») — пиши в живом разговорном тоне."
        )
    return "=== ПРОФИЛЬ СТИЛЯ АВТОРА ===\n" + (style_profile.get("profile_text") or "нет данных")


def _summary_lines(label: str, rows: list, value_key: str, suffix: str = "") -> list:
    if not rows:
        return [f"{label}: данных пока нет."]
    lines = [f"{label}:"]
    for r in rows:
        lines.append(f"- {r['type']}: {r[value_key]}{suffix} (n={r['count']})")
    return lines


def build_context_text(cache: dict, transcripts: dict) -> str:
    cfg = get_effective_config()
    niche = (cfg.get("account_niche") or "").strip()
    style_profile = load_style_profile()
    stats = compute_hook_stats(cache, transcripts)

    lines = [_niche_section(niche), "", _style_section(style_profile), ""]
    lines.append(f"=== СТАТИСТИКА ХУКІВ (проаналізовано транскриптів: {stats['transcribed_count']}) ===")
    lines.extend(_summary_lines("Досмотр после хука (% от длительности), по типу хука", stats["hook_type_summary"], "avg_indicator", "%"))
    lines.append("")
    lines.extend(_summary_lines("Skip rate (ниже = лучше), по типу хука", stats["skip_rate_summary"], "avg_skip_rate", "%"))
    lines.append("")
    lines.extend(_summary_lines("Engagement rate, по типу хука", stats["engagement_rate_summary"], "avg_engagement_rate", "%"))

    if stats["transcribed_count"] < 6:
        lines.append("")
        lines.append(
            f"Внимание: транскрибировано и учтено только {stats['transcribed_count']} рилсов — "
            "выборка маленькая, разбивка по типам хука может быть шумом."
        )

    return "\n".join(lines)


HOOKS_AI_PERSONA = (
    "Ты — аналитик хуков и удержания внимания в Reels. Тебе передан срез реальных данных "
    "аккаунта: нишу, профиль стиля автора и уже посчитанную статистику по типам хуков "
    "(досмотр после хука, skip rate, engagement rate). Напиши короткий связный вывод (4-7 "
    "предложений): какой тип хука реально держит внимание лучше, почему (в контексте ниши), и "
    "что снимать дальше — конкретный тип хука/подачу, а не общий совет."
)


def build_prompt(context_text: str, lang: str) -> tuple:
    system_prompt = (
        HOOKS_AI_PERSONA + "\n\n" + HONESTY_AND_ACTION_RULES + "\n\n" + _lang_instruction(lang)
    )
    return system_prompt, context_text


def generate_hook_summary(api_key: str, lang: str) -> str:
    cache = load_cache()
    transcripts = load_transcripts()
    context_text = build_context_text(cache, transcripts)
    system_prompt, user_message = build_prompt(context_text, lang)
    return call_opus(api_key, system_prompt, user_message, max_tokens=MAX_TOKENS)
