"""
Вердикт «зайшло / не зайшло» по одному рекламному крео — розкладка на 4 компоненти
(хук, текст/оффер, CTA, візуал) за цифрами Marketing API (див. app/ads_api.py) і
опційним транскриптом (app/transcription.py, якщо об'ява прив'язана до органічного
Reels через source_instagram_media_id).

Чиста логіка без HTTP-викликів — за зразком app/ads_audience.py::compute_audience_verdict.
Порівняння ЗАВЖДИ відносне — з середнім по інших об'явленнях тієї ж групи (adset) за той
самий період (той самий підхід, що в app/script_verdict.py: BETTER_RATIO/WORSE_RATIO),
бо в різних кабінетів/ніш різні "нормальні" цифри. Сусідні креативи в одній групі
конкурують за ту саму аудиторію й бюджет — коректніша база, ніж загальноринкові орієнтири.

Логіка компонентів (як просив користувач):
- високий skip перших 3с (низький hook_rate) -> слабкий хук/початок;
- добрий досмотр (ThruPlay/watch-through), але низький CTR -> слабкий текст/оффер
  (глядачі дивляться, та не клікають);
- низький клік саме по CTA-посиланню при нормальному залученні -> слабкий заклик до дії;
- "візуал" Marketing API прямо не віддає — чесно використовуємо quality_ranking Meta
  (порівняння з конкурентами за ту саму аудиторію) як найближчий доступний проксі.
"""
from app.ads_api import BELOW_AVERAGE_RANKING_CODES
from app.i18n import t

BETTER_RATIO = 1.15
WORSE_RATIO = 0.85

# Менше показів — частки 3s/ThruPlay/watch-through надто шумні, чесно "немає даних",
# а не робимо вердикт на дрібній вибірці.
MIN_IMPRESSIONS_FOR_RATES = 100

VERDICT_LABEL_KEYS = {
    "good": "creative_verdict.verdict.good",
    "bad": "creative_verdict.verdict.bad",
    "neutral": "creative_verdict.verdict.neutral",
    "insufficient_data": "creative_verdict.verdict.insufficient_data",
}

COMPONENT_LABEL_KEYS = {
    "hook": "creative_verdict.component.hook",
    "text": "creative_verdict.component.text",
    "cta": "creative_verdict.component.cta",
    "visual": "creative_verdict.component.visual",
}

_QUALITY_CLASS_BY_CODE = {"ABOVE_AVERAGE": "better", "AVERAGE": "near"}


def _rate(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def compute_rates(metrics: dict) -> dict:
    """hook_rate (частка тих, хто не проскіпнув перші 3с), thruplay_rate, watch_through_rate —
    похідні від сирих метрик Marketing API. Замало показів -> None (шум), не 0."""
    metrics = metrics or {}
    impressions = metrics.get("impressions")
    if not impressions or impressions < MIN_IMPRESSIONS_FOR_RATES:
        return {"hook_rate": None, "thruplay_rate": None, "watch_through_rate": None}
    return {
        "hook_rate": _rate(metrics.get("video_3s_views"), impressions),
        "thruplay_rate": _rate(metrics.get("thruplay"), impressions),
        "watch_through_rate": _rate(metrics.get("video_p100"), impressions),
    }


def compute_baseline(sibling_ads: list, exclude_ad_id: str = None) -> dict:
    """Середні по інших об'явленнях тієї ж групи за той самий період. sibling_ads —
    [{"id", "metrics"}, ...] (те, що повертає fetch_ad_diagnostics для кожного оголошення)."""
    rows = [a for a in sibling_ads if a.get("id") != exclude_ad_id and a.get("metrics")]

    def avg(field=None, rate_field=None):
        vals = []
        for r in rows:
            v = compute_rates(r["metrics"]).get(rate_field) if rate_field else r["metrics"].get(field)
            if v is not None:
                vals.append(v)
        return (round(sum(vals) / len(vals), 2) if vals else None), len(vals)

    ctr_avg, ctr_n = avg(field="ctr")
    ctr_link_avg, ctr_link_n = avg(field="ctr_link")
    hook_avg, hook_n = avg(rate_field="hook_rate")
    thruplay_avg, thruplay_n = avg(rate_field="thruplay_rate")
    watch_avg, watch_n = avg(rate_field="watch_through_rate")

    return {
        "sample_size": len(rows),
        "ctr_avg": ctr_avg, "ctr_sample": ctr_n,
        "ctr_link_avg": ctr_link_avg, "ctr_link_sample": ctr_link_n,
        "hook_rate_avg": hook_avg, "hook_rate_sample": hook_n,
        "thruplay_rate_avg": thruplay_avg, "thruplay_rate_sample": thruplay_n,
        "watch_through_rate_avg": watch_avg, "watch_through_rate_sample": watch_n,
    }


def _classify(value, baseline_avg):
    if value is None or not baseline_avg:
        return None
    ratio = value / baseline_avg
    if ratio >= BETTER_RATIO:
        return "better"
    if ratio <= WORSE_RATIO:
        return "worse"
    return "near"


def _component(component_id, cls, reasoning):
    return {
        "component": component_id,
        "label": t(COMPONENT_LABEL_KEYS[component_id]),
        "class": cls,
        "reasoning": reasoning,
    }


def _hook_component(rates, baseline):
    cls = _classify(rates["hook_rate"], baseline["hook_rate_avg"])
    if cls is None:
        return _component("hook", None, t("creative_verdict.reasoning.hook_no_data"))
    key = {"worse": "hook_worse", "better": "hook_better", "near": "hook_near"}[cls]
    reasoning = t(f"creative_verdict.reasoning.{key}", value=rates["hook_rate"], baseline=baseline["hook_rate_avg"])
    return _component("hook", cls, reasoning)


def _watch_signal_class(rates, baseline):
    """Найкращий доступний сигнал утримання середини ролика — ThruPlay, або watch-through,
    якщо ThruPlay недоступний (наприклад, коротке відео без окремого ThruPlay-поля)."""
    cls = _classify(rates["thruplay_rate"], baseline["thruplay_rate_avg"])
    if cls is not None:
        return cls
    return _classify(rates["watch_through_rate"], baseline["watch_through_rate_avg"])


def _text_component(rates, metrics, baseline, hook_cls):
    if hook_cls == "worse":
        return _component("text", None, t("creative_verdict.reasoning.text_insufficient_hook_weak"))

    ctr = metrics.get("ctr")
    ctr_cls = _classify(ctr, baseline["ctr_avg"])
    if ctr_cls is None:
        return _component("text", None, t("creative_verdict.reasoning.text_no_data"))

    watch_cls = _watch_signal_class(rates, baseline)
    watch_value = rates["thruplay_rate"] if rates["thruplay_rate"] is not None else rates["watch_through_rate"]
    watch_baseline = baseline["thruplay_rate_avg"] if rates["thruplay_rate"] is not None else baseline["watch_through_rate_avg"]

    if ctr_cls == "worse" and watch_cls in ("better", "near") and watch_value is not None:
        reasoning = t("creative_verdict.reasoning.text_bad_low_ctr_good_watch", value=watch_value, baseline=watch_baseline)
        return _component("text", "worse", reasoning)
    if ctr_cls == "worse" and watch_cls == "worse":
        return _component("text", "worse", t("creative_verdict.reasoning.text_bad_low_retention"))
    if ctr_cls == "better":
        return _component("text", "better", t("creative_verdict.reasoning.text_good", value=ctr, baseline=baseline["ctr_avg"]))
    return _component("text", "near", t("creative_verdict.reasoning.text_near", value=ctr, baseline=baseline["ctr_avg"]))


def _cta_component(metrics, baseline, creative, hook_cls):
    no_button = not creative.get("cta") or creative.get("cta") == "Без кнопки"

    if hook_cls == "worse":
        reasoning = t("creative_verdict.reasoning.text_insufficient_hook_weak")
        return _component("cta", None, reasoning + (" " + t("creative_verdict.reasoning.cta_no_button") if no_button else ""))

    ctr_link = metrics.get("ctr_link")
    cls = _classify(ctr_link, baseline["ctr_link_avg"])
    if cls is None:
        reasoning = t("creative_verdict.reasoning.cta_no_data")
        return _component("cta", None, reasoning + (" " + t("creative_verdict.reasoning.cta_no_button") if no_button else ""))

    key = {"worse": "cta_bad", "better": "cta_good", "near": "cta_near"}[cls]
    reasoning = t(f"creative_verdict.reasoning.{key}", value=ctr_link, baseline=baseline["ctr_link_avg"])
    if no_button:
        reasoning += " " + t("creative_verdict.reasoning.cta_no_button")
    return _component("cta", cls, reasoning)


def _visual_component(rankings):
    rankings = rankings or {}
    code = rankings.get("quality_code")
    label = rankings.get("quality")
    if not code or code == "UNKNOWN" or not label:
        return _component("visual", None, t("creative_verdict.reasoning.visual_no_data"))

    if code in BELOW_AVERAGE_RANKING_CODES:
        cls = "worse"
    else:
        cls = _QUALITY_CLASS_BY_CODE.get(code, "near")
    key = {"worse": "visual_worse", "better": "visual_better", "near": "visual_near"}[cls]
    return _component("visual", cls, t(f"creative_verdict.reasoning.{key}", label=label))


def compute_creative_verdict(metrics: dict, creative: dict, rankings: dict, baseline: dict) -> dict:
    """metrics — format_metrics_row() цього оголошення; creative — format_creative();
    rankings — блок "rankings" з fetch_ad_diagnostics(); baseline — compute_baseline() по
    сусідніх об'явленнях тієї ж групи. Повертає {"verdict", "verdict_label", "components": {...},
    "rates": {...}, "baseline": {...}}."""
    metrics = metrics or {}
    creative = creative or {}
    rates = compute_rates(metrics)

    hook = _hook_component(rates, baseline)
    text = _text_component(rates, metrics, baseline, hook["class"])
    cta = _cta_component(metrics, baseline, creative, hook["class"])
    visual = _visual_component(rankings)

    components = [hook, text, cta, visual]
    classified = [c for c in components if c["class"] is not None]

    if len(classified) < 2:
        verdict = "insufficient_data"
    else:
        better = sum(1 for c in classified if c["class"] == "better")
        worse = sum(1 for c in classified if c["class"] == "worse")
        if better > worse:
            verdict = "good"
        elif worse > better:
            verdict = "bad"
        else:
            verdict = "neutral"

    return {
        "verdict": verdict,
        "verdict_label": t(VERDICT_LABEL_KEYS[verdict]),
        "components": {"hook": hook, "text": text, "cta": cta, "visual": visual},
        "rates": rates,
        "baseline": baseline,
    }
