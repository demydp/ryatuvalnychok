"""
Авто-оценка "зашло / не зашло / нейтрально" для сгенерированного скрипта после
привязки к опубликованному рилсу. Сравнение ВСЕГДА относительное — с собственными
средними показателями аккаунта по органике, а не с абсолютными порогами (у разных
аккаунтов разные нормальные цифры). Метрики рилса "дозревают" несколько дней,
поэтому вердикт пересчитывается на каждом синке (см. recompute_all_verdicts,
вызывается из app/routes/metrics.py).
"""
from statistics import mean

from app.i18n import t
from app.saved_scripts import load_saved_scripts, now_iso, save_saved_scripts

# Порог "заметно отличается от среднего" — относительный, не абсолютный.
BETTER_RATIO = 1.15  # минимум на 15% выше среднего
WORSE_RATIO = 0.85  # минимум на 15% ниже среднего

# Ключи метрик хранятся вместо готового переведённого текста (persist в saved_scripts.json) —
# иначе при смене языка интерфейса старые вердикты остаются на языке, в котором были посчитаны.
# render_verdict_reason() рендерит текст из этих ключей заново при каждой отдаче на фронт
# (см. app/routes/generator.py: list_scripts и link_script).
METRIC_KEYS = {
    "er": "verdict.metric.er",
    "saves_rate": "verdict.metric.saves_rate",
    "skip_rate": "verdict.metric.skip_rate",
    "hook_indicator": "verdict.metric.hook_indicator",
}

# Записи, сохранённые до перехода на ключи метрик, хранят готовый русский "name" вместо
# "name_key" и вердикт словом ("зашло"/"не зашло"/"нейтрально") вместо кода. Обе таблицы
# нужны только для миграции старых данных "на лету" при отдаче (см. normalize_* ниже).
_LEGACY_METRIC_NAME_TO_KEY = {
    "ER": METRIC_KEYS["er"],
    "Saves rate": METRIC_KEYS["saves_rate"],
    "Skip rate": METRIC_KEYS["skip_rate"],
    "Индикатор хука (досмотр/длина)": METRIC_KEYS["hook_indicator"],
}
_LEGACY_VERDICT_MAP = {"зашло": "good", "не зашло": "bad", "нейтрально": "neutral"}


def normalize_verdict(verdict):
    return _LEGACY_VERDICT_MAP.get(verdict, verdict)


def normalize_verdict_metrics(metrics: list) -> list:
    if not metrics:
        return metrics
    return [
        m if "name_key" in m else {**m, "name_key": _LEGACY_METRIC_NAME_TO_KEY.get(m.get("name"), "")}
        for m in metrics
    ]


def _hook_indicator(post: dict, transcript: dict):
    avg_watch_ms = post.get("avg_watch_time")
    duration_sec = (transcript or {}).get("duration_sec")
    if avg_watch_ms is None or not duration_sec:
        return None
    return round((avg_watch_ms / 1000) / duration_sec * 100, 2)


def _organic_reels(posts: list, exclude_id: str = None) -> list:
    return [
        p
        for p in posts
        if p.get("media_product_type") == "REELS"
        and not p.get("is_ad")
        and p.get("insights_status") == "ok"
        and p.get("id") != exclude_id
    ]


def compute_baseline(posts: list, transcripts: dict, exclude_id: str = None) -> dict:
    """Средние по органике аккаунта — база для сравнения. exclude_id исключает сам
    оцениваемый рилс, чтобы он не подтягивал среднее к себе же."""
    organic = _organic_reels(posts, exclude_id)

    ers = [p["engagement_rate"] for p in organic if p.get("engagement_rate") is not None]
    saves_rates = [p["saves_rate"] for p in organic if p.get("saves_rate") is not None]
    skip_rates = [p["skip_rate"] for p in organic if p.get("skip_rate") is not None]
    hook_indicators = []
    for p in organic:
        hi = _hook_indicator(p, transcripts.get(p["id"]))
        if hi is not None:
            hook_indicators.append(hi)

    return {
        "sample_size": len(organic),
        "er_avg": round(mean(ers), 2) if ers else None,
        "er_sample": len(ers),
        "saves_rate_avg": round(mean(saves_rates), 2) if saves_rates else None,
        "saves_rate_sample": len(saves_rates),
        "skip_rate_avg": round(mean(skip_rates), 2) if skip_rates else None,
        "skip_rate_sample": len(skip_rates),
        "hook_indicator_avg": round(mean(hook_indicators), 2) if hook_indicators else None,
        "hook_indicator_sample": len(hook_indicators),
    }


def _classify(value, baseline_avg, lower_is_better: bool = False):
    if value is None or not baseline_avg:
        return None
    ratio = value / baseline_avg
    if lower_is_better:
        ratio = (1 / ratio) if ratio else float("inf")
    if ratio >= BETTER_RATIO:
        return "better"
    if ratio <= WORSE_RATIO:
        return "worse"
    return "near"


def render_verdict_reason(verdict, metrics: list) -> str:
    """Строит текст обоснования из ключей метрик на ТЕКУЩЕМ языке интерфейса — вызывается
    и сразу при подсчёте, и заново при каждой отдаче сохранённых скриптов на фронт
    (app/routes/generator.py), чтобы смена языка не оставляла старый вердикт на другом языке."""
    if not metrics:
        return t("verdict.reason.insufficient_metrics")
    return "; ".join(
        t("verdict.metric_line", name=t(m.get("name_key", "")), value=m["value"], baseline=m["baseline"])
        for m in normalize_verdict_metrics(metrics)
    )


def evaluate_reel(post: dict, transcript: dict, baseline: dict) -> dict:
    """Возвращает {"verdict": "good"/"bad"/"neutral"/None, "reason": str, "metrics": [...]}."""
    metrics = []

    checks = [
        ("er", post.get("engagement_rate"), baseline.get("er_avg"), False),
        ("saves_rate", post.get("saves_rate"), baseline.get("saves_rate_avg"), False),
        ("skip_rate", post.get("skip_rate"), baseline.get("skip_rate_avg"), True),
        ("hook_indicator", _hook_indicator(post, transcript), baseline.get("hook_indicator_avg"), False),
    ]

    for metric_id, value, baseline_avg, lower_is_better in checks:
        cls = _classify(value, baseline_avg, lower_is_better)
        if cls is None:
            continue
        metrics.append({"name_key": METRIC_KEYS[metric_id], "value": round(value, 2), "baseline": baseline_avg, "class": cls})

    if not metrics:
        return {"verdict": None, "reason": render_verdict_reason(None, []), "metrics": []}

    better = sum(1 for m in metrics if m["class"] == "better")
    worse = sum(1 for m in metrics if m["class"] == "worse")

    if better > worse:
        verdict = "good"
    elif worse > better:
        verdict = "bad"
    else:
        verdict = "neutral"

    reason = render_verdict_reason(verdict, metrics)

    return {"verdict": verdict, "reason": reason, "metrics": metrics}


def resolve_media_id_by_reference(posts: list, reference: str):
    """Находит media_id по прямому ID, ссылке на пост или shortcode."""
    ref = (reference or "").strip()
    if not ref:
        return None
    if any(p.get("id") == ref for p in posts):
        return ref
    shortcode = ref.rstrip("/").split("/")[-1] if "/" in ref else ref
    if not shortcode:
        return None
    for p in posts:
        if p.get("permalink") and shortcode in p["permalink"]:
            return p["id"]
    return None


def recompute_all_verdicts(posts: list, transcripts: dict):
    """Пересчитывает вердикты всех привязанных скриптов на свежих данных — вызывается
    после каждого синка, потому что метрики рилса дозревают несколько дней и ранний
    вердикт может быть ложным."""
    scripts = load_saved_scripts()
    posts_by_id = {p["id"]: p for p in posts}
    changed = False

    for s in scripts:
        media_id = s.get("linked_media_id")
        if not media_id:
            continue
        post = posts_by_id.get(media_id)
        if not post:
            continue
        baseline = compute_baseline(posts, transcripts, exclude_id=media_id)
        result = evaluate_reel(post, transcripts.get(media_id), baseline)
        if result["verdict"] != s.get("verdict") or result["reason"] != s.get("verdict_reason"):
            s["verdict"] = result["verdict"]
            s["verdict_reason"] = result["reason"]
            s["verdict_metrics"] = result["metrics"]
            s["verdict_computed_at"] = now_iso()
            s["baseline_used"] = baseline
            changed = True

    if changed:
        save_saved_scripts(scripts)
    return scripts
