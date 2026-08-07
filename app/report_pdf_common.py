"""
Спільний "движок" верстки PDF-звітів (reportlab, темний дизайн — фон #1d1d20, акцент #c19bee) —
винесено з app/client_report_pdf.py, щоб СММ-звіт (app/smm_report_pdf.py) не дублював шрифти,
кольори, фон сторінки і виділений блок ПІДСУМОК, а мав з рекламним звітом однаковий вигляд.
Модуль знає лише про ЗАГАЛЬНУ форму звіту (summary{main_fact,cause,consequence,actions,
business_plain}, старі report["conclusion"]/["next_period_plan"]) — нічого рекламного чи
СММ-специфічного тут немає.
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

from app.i18n import t

BG_COLOR = colors.HexColor("#1d1d20")
ACCENT_COLOR = colors.HexColor("#c19bee")
TEXT_COLOR = colors.HexColor("#e8e6ea")
MUTED_COLOR = colors.HexColor("#9d98a8")
CELL_BG = colors.HexColor("#242327")
BORDER_COLOR = colors.HexColor("#3a3940")
HEADER_BG = colors.HexColor("#1a1a1e")
ROW_BG_ALT = colors.HexColor("#1d1d20")
SUMMARY_BG = colors.HexColor("#2a2333")

PAGE_MARGIN = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN

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


def ensure_fonts():
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


def fmt(value, suffix: str = "") -> str:
    if value is None:
        return t("common.no_data")
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def delta_text(curr, prev) -> str:
    if curr is None or prev is None or prev == 0:
        return t("reports.client.no_comparison")
    pct = round((curr - prev) / prev * 100, 1)
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def draw_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG_COLOR)
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
    canvas.restoreState()


def styles() -> dict:
    ensure_fonts()
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


def data_table(header_labels: list, rows: list, col_fractions: tuple, sty: dict) -> Table:
    """Універсальна таблиця "заголовок + рядки" в спільному темному стилі — той самий вигляд,
    що й _funnel_table/_campaigns_table у client_report_pdf.py, але без прив'язки до конкретних
    колонок: rows — вже готові списки Paragraph-комірок (по одній на header_labels)."""
    table_rows = [[Paragraph(label, sty["table_header"]) for label in header_labels]] + rows
    col_widths = [CONTENT_WIDTH * f for f in col_fractions]
    table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CELL_BG, ROW_BG_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def value_grid(header_labels: list, values: list, delta_labels: list, sty: dict) -> Table:
    """"Велике число + дельта до попереднього періоду" сітка — однаковий вигляд і в рекламному
    звіті (app/client_report_pdf.py::_metrics_grid), і в СММ-звіті (app/smm_report_pdf.py):
    один рядок заголовків, один рядок великих значень акцентним кольором, один рядок дельт."""
    value_style = ParagraphStyle("grid_value", fontName=FONT_BOLD, fontSize=14, leading=17, textColor=ACCENT_COLOR, alignment=1)
    delta_style = ParagraphStyle("grid_delta", fontName=FONT_REGULAR, fontSize=8, leading=10, textColor=MUTED_COLOR, alignment=1)
    rows = [
        [Paragraph(label, sty["table_header_muted"]) for label in header_labels],
        [Paragraph(v, value_style) for v in values],
        [Paragraph(d, delta_style) for d in delta_labels],
    ]
    n = len(header_labels)
    table = Table(rows, colWidths=[CONTENT_WIDTH / n] * n)
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
    return table


_DEFAULT_SUMMARY_LABEL_KEYS = {
    "cause": "reports.client.summary.cause_label",
    "consequence": "reports.client.summary.consequence_label",
    "actions": "reports.client.summary.actions_label",
}


def summary_box(report: dict, sty: dict, label_keys: dict = None):
    """ПІДСУМОК (Фаза 7, єдиний формат) — виділений блок нагорі документа: головний факт,
    причина в цифрах, наслідок/висновок, дії. Толерантно до старих звітів (report["summary"]
    відсутній, є лише report["conclusion"]/report["next_period_plan"] зі старого формату) —
    показує їх замість пустого блоку, а не ховає історію.

    label_keys — опційне перевизначення i18n-ключів підписів (cause/consequence/actions):
    рекламний і СММ-звіт зберігають розбір під тими самими полями summary{cause,consequence,
    actions} (той самий парсер маркерів, app/ads_opus.py::parse_client_report_response), але
    підписують їх по-різному ("Наслідок" для клієнта, "Висновок" для внутрішнього СММ-розбору)."""
    keys = {**_DEFAULT_SUMMARY_LABEL_KEYS, **(label_keys or {})}
    summary = report.get("summary") or {}
    fact_style = ParagraphStyle("summary_fact", fontName=FONT_BOLD, fontSize=13, leading=17, textColor=TEXT_COLOR, spaceAfter=4)
    line_style = ParagraphStyle("summary_line", fontName=FONT_REGULAR, fontSize=10, leading=14, textColor=TEXT_COLOR, spaceAfter=3)

    content = []
    if summary.get("main_fact"):
        content.append(Paragraph(summary["main_fact"], fact_style))
    if summary.get("cause"):
        content.append(Paragraph(f"<b>{t(keys['cause'])}:</b> {summary['cause']}", line_style))
    if summary.get("consequence"):
        content.append(Paragraph(f"<b>{t(keys['consequence'])}:</b> {summary['consequence']}", line_style))
    if summary.get("actions"):
        actions_html = summary["actions"].replace("\n", "<br/>")
        content.append(Paragraph(f"<b>{t(keys['actions'])}:</b> {actions_html}", line_style))

    if not content:
        if report.get("conclusion"):
            content.append(Paragraph(report["conclusion"].replace("\n", "<br/>"), fact_style))
        if report.get("next_period_plan"):
            content.append(Paragraph(
                f"<b>{t(keys['actions'])}:</b> {report['next_period_plan'].replace(chr(10), '<br/>')}",
                line_style,
            ))
        if not content and report.get("opus_note"):
            content.append(Paragraph(report["opus_note"], sty["muted"]))

    if not content:
        return None

    box = Table([[content]], colWidths=[CONTENT_WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SUMMARY_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return box
