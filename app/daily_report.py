"""
Ежедневный отчёт по активной рекламе (пункт D ТЗ) — "ключевые цифры + рекомендации, без воды".

Осознанное решение: рекомендации здесь считаются локально (правила поверх тех же вердиктов
KPI, что и в ads_kpi.py), а не через Claude Opus (см. ads_opus.py) — этот отчёт может собираться
автоматически каждый день по расписанию, и дёргать платный LLM-вызов без участия пользователя
для каждого клиента/кабинета — неоправданный расход. Глубокие стратегические рекомендации
с Opus остаются в разделе "Реклама" -> "Рекомендации", где пользователь запускает это осознанно.

Снимок за день хранится в data/daily_stats_history.json, ключ — календарная дата (локальное
время машины, YYYY-MM-DD). Повторный сбор в тот же день перезаписывает снимок этого дня —
это осознанно (данные за "сегодня" дозревают в течение дня, поздний снимок точнее раннего).
"""
import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime, timezone

from app.ads_api import (
    AdsAPIError,
    DEFAULT_PERIOD,
    build_time_range_params,
    extract_result_metric,
    format_metrics_row,
    objective_label,
)
from app.ads_api import fetch_insights_by_level, fetch_structure
from app.ads_kpi import compute_kpi_verdicts, load_kpi_targets
from app.i18n import t
from app.project_store import get_effective_config, get_project, project_data_dir

logger = logging.getLogger("reels_dashboard")

_lock = threading.Lock()

ACTIVE_STATUSES = {"ACTIVE"}


def _history_path(project_id: str = None) -> str:
    return os.path.join(project_data_dir(project_id), "daily_stats_history.json")


def load_history(project_id: str = None) -> list:
    path = _history_path(project_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("daily_stats_history.json повреждён (%s) — история недоступна", e)
        return []
    days = data.get("days", [])
    return sorted(days, key=lambda d: d.get("date", ""), reverse=True)


def _save_history(days: list, project_id: str = None):
    path = _history_path(project_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".daily_stats_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"days": days}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def render_recommendation(code, params: dict = None) -> str:
    """Рендерит текст рекомендации из lang-независимого кода+параметров на ТЕКУЩЕМ языке
    интерфейса. Код+параметры (а не готовый текст) — то, что реально хранится в снимке
    (см. collect_daily_snapshot ниже), потому что снимок может быть собран планировщиком
    в фоне (app/scheduler.py, нет X-Lang заголовка -> всегда 'ru' на момент сбора). Если бы
    хранился готовый текст, история отчётов навсегда застревала бы на языке сбора — вместо
    этого routes/reports.py вызывает render_recommendation() заново при каждой отдаче истории."""
    if not code:
        return None
    return t(code, **(params or {}))


def _recommendation_for_campaign(objective: str, metrics: dict, result: dict, verdicts: list):
    """Возвращает (code, params) — без общих фраз, только по фактам этой кампании."""
    fails = [v for v in verdicts if v["verdict"] == "fail"]
    successes = [v for v in verdicts if v["verdict"] == "success"]

    if not verdicts:
        # Нет заданных KPI-целей для этой цели кампании — честно говорим это, а не молчим.
        if result.get("value") is None:
            return "reports.msg.rec_no_kpi_no_result", {}
        return "reports.msg.rec_no_kpi", {}

    if fails:
        names = ", ".join(v["metric"] for v in fails)
        return "reports.msg.rec_below_target", {"names": names}

    if successes and not fails:
        names = ", ".join(v["metric"] for v in successes)
        return "reports.msg.rec_on_target", {"names": names}

    return "reports.msg.rec_partial", {}


def build_daily_report(project_id: str = None, period: str = "today", include_ads: bool = False) -> dict:
    """Строит срез по активной рекламе на текущий момент. Не сохраняет — только считает.
    Честно возвращает {"error": "..."} вместо выдумывания данных, если ключи/кабинет не заданы.

    project_id — явно указанный проект (используется планировщиком, который должен пройтись
    по ВСЕМ проектам, а не только активному); None = текущий активный (запросы из UI).

    period — по умолчанию "today", как и раньше (нужно для дневного снимка в истории —
    collect_daily_snapshot(), сравнение по календарным дням не имеет смысла ни для какого
    другого периода). Напарник (app/companion.py) явно передаёт DEFAULT_PERIOD ("maximum") —
    тот же период, что и карточка объявления по умолчанию, — чтобы не называть по одному и
    тому же объявлению другие цифры, чем видит пользователь на вкладке «Реклама».

    include_ads — если True, дополнительно считает результат по каждому отдельному активному
    объявлению (та же extract_result_metric, тот же period) — без этого Напарник в принципе
    не может точно назвать цифры по конкретному объявлению, а не по кампании целиком (кампания
    almost всегда объединяет несколько объявлений, поэтому даже при совпадении периода её
    тотал не равен числу на карточке одного объявления)."""
    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    token = cfg.get("ig_access_token")
    account_id = cfg.get("ads_account_id")

    if not token or not account_id:
        return {"error": t("reports.msg.no_token_or_account")}

    try:
        campaigns = fetch_structure(token, account_id)
    except AdsAPIError as e:
        return {"error": t("reports.msg.structure_fetch_failed", error=e)}

    active_campaigns = [c for c in campaigns if c.get("effective_status") in ACTIVE_STATUSES]

    if not active_campaigns:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": date.today().isoformat(),
            "period": period,
            "campaigns": [],
            "ads": [],
            "totals": {"spend": 0, "campaigns_count": 0},
            "note_code": "reports.msg.no_active_campaigns",
            "note": t("reports.msg.no_active_campaigns"),
        }

    try:
        time_range_params = build_time_range_params(period)
        rows_by_id, unsupported = fetch_insights_by_level(token, account_id, "campaign", time_range_params)
    except AdsAPIError as e:
        if period == "today":
            return {"error": t("reports.msg.today_stats_fetch_failed", error=e)}
        return {"error": t("reports.msg.period_stats_fetch_failed", period=period, error=e)}

    kpi_targets_all = load_kpi_targets(project_id)
    no_data_code = "reports.msg.no_data_today" if period == "today" else "ads.msg.no_data_for_period"

    campaign_reports = []
    total_spend = 0.0
    had_spend = False

    for campaign in active_campaigns:
        cid = campaign["id"]
        objective = campaign.get("objective")
        row = rows_by_id.get(cid)

        if row is None:
            campaign_reports.append({
                "id": cid,
                "name": campaign.get("name", ""),
                "objective": objective,
                "objective_label": objective_label(objective),
                "metrics": None,
                "result": None,
                "verdicts": [],
                "recommendation_code": no_data_code,
                "recommendation_params": {},
                "recommendation": t(no_data_code),
            })
            continue

        metrics = format_metrics_row(row)
        result = extract_result_metric(objective, row)
        targets = kpi_targets_all.get(objective)
        verdicts = compute_kpi_verdicts(metrics, result, targets) if targets else []
        rec_code, rec_params = _recommendation_for_campaign(objective, metrics, result, verdicts)

        if metrics.get("spend"):
            total_spend += metrics["spend"]
            had_spend = True

        campaign_reports.append({
            "id": cid,
            "name": campaign.get("name", ""),
            "objective": objective,
            "objective_label": objective_label(objective),
            "metrics": metrics,
            "result": result,
            "verdicts": verdicts,
            "recommendation_code": rec_code,
            "recommendation_params": rec_params,
            "recommendation": render_recommendation(rec_code, rec_params),
        })

    ad_reports = []
    ads_error = None
    if include_ads:
        try:
            ad_rows, ad_unsupported = fetch_insights_by_level(token, account_id, "ad", time_range_params)
        except AdsAPIError as e:
            ad_rows, ad_unsupported = {}, {}
            ads_error = str(e)
        else:
            for campaign in active_campaigns:
                objective = campaign.get("objective")
                for adset in campaign.get("_adsets", []):
                    for ad in adset.get("_ads", []):
                        ad_row = ad_rows.get(ad["id"])
                        if ad_row is None:
                            continue
                        ad_reports.append({
                            "id": ad["id"],
                            "name": ad.get("name", ""),
                            "campaign_name": campaign.get("name", ""),
                            "objective": objective,
                            "objective_label": objective_label(objective),
                            "metrics": format_metrics_row(ad_row),
                            "result": extract_result_metric(objective, ad_row),
                        })
            if ad_unsupported:
                ads_error = "; ".join(ad_unsupported.values())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date.today().isoformat(),
        "period": period,
        "campaigns": campaign_reports,
        "ads": ad_reports,
        "ads_error": ads_error,
        "totals": {
            "spend": round(total_spend, 2) if had_spend else None,
            "campaigns_count": len(active_campaigns),
        },
        "unsupported_fields": unsupported or None,
    }


def collect_daily_snapshot(project_id: str = None) -> dict:
    """Строит отчёт и сохраняет его в историю — используется и кнопкой, и планировщиком
    (который вызывает это для каждого проекта отдельно, см. app/scheduler.py)."""
    report = build_daily_report(project_id)
    if "error" in report:
        logger.warning("Сбор дневного отчёта не удался: %s", report["error"])
        return report

    days = load_history(project_id)
    days = [d for d in days if d.get("date") != report["date"]]
    days.append(report)
    _save_history(days, project_id)
    logger.info("Дневной отчёт за %s сохранён (%d активных кампаний)", report["date"], report["totals"]["campaigns_count"])
    return report
