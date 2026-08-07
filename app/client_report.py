"""
Звіт для клієнта (Фаза 7) — на відміну від daily_report.py/past_campaigns_report.py (внутрішні
таблиці цифр для власника), це самостійний артефакт "звіт за період X", який відправляють
КЛІЄНТУ, побудований за методикою "факт без прикрас -> причини -> воронка -> що вже
протестовано -> план на наступний період -> просте пояснення для бізнесу": витрати/результати/
CPL-CPA/CTR/охоплення в порівнянні з ПОПЕРЕДНІМ періодом такої ж довжини, розбір по воронці
(покази->охоплення->CTR/кліки->результат), нові креативи/аудиторії, запущені за період
(_collect_tested_changes — факт зі структури кабінету, а не вигадка Opus), найкраще й найгірше
крео, топ органічних рілсів за період, і короткий висновок + план на наступний період від Opus
(у стилі власника, див. app/style_profile.py + app/ads_opus.py:build_client_report_prompt).

Тип звіту (report_type) — "daily" (учора), "weekly" (останні 7 днів) або "custom" (довільний
від-до) — визначає лише межі періоду (_resolve_range); і активна, і неактивна реклама кабінету
завжди в звіті (fetch_structure без фільтра по effective_status).

Зберігається по одному рядку ProjectData на звіт (не rolling history, як daily_report.py) —
поруч кешується PDF окремим рядком (base64), щоб повторне завантаження не смикало Opus повторно
(app/client_report_pdf.py рахує PDF лише один раз, тут — лише читання/запис байтів).
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from app.ads_api import (
    AdsAPIError,
    build_time_range_params,
    campaign_optimization_goal,
    extract_result_metric,
    fetch_insights_by_level,
    fetch_structure,
    format_metrics_row,
    objective_label,
)
from app.ads_placement import INSIGNIFICANT_DIFF_PCT
from app.analysis import compute_organic_analysis
from app.i18n import current_lang, t
from app.project_data_store import delete_key, get_bytes, get_json, list_json_by_prefix, set_bytes, set_json
from app.project_store import get_active_project, get_effective_config
from app.style_profile import load_style_profile

logger = logging.getLogger("reels_dashboard")

MIN_ADS_TO_COMPARE = 2

# Один рядок ProjectData на звіт (key="report:<id>") + окремий рядок з кешованим PDF
# (key="report_pdf:<id>", base64) — заміна файлів data/projects/<id>/reports/<id>.json/.pdf.
_REPORT_KEY_PREFIX = "report:"
_REPORT_PDF_KEY_PREFIX = "report_pdf:"


def _report_key(report_id: str) -> str:
    return f"{_REPORT_KEY_PREFIX}{report_id}"


def _report_pdf_key(report_id: str) -> str:
    return f"{_REPORT_PDF_KEY_PREFIX}{report_id}"


def _resolve_range(report_type: str, date_from: str = None, date_to: str = None):
    """Межі поточного періоду + межі періоду порівняння (щойно попередній відрізок такої ж
    довжини) — основа "факт без прикрас: порівняно з яким періодом, наскільки" з методики
    звіту (Фаза 7). ДЕННИЙ = учора, ТИЖНЕВИЙ = останні 7 завершених днів (учора і 6 днів до
    того) — те саме "сьогоднішні дані ще не дозріли", що й у ДЕННОГО, лише на довшому вікні.

    Раніше ТИЖНЕВИЙ рахував until=сьогодні (включно з ще не завершеною добою), тоді як ручний
    вибір тих самих "останніх 7 днів" в UI (custom-період) означає 7 завершених днів. Insights
    Meta за поточну, ще не завершену добу можуть повертати порожньо — з until=сьогодні це іноді
    гасило ВЕСЬ запит (а не лише сьогоднішній рядок), і звіт виглядав порожнім там, де ручний
    custom з тими самими на вигляд "7 днями" (але завершеними) чесно повертав дані."""
    today = date.today()
    if report_type == "daily":
        since = until = today - timedelta(days=1)
    elif report_type == "weekly":
        until = today - timedelta(days=1)
        since = until - timedelta(days=6)
    elif report_type == "custom":
        if not date_from or not date_to:
            raise AdsAPIError(t("ads.msg.custom_period_needs_dates"))
        try:
            since = datetime.strptime(date_from, "%Y-%m-%d").date()
            until = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            raise AdsAPIError(t("ads.msg.custom_period_needs_dates"))
    else:
        raise AdsAPIError(t("reports.client.msg.unknown_report_type", report_type=report_type))

    length_days = (until - since).days + 1
    prev_until = since - timedelta(days=1)
    prev_since = prev_until - timedelta(days=length_days - 1)
    return since, until, prev_since, prev_until


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


def _parse_meta_dt(ts):
    """Meta повертає ISO8601 без двокрапки в офсеті ("...+0200") — fromisoformat на старіших
    Python це не приймає, тому нормалізуємо офсет перед парсингом."""
    if not ts:
        return None
    s = ts.strip()
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# Поріг показів, нижче якого тест вважається "запустили і майже одразу зупинили" — шум, а
# не сигнал. Секція "що вже протестовано" має показувати суть (те, що реально встигло
# попрацювати), а не повний список усього створеного за період, включно з тим, що майже
# не покрутилось (0 витрат чи кілька показів).
MIN_TESTED_IMPRESSIONS = 100


def _collect_tested_changes(campaigns: list, since: date, until: date, adset_rows: dict, ad_rows: dict):
    """Нові аудиторії (adset.start_time) і нові креативи (ad.created_time), запущені в межах
    періоду звіту, — і які РЕАЛЬНО встигли попрацювати: назбирали помітний обсяг показів і
    мали витрати (MIN_TESTED_IMPRESSIONS). Тест, який лише завели, а не встиг покрутитись,
    у "що вже протестовано" не потрапляє — це шум, не сигнал для клієнта.

    Дедуплікація по id (не по імені) — той самий adset/ad не з'явиться в списку двічі, навіть
    якщо структура кабінету якимось чином віддала його в межах кількох кампаній ітерації."""
    since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    until_dt = datetime(until.year, until.month, until.day, tzinfo=timezone.utc) + timedelta(days=1)

    new_adsets, new_ads = [], []
    seen_adset_ids, seen_ad_ids = set(), set()
    for campaign in campaigns:
        objective = campaign.get("objective")
        for adset in campaign.get("_adsets", []):
            adset_id = adset.get("id")
            adset_opt_goal = adset.get("optimization_goal")
            dt = _parse_meta_dt(adset.get("start_time"))
            if dt and since_dt <= dt < until_dt and adset_id not in seen_adset_ids:
                row = adset_rows.get(adset_id)
                metrics = format_metrics_row(row) if row else None
                if metrics and (metrics.get("spend") or 0) > 0 and (metrics.get("impressions") or 0) >= MIN_TESTED_IMPRESSIONS:
                    seen_adset_ids.add(adset_id)
                    new_adsets.append({
                        "name": adset.get("name", ""),
                        "campaign_name": campaign.get("name", ""),
                        "start_time": adset.get("start_time"),
                        "metrics": metrics,
                        "result": extract_result_metric(objective, row, adset_opt_goal),
                    })
            for ad in adset.get("_ads", []):
                ad_id = ad.get("id")
                dt2 = _parse_meta_dt(ad.get("created_time"))
                if dt2 and since_dt <= dt2 < until_dt and ad_id not in seen_ad_ids:
                    row = ad_rows.get(ad_id)
                    metrics = format_metrics_row(row) if row else None
                    if metrics and (metrics.get("spend") or 0) > 0 and (metrics.get("impressions") or 0) >= MIN_TESTED_IMPRESSIONS:
                        seen_ad_ids.add(ad_id)
                        new_ads.append({
                            "name": ad.get("name", ""),
                            "campaign_name": campaign.get("name", ""),
                            "adset_name": adset.get("name", ""),
                            "created_time": ad.get("created_time"),
                            "metrics": metrics,
                            "result": extract_result_metric(objective, row, adset_opt_goal),
                        })
    return new_adsets, new_ads


def _pct_change(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 1)


def _delta_pct_text(curr, prev) -> str:
    pct = _pct_change(curr, prev)
    return f"{pct:+.1f}%" if pct is not None else t("reports.client.no_comparison")


def _fallback_main_fact(totals: dict, prev_totals: dict) -> str:
    """Без Anthropic-ключа (чи якщо виклик Opus не вдався) ПІДСУМОК все одно не порожній —
    головний факт рахується напряму з цифр, без AI: витрати і головний результат періоду
    з дельтою до попереднього періоду."""
    spend_line = f"{t('reports.client.spend')}: {_fmt(totals.get('spend'))} ({_delta_pct_text(totals.get('spend'), prev_totals.get('spend'))})"
    results = totals.get("results") or []
    if results:
        r = results[0]
        prev_by_label = {pr["label"]: pr for pr in (prev_totals.get("results") or [])}
        prev_r = prev_by_label.get(r["label"])
        prev_val = prev_r["value"] if prev_r else None
        return f"{spend_line}, «{r['label']}»: {r['value']} ({_delta_pct_text(r['value'], prev_val)})."
    return f"{spend_line}."


def _build_funnel(totals: dict, prev_totals: dict) -> list:
    """Розбір по воронці (покази -> охоплення -> кліки -> заявки/продажі), кожен етап з
    порівнянням до попереднього періоду — щоб було видно, ДЕ саме просіло, а не тільки що
    підсумок гірший."""
    stage_defs = [
        ("impressions", t("reports.client.funnel.impressions")),
        ("reach", t("reports.client.funnel.reach")),
        ("clicks", t("reports.client.funnel.clicks")),
    ]
    funnel = [
        {
            "stage": key,
            "label": label,
            "value": totals.get(key),
            "prev_value": prev_totals.get(key),
            "change_pct": _pct_change(totals.get(key), prev_totals.get(key)),
        }
        for key, label in stage_defs
    ]
    prev_results_by_label = {r["label"]: r for r in (prev_totals.get("results") or [])}
    for r in totals.get("results") or []:
        prev_r = prev_results_by_label.get(r["label"])
        prev_val = prev_r["value"] if prev_r else None
        funnel.append({
            "stage": f"result:{r['label']}",
            "label": r["label"],
            "value": r["value"],
            "prev_value": prev_val,
            "change_pct": _pct_change(r["value"], prev_val),
        })
    return funnel


def _filter_posts_by_period(posts: list, since: date, until: date) -> list:
    since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    until_dt = datetime(until.year, until.month, until.day, tzinfo=timezone.utc) + timedelta(days=1)
    out = []
    for p in posts:
        dt = _parse_ts(p.get("timestamp"))
        if dt and since_dt <= dt < until_dt:
            out.append(p)
    return out


def _all_ads_with_metrics(campaigns: list, ad_rows: dict) -> list:
    """Плоский список оголошень з метриками за період — імена вже є в дереві fetch_structure()
    (campaign._adsets[]._ads[]), тому додаткових запитів не треба."""
    out = []
    for campaign in campaigns:
        objective = campaign.get("objective")
        for adset in campaign.get("_adsets", []):
            adset_opt_goal = adset.get("optimization_goal")
            for ad in adset.get("_ads", []):
                row = ad_rows.get(ad["id"])
                if not row:
                    continue
                out.append({
                    "id": ad["id"],
                    "name": ad.get("name", ""),
                    "campaign_name": campaign.get("name", ""),
                    "metrics": format_metrics_row(row),
                    "result": extract_result_metric(objective, row, adset_opt_goal),
                })
    return out


# Порівнювати ціну результату/CTR чесно можна лише на СПІВСТАВНОМУ обсязі показів — дешевий
# результат на жмені показів проти дорогого на тисячах не перемога, а шум (саме такий кейс,
# що ввів в оману: 100 показів проти 5000). Два пороги:
# - абсолютний: менше цього показів взагалі — оголошення не бере участі в порівнянні;
# - відносний: навіть вище абсолютного порогу, але в рази менше показів за найбільшого
#   кандидата в цій самій вибірці — інша "вагова категорія", чесно порівнювати не можна.
MIN_IMPRESSIONS_FOR_RANK = 500
VOLUME_COMPARABILITY_RATIO = 0.2


def _rank_ads(ads: list):
    """Той самий чесний ідіом, що ads_placement.compute_placement_verdict: пріоритет метрики
    cost_per_result -> ctr -> cpm (перша, де є достатньо оголошень з даними), сортуємо,
    перший/останній — найкраще/найгірше, і чесна нотатка, якщо різниця в межах шуму.

    ПЕРЕД цим — фільтр за обсягом (MIN_IMPRESSIONS_FOR_RANK, VOLUME_COMPARABILITY_RATIO):
    оголошення з явно малим чи явно неспівставним обсягом показів у ранжування взагалі не
    потрапляють, навіть якщо в них найдешевша ціна результату — маленька вибірка не доказ,
    а шум, і "перемога" на ній вводить в оману власника акаунта."""
    with_impressions = [a for a in ads if (a["metrics"] or {}).get("impressions")]
    eligible = [a for a in with_impressions if a["metrics"]["impressions"] >= MIN_IMPRESSIONS_FOR_RANK]

    if len(eligible) < MIN_ADS_TO_COMPARE:
        return None, None, t("reports.client.msg.not_enough_volume")

    max_impressions = max(a["metrics"]["impressions"] for a in eligible)
    comparable = [a for a in eligible if a["metrics"]["impressions"] >= max_impressions * VOLUME_COMPARABILITY_RATIO]

    if len(comparable) < MIN_ADS_TO_COMPARE:
        return None, None, t("reports.client.msg.not_enough_volume")

    excluded_count = len(ads) - len(comparable)

    cost_rows = [a for a in comparable if (a["result"] or {}).get("cost_per_result") is not None]
    ctr_rows = [a for a in comparable if (a["metrics"] or {}).get("ctr") is not None]
    cpm_rows = [a for a in comparable if (a["metrics"] or {}).get("cpm") is not None]

    if len(cost_rows) >= MIN_ADS_TO_COMPARE:
        metric_used, lower_is_better, candidates = "cost_per_result", True, cost_rows
        value_of = lambda a: a["result"]["cost_per_result"]
    elif len(ctr_rows) >= MIN_ADS_TO_COMPARE:
        metric_used, lower_is_better, candidates = "ctr", False, ctr_rows
        value_of = lambda a: a["metrics"]["ctr"]
    elif len(cpm_rows) >= MIN_ADS_TO_COMPARE:
        metric_used, lower_is_better, candidates = "cpm", True, cpm_rows
        value_of = lambda a: a["metrics"]["cpm"]
    else:
        return None, None, t("reports.client.msg.not_enough_ads")

    ranked = sorted(candidates, key=value_of, reverse=not lower_is_better)
    best, worst = ranked[0], ranked[-1]
    best_val, worst_val = value_of(best), value_of(worst)
    diff_pct = round(abs(worst_val - best_val) / worst_val * 100, 1) if worst_val else None

    note = None
    if best["id"] == worst["id"]:
        note = t("reports.client.msg.only_one_ad")
    elif diff_pct is not None and diff_pct < INSIGNIFICANT_DIFF_PCT:
        note = t("placement.note.small_diff", diff_pct=diff_pct)
    if excluded_count:
        volume_note = t("reports.client.msg.excluded_low_volume", count=excluded_count)
        note = f"{note} {volume_note}" if note else volume_note

    best_out = {**best, "metric_used": metric_used, "value": round(best_val, 2),
                "impressions": best["metrics"]["impressions"]}
    worst_out = {**worst, "metric_used": metric_used, "value": round(worst_val, 2),
                 "impressions": worst["metrics"]["impressions"]}
    return best_out, worst_out, note


# Частота, з якої вважаємо, що аудиторія вже "перегріта" одним і тим же креативом (типовий
# орієнтир для Reels/Stories — вище цього людина бачить один і той же ролик надто часто).
FATIGUE_FREQUENCY = 3.0
# Просадка CTR до попереднього періоду (у %), після якої висока частота — це вже "втома
# креативу", а не випадковий шум.
FATIGUE_CTR_DROP_PCT = -15.0
# Кампанія дорожча за найдешевшу в 1.8+ раза — це і є "вдвічі дорожча" з методики звіту
# (не рівно x2, з невеликим запасом, щоб не чіплятися до 1.9 vs 2.0).
EXPENSIVE_RATIO_CUT = 1.8
# Дорожча на 30%+ від найдешевшої, але ще не "вдвічі" — вартує перегляду, різати зарано.
EXPENSIVE_RATIO_REVIEW = 1.3


def _campaign_verdicts(campaign_reports: list, prev_campaigns_by_id: dict):
    """Короткий вердикт (причина -> дія) для кожної кампанії — "журнал"-стиль зі структури
    Антона: не просто цифри, а що з ними робити. Правило-базовано (не Opus), щоб вердикт завжди
    був доступний, детермінований і не залежав від Anthropic-ключа.

    Втома креативу (висока частота + просадка CTR до попереднього періоду) має пріоритет над
    ціною результату — втомлений крео псує економіку, навіть якщо кампанія поки формально
    найдешевша. Далі — найдешевша/найдорожча за ціною результату серед кампаній, де вона
    порахована; кампанії без результату за період чесно позначені "недостатньо даних", а не
    мовчки пропущені."""
    cost_rows = [c for c in campaign_reports if (c.get("result") or {}).get("cost_per_result") is not None]
    best_cost = min((c["result"]["cost_per_result"] for c in cost_rows)) if len(cost_rows) >= MIN_ADS_TO_COMPARE else None

    for c in campaign_reports:
        m = c.get("metrics") or {}
        r = c.get("result") or {}
        prev_m = (prev_campaigns_by_id.get(c["id"]) or {}).get("metrics") or {}
        frequency = m.get("frequency")
        ctr_change = _pct_change(m.get("ctr"), prev_m.get("ctr"))

        if frequency is not None and frequency >= FATIGUE_FREQUENCY and ctr_change is not None and ctr_change <= FATIGUE_CTR_DROP_PCT:
            c["verdict"] = {"code": "fatigue", "text": t("reports.client.verdict.fatigue", frequency=frequency, ctr_change=ctr_change)}
            continue

        cost = r.get("cost_per_result")
        if cost is None:
            c["verdict"] = {"code": "no_data", "text": t("reports.client.verdict.no_data")}
            continue
        if best_cost is None:
            c["verdict"] = {"code": "only_one", "text": t("reports.client.verdict.only_one")}
            continue

        ratio = cost / best_cost if best_cost else None
        if ratio is not None and ratio <= 1.0 + 1e-9:
            c["verdict"] = {"code": "cheapest", "text": t("reports.client.verdict.cheapest", result_label=r.get("label") or "", cost=cost)}
        elif ratio is not None and ratio >= EXPENSIVE_RATIO_CUT:
            c["verdict"] = {"code": "expensive_cut", "text": t("reports.client.verdict.expensive_cut", cost=cost, best_cost=best_cost)}
        elif ratio is not None and ratio >= EXPENSIVE_RATIO_REVIEW:
            c["verdict"] = {"code": "expensive_review", "text": t("reports.client.verdict.expensive_review", pct=round((ratio - 1) * 100))}
        else:
            c["verdict"] = {"code": "in_range", "text": t("reports.client.verdict.in_range")}


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return t("common.no_data")
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _aggregate(campaigns: list, rows_by_id: dict):
    """Кампанії + підсумки за один період — окрема функція, бо звіту (Фаза 7) потрібно
    порахувати це двічі: для поточного періоду (з розбивкою по кампаніях) і для періоду
    порівняння (тільки підсумки, для funnel/дельт)."""
    campaign_reports = []
    total_spend = 0.0
    total_impressions = 0.0
    total_reach = 0.0
    total_clicks = 0.0
    result_groups = {}

    for campaign in campaigns:
        cid = campaign["id"]
        objective = campaign.get("objective")
        row = rows_by_id.get(cid)
        metrics = format_metrics_row(row) if row else None
        result = extract_result_metric(objective, row, campaign_optimization_goal(campaign)) if row else None

        if metrics:
            total_spend += metrics.get("spend") or 0
            total_impressions += metrics.get("impressions") or 0
            total_reach += metrics.get("reach") or 0
            total_clicks += metrics.get("clicks") or 0

        if result and result.get("label") and result.get("value") is not None:
            group = result_groups.setdefault(result["label"], {"value": 0.0, "spend": 0.0})
            group["value"] += result["value"]
            group["spend"] += (metrics or {}).get("spend") or 0

        campaign_reports.append({
            "id": cid,
            "name": campaign.get("name", ""),
            "objective": objective,
            "objective_label": objective_label(objective),
            "metrics": metrics,
            "result": result,
        })

    results_summary = [
        {
            "label": label,
            "value": round(g["value"], 2),
            "cost_per_result": round(g["spend"] / g["value"], 2) if g["value"] else None,
        }
        for label, g in result_groups.items()
    ]

    totals = {
        "spend": round(total_spend, 2) if campaign_reports else None,
        "impressions": round(total_impressions, 2) if total_impressions else None,
        "reach": round(total_reach, 2) if total_reach else None,
        "clicks": round(total_clicks, 2) if total_clicks else None,
        "ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions else None,
        "cpm": round(total_spend / total_impressions * 1000, 2) if total_impressions else None,
        # Загальна частота — саме impressions/reach за весь період, а не середнє по кампаніях
        # (частота по кампаніях НЕ додається лінійно, як spend/impressions).
        "frequency": round(total_impressions / total_reach, 2) if total_reach else None,
        "results": results_summary,
    }
    return campaign_reports, totals


def _build_context_text(
    project_name, niche, report_type, date_from, date_to, prev_date_from, prev_date_to,
    totals, prev_totals, funnel, campaign_reports, best_ad, worst_ad, ad_note, top_reels,
    new_adsets, new_ads,
) -> str:
    lines = [
        f"Клиент/проект: «{project_name}»",
        f"Ниша/тематика: {niche or 'нет данных'}",
        f"Тип отчёта: {report_type} ({date_from} — {date_to})",
        f"Период сравнения (сразу предыдущий отрезок такой же длины): {prev_date_from} — {prev_date_to}",
        "",
        "ИТОГИ ЗА ПЕРИОД (текущий период / предыдущий период):",
        f"Расход: {_fmt(totals['spend'])} / {_fmt(prev_totals['spend'])}",
        f"Показы: {_fmt(totals['impressions'])} / {_fmt(prev_totals['impressions'])}",
        f"Охват: {_fmt(totals['reach'])} / {_fmt(prev_totals['reach'])}",
        f"CTR: {_fmt(totals['ctr'], '%')} / {_fmt(prev_totals['ctr'], '%')}",
        f"CPM: {_fmt(totals['cpm'])} / {_fmt(prev_totals['cpm'])}",
        f"Частота: {_fmt(totals.get('frequency'))} / {_fmt(prev_totals.get('frequency'))}",
    ]
    if totals["results"]:
        prev_by_label = {r["label"]: r for r in (prev_totals.get("results") or [])}
        for r in totals["results"]:
            prev_r = prev_by_label.get(r["label"])
            prev_line = f" (было: {prev_r['value']}, цена {_fmt(prev_r['cost_per_result'])})" if prev_r else " (в предыдущем периоде данных нет)"
            lines.append(f"Результат «{r['label']}»: {r['value']} (цена результата: {_fmt(r['cost_per_result'])}){prev_line}")
    else:
        lines.append("Результаты: нет данных за период")

    lines.append("")
    lines.append("ВОРОНКА ПО ЭТАПАМ (текущее значение -> предыдущее, изменение %) — используй, чтобы указать, ГДЕ именно просело:")
    for f in funnel:
        change = f"{f['change_pct']:+.1f}%" if f["change_pct"] is not None else "нет данных для сравнения"
        lines.append(f"- {f['label']}: {_fmt(f['value'])} -> {_fmt(f['prev_value'])} ({change})")

    lines.append("")
    lines.append("КАМПАНИИ (вердикт уже посчитан по цифрам — используй его как готовый факт, не переизобретай):")
    for c in campaign_reports:
        m = c["metrics"] or {}
        r = c["result"] or {}
        verdict_text = (c.get("verdict") or {}).get("text", "")
        lines.append(
            f"- «{c['name']}» ({c['objective_label']}): расход {_fmt(m.get('spend'))}, "
            f"CTR {_fmt(m.get('ctr'), '%')}, частота {_fmt(m.get('frequency'))}, "
            f"результат {r.get('label') or 'нет данных'} = {_fmt(r.get('value'))} "
            f"(цена {_fmt(r.get('cost_per_result'))}) — вердикт: {verdict_text}"
        )

    lines.append("")
    if best_ad and worst_ad:
        lines.append(
            f"Лучшее объявление (уже отфильтровано по объёму — сравнивалось только с объявлениями "
            f"сопоставимого объёма показов): «{best_ad['name']}» ({best_ad['campaign_name']}) — "
            f"{best_ad['metric_used']}: {best_ad['value']}, показов: {_fmt(best_ad.get('impressions'))}"
        )
        lines.append(
            f"Худшее объявление: «{worst_ad['name']}» ({worst_ad['campaign_name']}) — "
            f"{worst_ad['metric_used']}: {worst_ad['value']}, показов: {_fmt(worst_ad.get('impressions'))}"
        )
        if ad_note:
            lines.append(f"Примечание: {ad_note}")
    else:
        lines.append(f"Сравнение объявлений: {ad_note}")

    lines.append("")
    lines.append("ЧТО УЖЕ ПРОТЕСТИРОВАНО ЗА ЭТОТ ПЕРИОД (уже отфильтровано — только то, что реально набрало заметный объём показов; используй для раздела «что уже тестировали» — НЕ выдумывай тесты сверх этого списка):")
    if new_adsets or new_ads:
        for a in new_adsets:
            r = a.get("result") or {}
            result_txt = f"{r['label']}: {r['value']} (цена {_fmt(r.get('cost_per_result'))})" if r.get("value") is not None else "результата по этой цели нет"
            lines.append(f"- Новая аудитория/группа объявлений: «{a['name']}» (кампания «{a['campaign_name']}», запущена {a['start_time'][:10]}) — {result_txt}")
        for a in new_ads:
            r = a.get("result") or {}
            result_txt = f"{r['label']}: {r['value']} (цена {_fmt(r.get('cost_per_result'))})" if r.get("value") is not None else "результата по этой цели нет"
            lines.append(f"- Новый креатив: «{a['name']}» (кампания «{a['campaign_name']}», группа «{a['adset_name']}», создан {a['created_time'][:10]}) — {result_txt}")
    else:
        lines.append("За этот период не было креативов/аудиторий, которые набрали заметный объём показов — честно скажи это, а не выдумывай тесты.")

    lines.append("")
    if top_reels:
        lines.append("ТОП ОРГАНИЧЕСКИХ РИЛСОВ ЗА ПЕРИОД:")
        for p in top_reels:
            lines.append(f"- «{p['caption']}»: ER {p['engagement_rate']}%, охват {p['reach']}")
    else:
        lines.append("Топ органических рилсов за период: нет данных (не публиковались/не собраны рилсы за этот период)")

    return "\n".join(lines)


def build_client_report(report_type: str, date_from: str = None, date_to: str = None) -> dict:
    """Рахує звіт за період для АКТИВНОГО проєкту (ДЕННИЙ/ТИЖНЕВИЙ/довільний, з порівнянням
    до попереднього періоду такої ж довжини), кличе Opus за висновком+планом, зберігає
    результат. Чесно повертає {"error": "..."}, якщо ключі/кабінет не задані.

    Кампанії тягнуться через fetch_structure() без фільтра по effective_status — і активна,
    і неактивна реклама кабінету потрапляє у звіт, як того вимагає методика (на відміну від
    daily_report.py, який навмисно показує лише ACTIVE для щоденного операційного зрізу)."""
    project = get_active_project()
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    account_id = cfg.get("ads_account_id")
    niche = cfg.get("account_niche") or ""
    anthropic_key = cfg.get("anthropic_api_key")
    project_name = project.get("name") if project else ""

    if not token or not account_id:
        return {"error": t("reports.client.msg.no_token_or_account")}

    try:
        since, until, prev_since, prev_until = _resolve_range(report_type, date_from, date_to)
        time_range_params = build_time_range_params("custom", since.isoformat(), until.isoformat())
        prev_time_range_params = build_time_range_params("custom", prev_since.isoformat(), prev_until.isoformat())

        campaigns = fetch_structure(token, account_id)
        campaign_rows, _unsupported = fetch_insights_by_level(token, account_id, "campaign", time_range_params)
        ad_rows, _unsupported_ads = fetch_insights_by_level(token, account_id, "ad", time_range_params)
        adset_rows, _unsupported_adsets = fetch_insights_by_level(token, account_id, "adset", time_range_params)
        prev_campaign_rows, _unsupported_prev = fetch_insights_by_level(token, account_id, "campaign", prev_time_range_params)
    except AdsAPIError as e:
        return {"error": str(e)}

    campaign_reports, totals = _aggregate(campaigns, campaign_rows)
    prev_campaign_reports, prev_totals = _aggregate(campaigns, prev_campaign_rows)
    funnel = _build_funnel(totals, prev_totals)

    prev_campaigns_by_id = {c["id"]: c for c in prev_campaign_reports}
    _campaign_verdicts(campaign_reports, prev_campaigns_by_id)

    ads_with_metrics = _all_ads_with_metrics(campaigns, ad_rows)
    best_ad, worst_ad, ad_note = _rank_ads(ads_with_metrics)

    new_adsets, new_ads = _collect_tested_changes(campaigns, since, until, adset_rows, ad_rows)

    posts = []
    try:
        from app.routes.metrics import load_cache

        posts = load_cache().get("posts", [])
    except Exception:
        logger.exception("Звіт для клієнта: не вдалося прочитати media_cache.json")

    organic_posts = _filter_posts_by_period([p for p in posts if not p.get("is_ad")], since, until)
    organic_analysis = compute_organic_analysis(organic_posts)
    top_reels = organic_analysis.get("top_er", []) if not organic_analysis.get("insufficient_data") else []

    context_text = _build_context_text(
        project_name, niche, report_type, since.isoformat(), until.isoformat(),
        prev_since.isoformat(), prev_until.isoformat(),
        totals, prev_totals, funnel, campaign_reports, best_ad, worst_ad, ad_note, top_reels,
        new_adsets, new_ads,
    )

    summary, opus_note = {}, None
    if not anthropic_key:
        opus_note = t("reports.client.msg.no_anthropic_key")
        summary = {"main_fact": _fallback_main_fact(totals, prev_totals)}
    else:
        try:
            from app.ads_opus import build_client_report_prompt, call_opus, parse_client_report_response

            style_profile = load_style_profile()
            system_prompt, user_message = build_client_report_prompt(context_text, style_profile, lang=current_lang())
            response_text = call_opus(anthropic_key, system_prompt, user_message, max_tokens=900)
            summary = parse_client_report_response(response_text)
            if not summary:
                # Opus не дотримався формату маркерів — чесніше показати сирий текст, ніж
                # мовчки лишити ПІДСУМОК порожнім.
                summary = {"main_fact": response_text.strip()}
        except Exception as e:
            logger.warning("Звіт для клієнта: виклик Opus не вдався (%s)", e)
            opus_note = t("reports.client.msg.opus_error", error=e)
            summary = {"main_fact": _fallback_main_fact(totals, prev_totals)}

    report = {
        "id": uuid.uuid4().hex[:12],
        "project_name": project_name,
        "niche": niche,
        "report_type": report_type,
        "period": report_type,
        "date_from": since.isoformat(),
        "date_to": until.isoformat(),
        "prev_date_from": prev_since.isoformat(),
        "prev_date_to": prev_until.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "prev_totals": prev_totals,
        "funnel": funnel,
        "campaigns": campaign_reports,
        "best_ad": best_ad,
        "worst_ad": worst_ad,
        "ad_note": ad_note,
        "top_reels": top_reels,
        "new_adsets": new_adsets,
        "new_ads": new_ads,
        "summary": summary,
        "opus_note": opus_note,
    }
    save_client_report(report)
    return report


def save_client_report(report: dict) -> dict:
    set_json(_report_key(report["id"]), report)
    return report


def load_client_reports() -> list:
    reports = list_json_by_prefix(_REPORT_KEY_PREFIX)
    reports.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
    return reports


def load_client_report(report_id: str):
    return get_json(_report_key(report_id), default=None)


def delete_client_report(report_id: str) -> bool:
    deleted = delete_key(_report_key(report_id))
    delete_key(_report_pdf_key(report_id))
    return deleted


def load_cached_pdf(report_id: str):
    return get_bytes(_report_pdf_key(report_id))


def save_cached_pdf(report_id: str, pdf_bytes: bytes):
    set_bytes(_report_pdf_key(report_id), pdf_bytes)
