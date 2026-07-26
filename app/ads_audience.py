"""
"Аудитория: та или не та?" — углублённый анализ по группе объявлений (adset).
Чистая логика без обращений к API: принимает уже посчитанные данные (метрики, breakdowns,
ranking-диагностику, learning stage, тренд частоты) и выдаёт структурированный вердикт с
обоснованием по цифрам. Каждый вывод в reasoning ссылается на конкретное число — без этого
в список не попадает (честность важнее полноты).
"""
from app.ads_api import BELOW_AVERAGE_RANKING_CODES
from app.i18n import t

SPEND_SKEW_THRESHOLD = 10.0   # п.п. разницы между долей бюджета и долей результата
CTR_LOW_THRESHOLD = 1.0       # % — ниже считаем "низкий CTR"
CTR_HIGH_VARIANCE = 0.4       # коэффициент вариации CTR между сегментами
FATIGUE_FREQUENCY_FLAG = 2.5
NARROW_AGE_SPAN = 10          # лет — таргетинг уже такой ширины считаем "узким"

# Защита от вывода на шуме. Абсолютный порог по расходу тут принципиально не берём —
# валюты у кабинетов разные, единого универсального числа нет. А вот число результатов и
# длина периода валют не касаются — это и есть честные, currency-independent пороги.
MIN_RESULTS_FOR_VERDICT = 50  # результатов за период — меньше -> "недостаточно данных, шум"
MIN_PERIOD_DAYS = 3           # дней в периоде — короче -> тот же вывод

# Сегмент breakdown'а с результатами меньше этого — сам по себе шум, не может быть
# "победителем"/"сливом" для вывода о сужении/смене таргетинга (см. _segment_skew).
MIN_SEGMENT_RESULTS = 5

# Если самый дешёвый сегмент почти не встречается в реальной органической аудитории
# аккаунта (follower_demographics) — подозрительно: похоже на дешёвое нецелевое
# вовлечение, а не на реальную аудиторию бренда, и НЕ повод советовать туда сужаться.
ORGANIC_MISMATCH_SHARE_THRESHOLD = 5.0  # % органической аудитории по этому сегменту

VERDICT_KEYS = {
    "audience_working": "audience.verdict.audience_working",
    "narrow_to_segment": "audience.verdict.narrow_to_segment",
    "wrong_change_to": "audience.verdict.wrong_change_to",
    "not_audience_its_creative": "audience.verdict.not_audience_its_creative",
    "insufficient_data": "audience.verdict.insufficient_data",
}


def _ctr_variance_diagnosis(rows: list) -> dict:
    """TZ: CTR низкий везде -> крео; CTR разный по сегментам -> таргет."""
    ctrs = [r["metrics"].get("ctr") for r in rows if r["metrics"].get("ctr") is not None and (r["metrics"].get("spend") or 0) > 0]
    if len(ctrs) < 2:
        return {"diagnosis": None, "note": t("audience.ctr.note.insufficient"), "mean_ctr": None, "cv": None}

    mean_ctr = sum(ctrs) / len(ctrs)
    if mean_ctr == 0:
        return {"diagnosis": "creative", "note": t("audience.ctr.note.zero"), "mean_ctr": 0, "cv": None}

    variance = sum((c - mean_ctr) ** 2 for c in ctrs) / len(ctrs)
    cv = round((variance ** 0.5) / mean_ctr, 2)

    if mean_ctr < CTR_LOW_THRESHOLD and cv < CTR_HIGH_VARIANCE:
        return {
            "diagnosis": "creative",
            "note": t("audience.ctr.note.low_uniform", mean_ctr=f"{mean_ctr:.2f}", n=len(ctrs)),
            "mean_ctr": round(mean_ctr, 2),
            "cv": cv,
        }
    if cv >= CTR_HIGH_VARIANCE:
        return {
            "diagnosis": "audience",
            "note": t("audience.ctr.note.high_variance", cv_pct=int(cv * 100), mean_ctr=f"{mean_ctr:.2f}"),
            "mean_ctr": round(mean_ctr, 2),
            "cv": cv,
        }
    return {
        "diagnosis": "inconclusive",
        "note": t("audience.ctr.note.inconclusive", mean_ctr=f"{mean_ctr:.2f}"),
        "mean_ctr": round(mean_ctr, 2),
        "cv": cv,
    }


def _segment_skew(tagged_rows: list) -> list:
    """Перекос "деньги идут сюда, результаты — оттуда". tagged_rows — [{label, _dim, metrics, result}]."""
    total_spend = sum(r["metrics"].get("spend") or 0 for r in tagged_rows)
    total_results = sum((r["result"].get("value") or 0) for r in tagged_rows if r.get("result"))
    if not total_spend or not total_results:
        return []

    out = []
    for r in tagged_rows:
        spend = r["metrics"].get("spend") or 0
        result_value = (r["result"].get("value") or 0) if r.get("result") else 0
        if not spend:
            continue
        spend_share = round(spend / total_spend * 100, 1)
        result_share = round(result_value / total_results * 100, 1) if total_results else 0.0
        out.append({
            "label": r["label"],
            "_dim": r.get("_dim"),
            "spend_share": spend_share,
            "result_share": result_share,
            "skew": round(result_share - spend_share, 1),
            "result_value": result_value,
        })
    return sorted(out, key=lambda x: x["skew"])


def _reliable_pivot_rows(skew_rows: list) -> list:
    """Сегменты с результатами ниже MIN_SEGMENT_RESULTS сами по себе — шум: 2 лида по 55-64
    ничего не доказывают, даже если по проценту это "дешевле всех". Такие строки остаются в
    ranked-списке для прозрачности, но не могут быть "победителем"/"сливом" вывода."""
    return [r for r in skew_rows if r["result_value"] >= MIN_SEGMENT_RESULTS]


def _organic_share_for_segment(segment: dict, organic_audience: dict):
    """Доля этого age-сегмента в РЕАЛЬНОЙ органической аудитории аккаунта (follower_demographics).
    None, если сегмент не по возрасту или органических данных нет — тогда сравнение честно
    не делается, а не выдумывается."""
    if not segment or segment.get("_dim") != "age" or not organic_audience or not organic_audience.get("available"):
        return None
    by_age = organic_audience.get("by_age") or {}
    total = sum(by_age.values())
    if not total:
        return None
    return round(by_age.get(segment["label"], 0) / total * 100, 1)


def _segment_within_targeting(row: dict, raw_targeting: dict) -> bool:
    """Укладывается ли выигрышный/сливающий сегмент в уже настроенный таргетинг (значит,
    достаточно СУЗИТЬ существующий таргетинг), или он вне его рамок (значит, таргетинг нужно
    МЕНЯТЬ). При неразборчивом формате не блокируем вывод ложным "не то" — считаем "в рамках"."""
    dim = row.get("_dim")
    label = row.get("label", "")
    if dim == "gender":
        genders = raw_targeting.get("genders") or []
        if not genders:
            return True
        wanted = {1: "male", 2: "female"}
        target_labels = {wanted.get(g) for g in genders}
        return label in target_labels
    if dim == "age":
        age_min, age_max = raw_targeting.get("age_min"), raw_targeting.get("age_max")
        if age_min is None and age_max is None:
            return True
        try:
            lo_str, hi_str = label.split("-")
            lo, hi = int(lo_str), int(hi_str.rstrip("+"))
        except (ValueError, AttributeError):
            return True
        return lo >= (age_min or 0) and hi <= (age_max or 200)
    return True


def _targeting_is_narrow(raw_targeting: dict) -> bool:
    age_min, age_max = raw_targeting.get("age_min"), raw_targeting.get("age_max")
    genders = raw_targeting.get("genders") or []
    age_narrow = age_min is not None and age_max is not None and (age_max - age_min) <= NARROW_AGE_SPAN
    gender_narrow = len(genders) == 1
    return age_narrow and gender_narrow


def compute_audience_verdict(
    adset_metrics: dict,
    adset_result: dict,
    raw_targeting: dict,
    breakdowns: dict,
    ads_diagnostics: list,
    learning_stage,
    frequency_trend: dict = None,
    period_days: int = None,
    organic_audience: dict = None,
) -> dict:
    reasoning = []

    # Защита от вывода на шуме (см. MIN_RESULTS_FOR_VERDICT/MIN_PERIOD_DAYS выше) — ДО любых
    # других сигналов: с выборкой настолько маленькой ненадёжны и CTR-паттерны по сегментам,
    # не только сам вывод "сузить/сменить аудиторию".
    total_results = (adset_result or {}).get("value")
    low_volume = False
    if total_results is not None and total_results < MIN_RESULTS_FOR_VERDICT:
        low_volume = True
        reasoning.append(t("audience.reasoning.low_volume_results", value=total_results, min=MIN_RESULTS_FOR_VERDICT))
    if period_days is not None and period_days < MIN_PERIOD_DAYS:
        low_volume = True
        reasoning.append(t("audience.reasoning.low_volume_period", days=period_days, min=MIN_PERIOD_DAYS))

    if learning_stage == "LEARNING_LIMITED":
        reasoning.append(t("audience.reasoning.learning_limited"))
    elif learning_stage == "LEARNING":
        reasoning.append(t("audience.reasoning.learning"))
    elif learning_stage is None:
        reasoning.append(t("audience.reasoning.no_learning_data"))

    ranking_flags = []
    for ad in ads_diagnostics:
        rankings = ad.get("rankings") or {}
        for key, code_key, label_key in (
            ("quality", "quality_code", "audience.ranking_name.quality"),
            ("engagement_rate", "engagement_rate_code", "audience.ranking_name.engagement_rate"),
            ("conversion_rate", "conversion_rate_code", "audience.ranking_name.conversion_rate"),
        ):
            val = rankings.get(key)
            code = rankings.get(code_key)
            if val and code in BELOW_AVERAGE_RANKING_CODES:
                ranking_flags.append(f'«{ad.get("name") or "?"}»: {t(label_key)} — {val}')
    if ranking_flags:
        reasoning.append(t("audience.reasoning.ranking_flags", flags="; ".join(ranking_flags)))

    age_rows = [dict(r, _dim="age") for r in (breakdowns.get("age") or [])]
    gender_rows = [dict(r, _dim="gender") for r in (breakdowns.get("gender") or [])]

    ctr_diag = _ctr_variance_diagnosis(age_rows or gender_rows)
    if ctr_diag["note"]:
        reasoning.append(ctr_diag["note"])

    segment_rows = age_rows + gender_rows
    skew_rows = _segment_skew(segment_rows)
    reliable_rows = _reliable_pivot_rows(skew_rows)
    noisy_segments_only = bool(skew_rows) and not reliable_rows
    worst_segment = reliable_rows[0] if reliable_rows else None
    cheapest_segment = reliable_rows[-1] if reliable_rows else None

    if noisy_segments_only:
        reasoning.append(t("audience.reasoning.segments_too_small", min=MIN_SEGMENT_RESULTS))

    if worst_segment and worst_segment["skew"] < -SPEND_SKEW_THRESHOLD:
        reasoning.append(t(
            "audience.reasoning.spend_sink",
            label=worst_segment["label"], spend_share=worst_segment["spend_share"], result_share=worst_segment["result_share"],
        ))
    if cheapest_segment and cheapest_segment["skew"] > SPEND_SKEW_THRESHOLD and cheapest_segment is not worst_segment:
        reasoning.append(t(
            "audience.reasoning.underinvested",
            label=cheapest_segment["label"], spend_share=cheapest_segment["spend_share"], result_share=cheapest_segment["result_share"],
        ))
        organic_share = _organic_share_for_segment(cheapest_segment, organic_audience)
        if organic_share is not None and organic_share < ORGANIC_MISMATCH_SHARE_THRESHOLD:
            reasoning.append(t(
                "audience.reasoning.organic_mismatch",
                label=cheapest_segment["label"], organic_pct=organic_share,
            ))

    freq = adset_metrics.get("frequency")
    if freq is not None and freq >= FATIGUE_FREQUENCY_FLAG:
        reasoning.append(t("audience.reasoning.frequency_high", freq=f"{freq:.2f}"))
    if frequency_trend and frequency_trend.get("direction") == "worsening":
        pct = frequency_trend.get("change_pct")
        sign = "+" if pct and pct > 0 else ""
        reasoning.append(t("audience.reasoning.frequency_trend_worsening", sign=sign, pct=pct))

    has_significant_skew = bool(skew_rows) and (
        (worst_segment and worst_segment["skew"] < -SPEND_SKEW_THRESHOLD)
        or (cheapest_segment and cheapest_segment["skew"] > SPEND_SKEW_THRESHOLD)
    )

    # low_volume — приоритетнее любых других сигналов: на выборке меньше MIN_RESULTS_FOR_VERDICT
    # результатов/MIN_PERIOD_DAYS дней сужать/менять аудиторию не советуем, точка.
    if low_volume:
        verdict = "insufficient_data"
    elif ctr_diag["diagnosis"] == "creative":
        verdict = "not_audience_its_creative"
    elif learning_stage == "LEARNING":
        verdict = "insufficient_data"
    elif not skew_rows and freq is None and not ranking_flags:
        verdict = "insufficient_data"
    elif noisy_segments_only and freq is None and not ranking_flags:
        verdict = "insufficient_data"
    elif has_significant_skew:
        pivot_segment = cheapest_segment if (cheapest_segment and cheapest_segment["skew"] > SPEND_SKEW_THRESHOLD) else worst_segment
        verdict = "narrow_to_segment" if _segment_within_targeting(pivot_segment, raw_targeting) else "wrong_change_to"
    elif learning_stage == "LEARNING_LIMITED" and freq is not None and freq >= 2.0:
        verdict = "wrong_change_to" if _targeting_is_narrow(raw_targeting) else "narrow_to_segment"
    else:
        verdict = "audience_working"

    label = t(VERDICT_KEYS[verdict])
    if verdict == "narrow_to_segment" and reliable_rows:
        pivot = cheapest_segment if (cheapest_segment and cheapest_segment["skew"] > SPEND_SKEW_THRESHOLD) else worst_segment
        label = t("audience.verdict_label.narrow_to_segment_pivot", segment=pivot["label"])
    elif verdict == "wrong_change_to" and reliable_rows:
        pivot = cheapest_segment if (cheapest_segment and cheapest_segment["skew"] > SPEND_SKEW_THRESHOLD) else worst_segment
        label = t("audience.verdict_label.wrong_change_to_pivot", segment=pivot["label"])

    if not reasoning:
        reasoning.append(t("audience.reasoning.no_signals"))

    return {
        "verdict": verdict,
        "verdict_label": label,
        "reasoning": reasoning,
        "cheapest_segment": cheapest_segment,
        "worst_segment": worst_segment,
        "ctr_diagnosis": ctr_diag,
        "ranking_flags": ranking_flags,
        "learning_stage": learning_stage,
        "low_volume": low_volume,
    }
