from flask import Blueprint, Response, jsonify, request

from app.client_report import (
    build_client_report,
    delete_client_report,
    load_cached_pdf,
    load_client_report,
    load_client_reports,
    save_cached_pdf,
)
from app.client_report_pdf import build_client_report_pdf_bytes
from app.daily_report import build_daily_report, collect_daily_snapshot, load_history, render_recommendation
from app.excel_export import build_excel_bytes, build_past_campaigns_excel_bytes
from app.i18n import t
from app.past_campaigns_report import (
    collect_past_campaigns_snapshot,
    load_past_campaigns_history,
)
from app.past_campaigns_report import render_recommendation as render_past_recommendation
from app.smm_report import (
    build_smm_report,
    delete_smm_report,
    load_cached_smm_pdf,
    load_smm_report,
    load_smm_reports,
    save_cached_smm_pdf,
)
from app.smm_report_pdf import build_smm_report_pdf_bytes

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/history", methods=["GET"])
def history():
    days = load_history()
    for day in days:
        # Снимок мог быть собран планировщиком в фоне (нет X-Lang -> язык на момент сбора
        # не обязательно совпадает с текущим) — перерендериваем текст из code+params на
        # текущем языке. У снимков до этой миграции code нет, тогда оставляем как было.
        if day.get("note_code"):
            day["note"] = render_recommendation(day["note_code"])
        for c in day.get("campaigns") or []:
            if c.get("recommendation_code"):
                c["recommendation"] = render_recommendation(c["recommendation_code"], c.get("recommendation_params"))
    return jsonify({"days": days})


@reports_bp.route("/preview", methods=["GET"])
def preview():
    """Только посчитать, не сохранять — для предпросмотра перед "Собрать отчёт за день"."""
    report = build_daily_report()
    if "error" in report:
        return jsonify(report), 400
    return jsonify(report)


@reports_bp.route("/collect", methods=["POST"])
def collect():
    report = collect_daily_snapshot()
    if "error" in report:
        return jsonify(report), 400
    return jsonify(report)


@reports_bp.route("/export-excel", methods=["GET"])
def export_excel():
    days = load_history()
    if not days:
        return jsonify({"error": t("reports.msg.no_history_to_export")}), 400

    xlsx_bytes = build_excel_bytes(days)
    return Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=daily_ads_report.xlsx"},
    )


@reports_bp.route("/past-campaigns/history", methods=["GET"])
def past_campaigns_history():
    reports = load_past_campaigns_history()
    for snap in reports:
        for c in snap.get("campaigns") or []:
            if c.get("recommendation_code"):
                c["recommendation"] = render_past_recommendation(c["recommendation_code"], c.get("recommendation_params"))
    return jsonify({"reports": reports})


@reports_bp.route("/past-campaigns/collect", methods=["POST"])
def past_campaigns_collect():
    body = request.get_json(force=True) or {}
    status_filter = body.get("status_filter", "all")
    period = body.get("period", "last_30d")
    date_from = body.get("date_from")
    date_to = body.get("date_to")

    report = collect_past_campaigns_snapshot(status_filter, period, date_from, date_to)
    if "error" in report:
        return jsonify(report), 400
    return jsonify(report)


@reports_bp.route("/past-campaigns/export-excel", methods=["GET"])
def past_campaigns_export_excel():
    reports = load_past_campaigns_history()
    if not reports:
        return jsonify({"error": t("reports.msg.no_past_campaigns_history_to_export")}), 400

    xlsx_bytes = build_past_campaigns_excel_bytes(reports)
    return Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=past_campaigns_report.xlsx"},
    )


# --- Звіт для клієнта (Фаза 7) ---

@reports_bp.route("/client", methods=["GET"])
def client_reports_list():
    return jsonify({"reports": load_client_reports()})


@reports_bp.route("/client/generate", methods=["POST"])
def client_report_generate():
    body = request.get_json(force=True) or {}
    report_type = body.get("report_type", "daily")
    date_from = body.get("date_from")
    date_to = body.get("date_to")

    report = build_client_report(report_type, date_from, date_to)
    if "error" in report:
        return jsonify(report), 400
    return jsonify(report)


@reports_bp.route("/client/<report_id>", methods=["GET"])
def client_report_get(report_id):
    report = load_client_report(report_id)
    if not report:
        return jsonify({"error": t("reports.client.msg.not_found")}), 404
    return jsonify(report)


@reports_bp.route("/client/<report_id>/pdf", methods=["GET"])
def client_report_pdf(report_id):
    report = load_client_report(report_id)
    if not report:
        return jsonify({"error": t("reports.client.msg.not_found")}), 404

    pdf_bytes = load_cached_pdf(report_id)
    if pdf_bytes is None:
        pdf_bytes = build_client_report_pdf_bytes(report)
        save_cached_pdf(report_id, pdf_bytes)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=client_report_{report_id}.pdf"},
    )


@reports_bp.route("/client/<report_id>", methods=["DELETE"])
def client_report_delete(report_id):
    if not delete_client_report(report_id):
        return jsonify({"error": t("reports.client.msg.not_found")}), 404
    return jsonify({"deleted": True})


# --- СММ-звіт по контенту ---

@reports_bp.route("/smm", methods=["GET"])
def smm_reports_list():
    return jsonify({"reports": load_smm_reports()})


@reports_bp.route("/smm/generate", methods=["POST"])
def smm_report_generate():
    body = request.get_json(force=True) or {}
    report_type = body.get("report_type", "daily")
    date_from = body.get("date_from")
    date_to = body.get("date_to")

    report = build_smm_report(report_type, date_from, date_to)
    if "error" in report:
        return jsonify(report), 400
    return jsonify(report)


@reports_bp.route("/smm/<report_id>", methods=["GET"])
def smm_report_get(report_id):
    report = load_smm_report(report_id)
    if not report:
        return jsonify({"error": t("reports.client.msg.not_found")}), 404
    return jsonify(report)


@reports_bp.route("/smm/<report_id>/pdf", methods=["GET"])
def smm_report_pdf(report_id):
    report = load_smm_report(report_id)
    if not report:
        return jsonify({"error": t("reports.client.msg.not_found")}), 404

    pdf_bytes = load_cached_smm_pdf(report_id)
    if pdf_bytes is None:
        pdf_bytes = build_smm_report_pdf_bytes(report)
        save_cached_smm_pdf(report_id, pdf_bytes)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=smm_report_{report_id}.pdf"},
    )


@reports_bp.route("/smm/<report_id>", methods=["DELETE"])
def smm_report_delete(report_id):
    if not delete_smm_report(report_id):
        return jsonify({"error": t("reports.client.msg.not_found")}), 404
    return jsonify({"deleted": True})
