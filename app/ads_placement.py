"""
Крео × плейсмент (пункт C ТЗ): для конкретного объявления — где оно реально заходит
лучше (Instagram Reels / Stories / Feed, Facebook и т.п.), по цифрам, а не на глаз.

Метрика сравнения выбирается по тому же принципу честности, что и в ads_kpi.py —
"цена результата" приоритетнее CTR, потому что она напрямую отражает цель кампании
(лид дешевле/дороже), а CTR — только промежуточный сигнал. Если по цели кампании
результат не считается (например, Узнаваемость), сравниваем по CPM.
"""
from app.i18n import t

MIN_PLACEMENTS_TO_COMPARE = 2
INSIGNIFICANT_DIFF_PCT = 10.0

# Той самий волюм-фільтр, що й у app/client_report.py::_rank_ads — дешева ціна результату на
# жмені показів проти дорогої на тисячах не перемога плейсменту, а шум. Абсолютний поріг
# (замало показів взагалі) + відносний (в рази менше показів за найбільшого плейсмента в цій
# самій вибірці — інша вагова категорія, порівнювати нечесно).
MIN_IMPRESSIONS_FOR_RANK = 500
VOLUME_COMPARABILITY_RATIO = 0.2


def _rows_with_spend(rows: list) -> list:
    return [r for r in rows if (r.get("metrics") or {}).get("spend")]


def compute_placement_verdict(rows: list, objective: str) -> dict:
    """rows — результат fetch_all_breakdowns(...)["platform_position"], т.е. список
    {"label":..., "metrics": {...}, "result": {...}} (см. format_breakdown_row в ads_api.py).
    Честно: если данных мало, все плейсменты примерно одинаковы, или объём показов между
    плейсментами несопоставим (см. MIN_IMPRESSIONS_FOR_RANK/VOLUME_COMPARABILITY_RATIO) —
    так и говорим, не выдумываем "лучший" из шума."""
    valid = _rows_with_spend(rows)
    if len(valid) < MIN_PLACEMENTS_TO_COMPARE:
        return {
            "available": False,
            "metric_used": None,
            "best": None,
            "worst": None,
            "ranked": [],
            "note": t("placement.note.not_enough_placements"),
        }

    with_impressions = [r for r in valid if (r.get("metrics") or {}).get("impressions")]
    eligible = [r for r in with_impressions if r["metrics"]["impressions"] >= MIN_IMPRESSIONS_FOR_RANK]
    if len(eligible) < MIN_PLACEMENTS_TO_COMPARE:
        return {
            "available": False,
            "metric_used": None,
            "best": None,
            "worst": None,
            "ranked": [],
            "note": t("placement.note.not_enough_volume"),
        }

    max_impressions = max(r["metrics"]["impressions"] for r in eligible)
    valid = [r for r in eligible if r["metrics"]["impressions"] >= max_impressions * VOLUME_COMPARABILITY_RATIO]
    if len(valid) < MIN_PLACEMENTS_TO_COMPARE:
        return {
            "available": False,
            "metric_used": None,
            "best": None,
            "worst": None,
            "ranked": [],
            "note": t("placement.note.not_enough_volume"),
        }

    cost_rows = [r for r in valid if (r.get("result") or {}).get("cost_per_result") is not None]
    ctr_rows = [r for r in valid if (r.get("metrics") or {}).get("ctr") is not None]
    cpm_rows = [r for r in valid if (r.get("metrics") or {}).get("cpm") is not None]

    if len(cost_rows) >= MIN_PLACEMENTS_TO_COMPARE:
        metric_used, lower_is_better = "cost_per_result", True
        candidate_rows = cost_rows
        value_of = lambda r: r["result"]["cost_per_result"]
        result_label = candidate_rows[0]["result"].get("label") or t("placement.result_label.default")
    elif len(ctr_rows) >= MIN_PLACEMENTS_TO_COMPARE:
        metric_used, lower_is_better = "ctr", False
        candidate_rows = ctr_rows
        value_of = lambda r: r["metrics"]["ctr"]
        result_label = "CTR"
    elif len(cpm_rows) >= MIN_PLACEMENTS_TO_COMPARE:
        metric_used, lower_is_better = "cpm", True
        candidate_rows = cpm_rows
        value_of = lambda r: r["metrics"]["cpm"]
        result_label = "CPM"
    else:
        return {
            "available": False,
            "metric_used": None,
            "best": None,
            "worst": None,
            "ranked": [],
            "note": t("placement.note.no_metrics"),
        }

    ranked = sorted(candidate_rows, key=value_of, reverse=not lower_is_better)
    best, worst = ranked[0], ranked[-1]
    best_val, worst_val = value_of(best), value_of(worst)

    diff_pct = None
    if worst_val:
        diff_pct = round(abs(worst_val - best_val) / worst_val * 100, 1)

    note = None
    if best["label"] == worst["label"]:
        note = t("placement.note.only_one_placement")
    elif diff_pct is not None and diff_pct < INSIGNIFICANT_DIFF_PCT:
        note = t("placement.note.small_diff", diff_pct=diff_pct)

    return {
        "available": True,
        "metric_used": metric_used,
        "result_label": result_label,
        "best": {"label": best["label"], "value": round(best_val, 2), "impressions": best["metrics"]["impressions"]},
        "worst": {"label": worst["label"], "value": round(worst_val, 2), "impressions": worst["metrics"]["impressions"]},
        "diff_pct": diff_pct,
        "ranked": [{"label": r["label"], "value": round(value_of(r), 2), "impressions": r["metrics"]["impressions"]} for r in ranked],
        "note": note,
    }
