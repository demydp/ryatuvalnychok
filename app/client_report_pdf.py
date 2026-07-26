"""
PDF-експорт звіту для клієнта (Фаза 7) — темний дизайн (фон #1d1d20, акцент #c19bee), щоб можна
було одразу відправити клієнту поштою/месенджером. reportlab обраний свідомо: чистий Python, без
нативних бінарників (на відміну від WeasyPrint, якому потрібні Pango/Cairo DLL) — безпечний вибір
для PyInstaller-збірки, як і вже наявний openpyxl для Excel-експорту.
"""
import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

from app.i18n import t

BG_COLOR = colors.HexColor("#1d1d20")
ACCENT_COLOR = colors.HexColor("#c19bee")
TEXT_COLOR = colors.HexColor("#e8e6ea")
MUTED_COLOR = colors.HexColor("#9d98a8")
CELL_BG = colors.HexColor("#242327")
BORDER_COLOR = colors.HexColor("#3a3940")

PAGE_MARGIN = 18 * mm

# reportlab-овi вбудовані base-14 шрифти (Helvetica тощо) — латиниця й WinAnsiEncoding, БЕЗ
# кирилиці (текст перетворюється на суцільні прямокутники). Застосунок працює лише під Windows
# (start.bat/pythonw.exe/installer/*.spec — усюди Windows-only), тому реєструємо шрифт напряму
# зі стандартної системної теки Windows — Arial/Calibri/Segoe UI там є завжди й повністю
# покривають кирилицю. Якщо раптом жодного не знайдено (по суті неможливо на Windows) —
# тихо лишаємось на Helvetica (латиниця/квадратики), а не падаємо.
_FONT_CANDIDATES = [
    ("arial.ttf", "arialbd.ttf"),
    ("calibri.ttf", "calibrib.ttf"),
    ("segoeui.ttf", "segoeuib.ttf"),
    ("tahoma.ttf", "tahomabd.ttf"),
]
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

_fonts_ready = False


def _ensure_fonts():
    global _fonts_ready, FONT_REGULAR, FONT_BOLD
    if _fonts_ready:
        return
    _fonts_ready = True
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for regular_name, bold_name in _FONT_CANDIDATES:
        regular_path = os.path.join(fonts_dir, regular_name)
        bold_path = os.path.join(fonts_dir, bold_name)
        if os.path.exists(regular_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("ReportSans", regular_path))
                pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold_path))
                FONT_REGULAR, FONT_BOLD = "ReportSans", "ReportSans-Bold"
                return
            except Exception:
                continue


def _report_type_label(report_type: str) -> str:
    key = f"reports.client.type.{report_type}"
    label = t(key)
    return label if label != key else (report_type or "")


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return t("common.no_data")
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _delta_text(curr, prev) -> str:
    if curr is None or prev is None or prev == 0:
        return t("reports.client.no_comparison")
    pct = round((curr - prev) / prev * 100, 1)
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def _draw_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG_COLOR)
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
    canvas.restoreState()


def _styles():
    return {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=22, leading=27, textColor=ACCENT_COLOR, spaceAfter=10),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT_REGULAR, fontSize=11, leading=14, textColor=MUTED_COLOR, spaceAfter=16),
        "heading": ParagraphStyle("heading", fontName=FONT_BOLD, fontSize=14, textColor=ACCENT_COLOR, spaceBefore=18, spaceAfter=8),
        "body": ParagraphStyle("body", fontName=FONT_REGULAR, fontSize=10.5, textColor=TEXT_COLOR, leading=15),
        "muted": ParagraphStyle("muted", fontName=FONT_REGULAR, fontSize=9.5, textColor=MUTED_COLOR, leading=13),
        "table_header": ParagraphStyle("table_header", fontName=FONT_BOLD, fontSize=8, leading=10, textColor=ACCENT_COLOR),
        "table_header_muted": ParagraphStyle("table_header_muted", fontName=FONT_REGULAR, fontSize=8, leading=10, textColor=MUTED_COLOR),
        "table_cell": ParagraphStyle("table_cell", fontName=FONT_REGULAR, fontSize=9, leading=12, textColor=TEXT_COLOR),
    }


def _metrics_grid(report: dict, styles) -> Table:
    totals = report["totals"]
    prev_totals = report.get("prev_totals") or {}
    results = totals.get("results") or []
    prev_results_by_label = {r["label"]: r for r in (prev_totals.get("results") or [])}
    result_parts = []
    for r in results:
        prev_r = prev_results_by_label.get(r["label"])
        delta = f" ({_delta_text(r['value'], prev_r['value'] if prev_r else None)})"
        result_parts.append(f"{r['label']}: {r['value']} ({_fmt(r['cost_per_result'])}){delta}")
    result_line = ", ".join(result_parts) if result_parts else t("common.no_data")

    header_labels = [
        t("reports.client.spend"), t("reports.client.ctr"),
        t("reports.client.cpm"), t("reports.client.reach"), t("reports.client.frequency"),
    ]
    metric_keys = ["spend", "ctr", "cpm", "reach", "frequency"]
    suffixes = ["", "%", "", "", ""]
    value_style = ParagraphStyle("metric_value", fontName=FONT_BOLD, fontSize=14, leading=17, textColor=ACCENT_COLOR, alignment=1)
    delta_style = ParagraphStyle("metric_delta", fontName=FONT_REGULAR, fontSize=8, leading=10, textColor=MUTED_COLOR, alignment=1)
    rows = [
        [Paragraph(label, styles["table_header_muted"]) for label in header_labels],
        [Paragraph(_fmt(totals.get(k), s), value_style) for k, s in zip(metric_keys, suffixes)],
        [Paragraph(f"{t('reports.client.vs_prev')}: {_delta_text(totals.get(k), prev_totals.get(k))}", delta_style) for k in metric_keys],
    ]
    table = Table(rows, colWidths=[(A4[0] - 2 * PAGE_MARGIN) / 5.0] * 5)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CELL_BG),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 1),
        ("TOPPADDING", (0, 2), (-1, 2), 0),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
    ]))
    return table, result_line


def _funnel_table(report: dict, styles):
    funnel = report.get("funnel") or []
    if not funnel:
        return None
    header_labels = [
        t("reports.client.funnel_col_stage"), t("reports.client.funnel_col_current"),
        t("reports.client.funnel_col_prev"), t("reports.client.funnel_col_change"),
    ]
    rows = [[Paragraph(label, styles["table_header"]) for label in header_labels]]
    for f in funnel:
        change = _delta_text(f.get("value"), f.get("prev_value"))
        rows.append([
            Paragraph(f.get("label", ""), styles["table_cell"]),
            Paragraph(_fmt(f.get("value")), styles["table_cell"]),
            Paragraph(_fmt(f.get("prev_value")), styles["table_cell"]),
            Paragraph(change, styles["table_cell"]),
        ])
    col_widths = [(A4[0] - 2 * PAGE_MARGIN) * w for w in (0.4, 0.2, 0.2, 0.2)]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CELL_BG, colors.HexColor("#1d1d20")]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _campaigns_table(report: dict, styles) -> Table:
    header_labels = [
        t("reports.client.col_campaign"),
        t("reports.client.col_spend"),
        t("reports.client.col_ctr"),
        t("reports.client.col_result"),
        t("reports.client.col_cost_per_result"),
        t("reports.client.col_verdict"),
    ]
    rows = [[Paragraph(label, styles["table_header"]) for label in header_labels]]
    for c in report.get("campaigns") or []:
        m = c.get("metrics") or {}
        r = c.get("result") or {}
        result_cell = f"{r.get('label')}: {r.get('value')}" if r.get("value") is not None else t("common.no_data")
        verdict_text = (c.get("verdict") or {}).get("text", "")
        rows.append([
            Paragraph(c.get("name", ""), styles["table_cell"]),
            Paragraph(_fmt(m.get("spend")), styles["table_cell"]),
            Paragraph(_fmt(m.get("ctr"), "%"), styles["table_cell"]),
            Paragraph(result_cell, styles["table_cell"]),
            Paragraph(_fmt(r.get("cost_per_result")), styles["table_cell"]),
            Paragraph(verdict_text, styles["table_cell"]),
        ])

    col_widths = [(A4[0] - 2 * PAGE_MARGIN) * w for w in (0.22, 0.11, 0.1, 0.16, 0.13, 0.28)]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CELL_BG, colors.HexColor("#1d1d20")]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _summary_box(report: dict, styles):
    """ПІДСУМОК (Фаза 7, єдиний формат) — виділений блок нагорі документа: головний факт,
    причина в цифрах, наслідок, дії. Толерантно до старих звітів (report["summary"] відсутній,
    є лише report["conclusion"]/report["next_period_plan"] зі старого формату) — показує їх
    замість пустого блоку, а не ховає історію."""
    summary = report.get("summary") or {}
    fact_style = ParagraphStyle("summary_fact", fontName=FONT_BOLD, fontSize=13, leading=17, textColor=TEXT_COLOR, spaceAfter=4)
    line_style = ParagraphStyle("summary_line", fontName=FONT_REGULAR, fontSize=10, leading=14, textColor=TEXT_COLOR, spaceAfter=3)

    content = []
    if summary.get("main_fact"):
        content.append(Paragraph(summary["main_fact"], fact_style))
    if summary.get("cause"):
        content.append(Paragraph(f"<b>{t('reports.client.summary.cause_label')}:</b> {summary['cause']}", line_style))
    if summary.get("consequence"):
        content.append(Paragraph(f"<b>{t('reports.client.summary.consequence_label')}:</b> {summary['consequence']}", line_style))
    if summary.get("actions"):
        actions_html = summary["actions"].replace("\n", "<br/>")
        content.append(Paragraph(f"<b>{t('reports.client.summary.actions_label')}:</b> {actions_html}", line_style))

    if not content:
        if report.get("conclusion"):
            content.append(Paragraph(report["conclusion"].replace("\n", "<br/>"), fact_style))
        if report.get("next_period_plan"):
            content.append(Paragraph(
                f"<b>{t('reports.client.summary.actions_label')}:</b> {report['next_period_plan'].replace(chr(10), '<br/>')}",
                line_style,
            ))
        if not content and report.get("opus_note"):
            content.append(Paragraph(report["opus_note"], styles["muted"]))

    if not content:
        return None

    box = Table([[content]], colWidths=[A4[0] - 2 * PAGE_MARGIN])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2a2333")),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return box


def build_client_report_pdf_bytes(report: dict) -> bytes:
    _ensure_fonts()
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN, topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
    )

    story = []
    story.append(Paragraph(report.get("project_name") or t("reports.client.untitled_project"), styles["title"]))
    type_label = _report_type_label(report.get("report_type") or report.get("period"))
    story.append(Paragraph(
        f"{t('reports.client.period_label')}: {type_label} ({report.get('date_from')} — {report.get('date_to')}) · "
        f"{t('reports.client.generated_label')}: {(report.get('generated_at') or '')[:10]}",
        styles["subtitle"],
    ))
    if report.get("prev_date_from") and report.get("prev_date_to"):
        story.append(Paragraph(
            f"{t('reports.client.vs_prev')}: {report.get('prev_date_from')} — {report.get('prev_date_to')}",
            styles["muted"],
        ))

    summary_box = _summary_box(report, styles)
    if summary_box is not None:
        story.append(Spacer(1, 10))
        story.append(summary_box)

    story.append(Paragraph(t("reports.client.totals_heading"), styles["heading"]))
    metrics_table, result_line = _metrics_grid(report, styles)
    story.append(metrics_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"{t('reports.client.results_label')}: {result_line}", styles["body"]))

    funnel_table = _funnel_table(report, styles)
    if funnel_table is not None:
        story.append(Paragraph(t("reports.client.funnel_heading"), styles["heading"]))
        story.append(funnel_table)

    story.append(Paragraph(t("reports.client.campaigns_heading"), styles["heading"]))
    if report.get("campaigns"):
        story.append(_campaigns_table(report, styles))
    else:
        story.append(Paragraph(t("common.no_data"), styles["muted"]))

    story.append(Paragraph(t("reports.client.creatives_heading"), styles["heading"]))
    best_ad, worst_ad = report.get("best_ad"), report.get("worst_ad")
    if best_ad and worst_ad:
        impressions_label = t("reports.client.funnel.impressions")
        story.append(Paragraph(
            f"<b>{t('reports.client.best_ad')}:</b> «{best_ad['name']}» ({best_ad['campaign_name']}) — "
            f"{best_ad['metric_used']}: {best_ad['value']} ({impressions_label}: {_fmt(best_ad.get('impressions'))})",
            styles["body"],
        ))
        story.append(Paragraph(
            f"<b>{t('reports.client.worst_ad')}:</b> «{worst_ad['name']}» ({worst_ad['campaign_name']}) — "
            f"{worst_ad['metric_used']}: {worst_ad['value']} ({impressions_label}: {_fmt(worst_ad.get('impressions'))})",
            styles["body"],
        ))
    if report.get("ad_note"):
        story.append(Paragraph(report["ad_note"], styles["muted"]))

    story.append(Paragraph(t("reports.client.tested_heading"), styles["heading"]))
    new_adsets = report.get("new_adsets") or []
    new_ads = report.get("new_ads") or []

    def _tested_result_text(item):
        r = item.get("result") or {}
        if r.get("value") is None:
            return t("common.no_data")
        cost = r.get("cost_per_result")
        return f"{r['label']}: {r['value']}" + (f" ({_fmt(cost)})" if cost is not None else "")

    if new_adsets or new_ads:
        for a in new_adsets:
            story.append(Paragraph(
                t("reports.client.tested_new_adset", name=a.get("name", ""), campaign=a.get("campaign_name", ""),
                  result=_tested_result_text(a)),
                styles["body"],
            ))
        for a in new_ads:
            story.append(Paragraph(
                t("reports.client.tested_new_ad", name=a.get("name", ""), campaign=a.get("campaign_name", ""),
                  result=_tested_result_text(a)),
                styles["body"],
            ))
    else:
        story.append(Paragraph(t("reports.client.tested_none"), styles["muted"]))

    story.append(Paragraph(t("reports.client.top_reels_heading"), styles["heading"]))
    top_reels = report.get("top_reels") or []
    if top_reels:
        for p in top_reels:
            caption = (p.get("caption") or "").replace("\n", " ")
            story.append(Paragraph(
                f"«{caption}» — ER {p.get('engagement_rate')}%, {t('reports.client.reach_label')} {p.get('reach')}",
                styles["body"],
            ))
    else:
        story.append(Paragraph(t("common.no_data"), styles["muted"]))

    business_plain = (report.get("summary") or {}).get("business_plain")
    if business_plain:
        story.append(Paragraph(t("reports.client.business_heading"), styles["heading"]))
        story.append(Paragraph(business_plain, styles["body"]))

    doc.build(story, onFirstPage=_draw_background, onLaterPages=_draw_background)
    return buf.getvalue()
