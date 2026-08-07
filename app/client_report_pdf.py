"""
PDF-експорт звіту для клієнта (Фаза 7) — темний дизайн, спільний з СММ-звітом
(app/smm_report_pdf.py) движок верстки в app/report_pdf_common.py (шрифти, кольори, фон
сторінки, блок ПІДСУМОК, універсальна таблиця). Тут — лише рекламно-специфічні секції
(метрики кампаній, воронка, таблиця кампаній, креативи, нові тести, органічні рілси).
reportlab обраний свідомо: чистий Python, без нативних бінарників (на відміну від WeasyPrint,
якому потрібні Pango/Cairo DLL) — безпечний вибір для PyInstaller-збірки, як і вже наявний
openpyxl для Excel-експорту.
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from app.i18n import t
from app.report_pdf_common import (
    PAGE_MARGIN,
    data_table,
    delta_text,
    draw_background,
    ensure_fonts,
    fmt,
    styles,
    summary_box,
    value_grid,
)


def _report_type_label(report_type: str) -> str:
    key = f"reports.client.type.{report_type}"
    label = t(key)
    return label if label != key else (report_type or "")


def _metrics_grid(report: dict, sty) -> Table:
    totals = report["totals"]
    prev_totals = report.get("prev_totals") or {}
    results = totals.get("results") or []
    prev_results_by_label = {r["label"]: r for r in (prev_totals.get("results") or [])}
    result_parts = []
    for r in results:
        prev_r = prev_results_by_label.get(r["label"])
        delta = f" ({delta_text(r['value'], prev_r['value'] if prev_r else None)})"
        result_parts.append(f"{r['label']}: {r['value']} ({fmt(r['cost_per_result'])}){delta}")
    result_line = ", ".join(result_parts) if result_parts else t("common.no_data")

    header_labels = [
        t("reports.client.spend"), t("reports.client.ctr"),
        t("reports.client.cpm"), t("reports.client.reach"), t("reports.client.frequency"),
    ]
    metric_keys = ["spend", "ctr", "cpm", "reach", "frequency"]
    suffixes = ["", "%", "", "", ""]
    values = [fmt(totals.get(k), s) for k, s in zip(metric_keys, suffixes)]
    deltas = [f"{t('reports.client.vs_prev')}: {delta_text(totals.get(k), prev_totals.get(k))}" for k in metric_keys]
    return value_grid(header_labels, values, deltas, sty), result_line


def _funnel_table(report: dict, sty):
    funnel = report.get("funnel") or []
    if not funnel:
        return None
    header_labels = [
        t("reports.client.funnel_col_stage"), t("reports.client.funnel_col_current"),
        t("reports.client.funnel_col_prev"), t("reports.client.funnel_col_change"),
    ]
    rows = []
    for f in funnel:
        change = delta_text(f.get("value"), f.get("prev_value"))
        rows.append([
            Paragraph(f.get("label", ""), sty["table_cell"]),
            Paragraph(fmt(f.get("value")), sty["table_cell"]),
            Paragraph(fmt(f.get("prev_value")), sty["table_cell"]),
            Paragraph(change, sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.4, 0.2, 0.2, 0.2), sty)


def _campaigns_table(report: dict, sty) -> Table:
    header_labels = [
        t("reports.client.col_campaign"),
        t("reports.client.col_spend"),
        t("reports.client.col_ctr"),
        t("reports.client.col_result"),
        t("reports.client.col_cost_per_result"),
        t("reports.client.col_verdict"),
    ]
    rows = []
    for c in report.get("campaigns") or []:
        m = c.get("metrics") or {}
        r = c.get("result") or {}
        result_cell = f"{r.get('label')}: {r.get('value')}" if r.get("value") is not None else t("common.no_data")
        verdict_text = (c.get("verdict") or {}).get("text", "")
        rows.append([
            Paragraph(c.get("name", ""), sty["table_cell"]),
            Paragraph(fmt(m.get("spend")), sty["table_cell"]),
            Paragraph(fmt(m.get("ctr"), "%"), sty["table_cell"]),
            Paragraph(result_cell, sty["table_cell"]),
            Paragraph(fmt(r.get("cost_per_result")), sty["table_cell"]),
            Paragraph(verdict_text, sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.22, 0.11, 0.1, 0.16, 0.13, 0.28), sty)


def build_client_report_pdf_bytes(report: dict) -> bytes:
    ensure_fonts()
    sty = styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN, topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
    )

    story = []
    story.append(Paragraph(report.get("project_name") or t("reports.client.untitled_project"), sty["title"]))
    type_label = _report_type_label(report.get("report_type") or report.get("period"))
    story.append(Paragraph(
        f"{t('reports.client.period_label')}: {type_label} ({report.get('date_from')} — {report.get('date_to')}) · "
        f"{t('reports.client.generated_label')}: {(report.get('generated_at') or '')[:10]}",
        sty["subtitle"],
    ))
    if report.get("prev_date_from") and report.get("prev_date_to"):
        story.append(Paragraph(
            f"{t('reports.client.vs_prev')}: {report.get('prev_date_from')} — {report.get('prev_date_to')}",
            sty["muted"],
        ))

    box = summary_box(report, sty)
    if box is not None:
        story.append(Spacer(1, 10))
        story.append(box)

    story.append(Paragraph(t("reports.client.totals_heading"), sty["heading"]))
    metrics_table, result_line = _metrics_grid(report, sty)
    story.append(metrics_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"{t('reports.client.results_label')}: {result_line}", sty["body"]))

    funnel_table = _funnel_table(report, sty)
    if funnel_table is not None:
        story.append(Paragraph(t("reports.client.funnel_heading"), sty["heading"]))
        story.append(funnel_table)

    story.append(Paragraph(t("reports.client.campaigns_heading"), sty["heading"]))
    if report.get("campaigns"):
        story.append(_campaigns_table(report, sty))
    else:
        story.append(Paragraph(t("common.no_data"), sty["muted"]))

    story.append(Paragraph(t("reports.client.creatives_heading"), sty["heading"]))
    best_ad, worst_ad = report.get("best_ad"), report.get("worst_ad")
    if best_ad and worst_ad:
        impressions_label = t("reports.client.funnel.impressions")
        story.append(Paragraph(
            f"<b>{t('reports.client.best_ad')}:</b> «{best_ad['name']}» ({best_ad['campaign_name']}) — "
            f"{best_ad['metric_used']}: {best_ad['value']} ({impressions_label}: {fmt(best_ad.get('impressions'))})",
            sty["body"],
        ))
        story.append(Paragraph(
            f"<b>{t('reports.client.worst_ad')}:</b> «{worst_ad['name']}» ({worst_ad['campaign_name']}) — "
            f"{worst_ad['metric_used']}: {worst_ad['value']} ({impressions_label}: {fmt(worst_ad.get('impressions'))})",
            sty["body"],
        ))
    if report.get("ad_note"):
        story.append(Paragraph(report["ad_note"], sty["muted"]))

    story.append(Paragraph(t("reports.client.tested_heading"), sty["heading"]))
    new_adsets = report.get("new_adsets") or []
    new_ads = report.get("new_ads") or []

    def _tested_result_text(item):
        r = item.get("result") or {}
        if r.get("value") is None:
            return t("common.no_data")
        cost = r.get("cost_per_result")
        return f"{r['label']}: {r['value']}" + (f" ({fmt(cost)})" if cost is not None else "")

    if new_adsets or new_ads:
        for a in new_adsets:
            story.append(Paragraph(
                t("reports.client.tested_new_adset", name=a.get("name", ""), campaign=a.get("campaign_name", ""),
                  result=_tested_result_text(a)),
                sty["body"],
            ))
        for a in new_ads:
            story.append(Paragraph(
                t("reports.client.tested_new_ad", name=a.get("name", ""), campaign=a.get("campaign_name", ""),
                  result=_tested_result_text(a)),
                sty["body"],
            ))
    else:
        story.append(Paragraph(t("reports.client.tested_none"), sty["muted"]))

    story.append(Paragraph(t("reports.client.top_reels_heading"), sty["heading"]))
    top_reels = report.get("top_reels") or []
    if top_reels:
        for p in top_reels:
            caption = (p.get("caption") or "").replace("\n", " ")
            story.append(Paragraph(
                f"«{caption}» — ER {p.get('engagement_rate')}%, {t('reports.client.reach_label')} {p.get('reach')}",
                sty["body"],
            ))
    else:
        story.append(Paragraph(t("common.no_data"), sty["muted"]))

    business_plain = (report.get("summary") or {}).get("business_plain")
    if business_plain:
        story.append(Paragraph(t("reports.client.business_heading"), sty["heading"]))
        story.append(Paragraph(business_plain, sty["body"]))

    doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
    return buf.getvalue()
