"""
Отчёт по прошлым кампаниям — то же самое, что daily_report.py делает для активной рекламы
"за сегодня", но для произвольного периода (включая "maximum" — всё время) и БЕЗ фильтрации
по статусу кампании при получении данных: fetch_structure тянет кампании всех статусов
(ACTIVE/PAUSED/ARCHIVED/...) уже сама по себе, фильтрация происходит только здесь, на
уровне отображения — по явному выбору пользователя (активные/неактивные/все).

Meta не возвращает отдельного статуса "COMPLETED" — завершённая по факту (истёк бюджет
или stop_time) кампания у API всё ещё числится ACTIVE/PAUSED/ARCHIVED в зависимости от того,
остановил ли её пользователь вручную. Поэтому "неактивные" здесь = всё, что не ACTIVE —
самое честное деление без угадывания несуществующего в API статуса.

Рекомендации — тем же rule-based способом, что в daily_report.py (без автоматического
вызова Opus): отчёт может разом поднимать десятки прошлых кампаний, и дёргать платный
LLM на каждую без явного запроса пользователя было бы неоправданным расходом. Глубокий
разбор конкретной кампании с Opus — по-прежнему через «Реклама» → «Рекомендации».
"""
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone

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
from app.ads_kpi import compute_kpi_verdicts, load_kpi_targets
from app.i18n import t
from app.project_store import get_effective_config, project_data_dir

logger = logging.getLogger("reels_dashboard")

_lock = threading.Lock()


def _history_path() -> str:
    return os.path.join(project_data_dir(), "past_campaigns_history.json")

# История отчётов по прошлым кампаниям не привязана к календарной дате (в отличие от
# дневного отчёта) — пользователь может запускать её многократно за один день с разными
# периодами/фильтрами. Ограничиваем количество записей, чтобы файл не рос бесконечно.
MAX_HISTORY_ENTRIES = 50

STATUS_FILTERS = ("active", "inactive", "all")


def _matches_status_filter(effective_status: str, status_filter: str) -> bool:
    is_active = (effective_status or "").upper() == "ACTIVE"
    if status_filter == "active":
        return is_active
    if status_filter == "inactive":
        return not is_active
    return True


def render_recommendation(code, params: dict = None) -> str:
    """См. app.daily_report.render_recommendation — тот же приём: код+параметры хранятся
    в истории вместо готового текста, чтобы смена языка интерфейса не оставляла старые
    записи истории на другом языке (routes/reports.py перерендеривает при отдаче)."""
    if not code:
        return None
    return t(code, **(params or {}))


def _recommendation_for_campaign(verdicts: list, has_data: bool):
    """Возвращает (code, params)."""
    if not has_data:
        return "reports.past.msg.rec_no_data", {}

    if not verdicts:
        return "reports.past.msg.rec_no_kpi", {}

    fails = [v for v in verdicts if v["verdict"] == "fail"]
    successes = [v for v in verdicts if v["verdict"] == "success"]

    if fails:
        names = ", ".join(v["metric"] for v in fails)
        return "reports.past.msg.rec_below_target", {"names": names}
    if successes:
        names = ", ".join(v["metric"] for v in successes)
        return "reports.past.msg.rec_on_target", {"names": names}
    return "reports.past.msg.rec_partial", {}


def build_past_campaigns_report(status_filter: str, period: str, date_from: str = None, date_to: str = None) -> dict:
    """Считает, не сохраняет. Честно возвращает {"error": "..."} вместо выдумывания данных,
    если ключи/кабинет не заданы или Marketing API недоступен."""
    if status_filter not in STATUS_FILTERS:
        status_filter = "all"

    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    account_id = cfg.get("ads_account_id")
    if not token or not account_id:
        return {"error": t("reports.msg.no_token_or_account")}

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)
        campaigns = fetch_structure(token, account_id)
        campaign_insights, unsupported = fetch_insights_by_level(token, account_id, "campaign", time_range_params)
    except AdsAPIError as e:
        return {"error": str(e)}

    filtered = [c for c in campaigns if _matches_status_filter(c.get("effective_status"), status_filter)]

    kpi_targets_all = load_kpi_targets()
    campaign_reports = []
    total_spend = 0.0
    had_spend = False

    for campaign in filtered:
        cid = campaign["id"]
        objective = campaign.get("objective")
        row = campaign_insights.get(cid)

        base = {
            "id": cid,
            "name": campaign.get("name", ""),
            "status": campaign.get("status"),
            "effective_status": campaign.get("effective_status"),
            "objective": objective,
            "objective_label": objective_label(objective),
        }

        if row is None:
            rec_code, rec_params = _recommendation_for_campaign([], False)
            campaign_reports.append({
                **base,
                "metrics": None,
                "result": None,
                "verdicts": [],
                "recommendation_code": rec_code,
                "recommendation_params": rec_params,
                "recommendation": render_recommendation(rec_code, rec_params),
            })
            continue

        metrics = format_metrics_row(row)
        result = extract_result_metric(objective, row, campaign_optimization_goal(campaign))
        targets = kpi_targets_all.get(objective)
        verdicts = compute_kpi_verdicts(metrics, result, targets) if targets else []
        rec_code, rec_params = _recommendation_for_campaign(verdicts, True)

        if metrics.get("spend"):
            total_spend += metrics["spend"]
            had_spend = True

        campaign_reports.append({
            **base,
            "metrics": metrics,
            "result": result,
            "verdicts": verdicts,
            "recommendation_code": rec_code,
            "recommendation_params": rec_params,
            "recommendation": render_recommendation(rec_code, rec_params),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_filter": status_filter,
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "campaigns": campaign_reports,
        "totals": {
            "spend": round(total_spend, 2) if had_spend else None,
            "campaigns_count": len(filtered),
        },
        "unsupported_fields": unsupported or None,
    }


def load_past_campaigns_history() -> list:
    if not os.path.exists(_history_path()):
        return []
    try:
        with open(_history_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("past_campaigns_history.json повреждён (%s) — история недоступна", e)
        return []
    reports = data.get("reports", [])
    return sorted(reports, key=lambda r: r.get("generated_at", ""), reverse=True)


def _save_past_campaigns_history(reports: list):
    os.makedirs(os.path.dirname(_history_path()), exist_ok=True)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_history_path()), prefix=".past_campaigns_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"reports": reports}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _history_path())
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def collect_past_campaigns_snapshot(status_filter: str, period: str, date_from: str = None, date_to: str = None) -> dict:
    report = build_past_campaigns_report(status_filter, period, date_from, date_to)
    if "error" in report:
        logger.warning("Сбор отчёта по прошлым кампаниям не удался: %s", report["error"])
        return report

    reports = load_past_campaigns_history()
    reports.insert(0, report)
    reports = reports[:MAX_HISTORY_ENTRIES]
    _save_past_campaigns_history(reports)
    logger.info(
        "Отчёт по прошлым кампаниям сохранён (фильтр=%s, период=%s, %d кампаний)",
        status_filter, period, report["totals"]["campaigns_count"],
    )
    return report
