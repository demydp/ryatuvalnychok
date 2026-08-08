"""
PDF-експорт СММ-звіту по контенту (app/smm_report.py) — та сама верстка й той самий темний
дизайн, що й у рекламному Звіті для клієнта (app/client_report_pdf.py), через спільний движок
app/report_pdf_common.py: шрифти, кольори, фон сторінки, блок ПІДСУМОК, універсальні таблиці.
Тут — лише СММ-специфічні секції (метрики акаунту, динаміка, що заходить, хук-аналіз, рубрики).
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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


_SMM_SUMMARY_LABEL_KEYS = {
    "cause": "reports.smm.summary.cause_label",
    "consequence": "reports.smm.summary.conclusion_label",
    "actions": "reports.smm.summary.actions_label",
}


def _account_metrics_grid(report: dict, sty):
    totals = report.get("account_metrics") or {}
    prev_totals = report.get("prev_account_metrics") or {}
    header_labels = [
        t("reports.smm.posts_count"), t("reports.smm.reach"),
        t("reports.smm.engagement"), t("reports.smm.er"), t("reports.smm.saves"),
    ]
    metric_keys = ["posts_count", "reach_total", "engagement_total", "engagement_rate_avg", "saves_total"]
    suffixes = ["", "", "", "%", ""]
    values = [fmt(totals.get(k), s) for k, s in zip(metric_keys, suffixes)]
    deltas = [f"{t('reports.client.vs_prev')}: {delta_text(totals.get(k), prev_totals.get(k))}" for k in metric_keys]
    return value_grid(header_labels, values, deltas, sty)


def _trend_table(report: dict, sty):
    trend = report.get("trend") or []
    if not trend:
        return None
    header_labels = [
        t("reports.client.funnel_col_stage"), t("reports.client.funnel_col_current"),
        t("reports.client.funnel_col_prev"), t("reports.client.funnel_col_change"),
    ]
    rows = []
    for row in trend:
        change = delta_text(row.get("value"), row.get("prev_value"))
        rows.append([
            Paragraph(row.get("label", ""), sty["table_cell"]),
            Paragraph(fmt(row.get("value")), sty["table_cell"]),
            Paragraph(fmt(row.get("prev_value")), sty["table_cell"]),
            Paragraph(change, sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.4, 0.2, 0.2, 0.2), sty)


def _top_content_table(report: dict, sty):
    top_content = report.get("top_content") or {}
    top_er = top_content.get("top_er") or []
    if not top_er:
        return None
    header_labels = [t("reports.smm.col_post"), t("reports.smm.col_reach"), t("reports.smm.col_er")]
    rows = []
    for p in top_er:
        caption = (p.get("caption") or "").replace("\n", " ")
        rows.append([
            Paragraph(caption or t("common.no_data"), sty["table_cell"]),
            Paragraph(fmt(p.get("reach")), sty["table_cell"]),
            Paragraph(fmt(p.get("engagement_rate"), "%"), sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.6, 0.2, 0.2), sty)


def _stories_summary_grid(report: dict, sty):
    stories = report.get("stories") or {}
    totals = stories.get("totals") or {}
    header_labels = [
        t("reports.smm.stories.count"), t("reports.smm.stories.reach_total"),
        t("reports.smm.stories.replies_total"), t("reports.smm.stories.navigation_total"),
        t("reports.smm.stories.profile_visits_total"), t("reports.smm.stories.interactions_total"),
    ]
    values = [
        str(stories.get("count", 0)), fmt(totals.get("reach")), fmt(totals.get("replies")),
        fmt(totals.get("navigation")), fmt(totals.get("profile_visits")), fmt(totals.get("total_interactions")),
    ]
    deltas = ["" for _ in header_labels]
    return value_grid(header_labels, values, deltas, sty)


def _stories_table(report: dict, sty):
    items = (report.get("stories") or {}).get("items") or []
    if not items:
        return None
    header_labels = [
        t("reports.smm.stories.col_story"), t("reports.smm.stories.col_date"),
        t("reports.smm.stories.col_type"), t("reports.smm.stories.col_reach"),
        t("reports.smm.stories.col_replies"), t("reports.smm.stories.col_navigation"),
        t("reports.smm.stories.col_profile_visits"), t("reports.smm.stories.col_interactions"),
    ]
    rows = []
    for s in items:
        rows.append([
            Paragraph(s.get("title") or t("common.no_data"), sty["table_cell"]),
            Paragraph(s.get("date_label") or "", sty["table_cell"]),
            Paragraph(s.get("media_type_label") or "", sty["table_cell"]),
            Paragraph(fmt(s.get("reach")), sty["table_cell"]),
            Paragraph(fmt(s.get("replies")), sty["table_cell"]),
            Paragraph(fmt(s.get("navigation")), sty["table_cell"]),
            Paragraph(fmt(s.get("profile_visits")), sty["table_cell"]),
            Paragraph(fmt(s.get("total_interactions")), sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.22, 0.13, 0.08, 0.11, 0.11, 0.11, 0.12, 0.12), sty)


def _hooks_table(report: dict, sty):
    hook_summary = (report.get("hooks") or {}).get("hook_type_summary") or []
    if not hook_summary:
        return None
    header_labels = [t("reports.smm.col_hook_type"), t("reports.smm.col_hook_indicator"), t("reports.smm.col_sample")]
    rows = []
    for row in hook_summary:
        rows.append([
            Paragraph(row.get("type", ""), sty["table_cell"]),
            Paragraph(fmt(row.get("avg_indicator"), "%"), sty["table_cell"]),
            Paragraph(str(row.get("count", 0)), sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.5, 0.3, 0.2), sty)


def _categories_table(report: dict, sty):
    categories = [c for c in (report.get("categories") or []) if c.get("organic_count")]
    if not categories:
        return None
    header_labels = [
        t("reports.smm.col_category"), t("reports.smm.col_er"),
        t("reports.smm.col_saves_rate"), t("reports.smm.col_hook_indicator"), t("reports.smm.col_sample"),
    ]
    rows = []
    for c in categories:
        rows.append([
            Paragraph(c.get("name", ""), sty["table_cell"]),
            Paragraph(fmt(c.get("avg_er"), "%"), sty["table_cell"]),
            Paragraph(fmt(c.get("avg_saves_rate"), "%"), sty["table_cell"]),
            Paragraph(fmt(c.get("avg_hook_indicator"), "%"), sty["table_cell"]),
            Paragraph(str(c.get("organic_count", 0)), sty["table_cell"]),
        ])
    return data_table(header_labels, rows, (0.32, 0.17, 0.17, 0.17, 0.17), sty)


def build_smm_report_pdf_bytes(report: dict) -> bytes:
    ensure_fonts()
    sty = styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN, topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
    )

    story = []
    title = report.get("project_name") or report.get("ig_username") or t("reports.smm.untitled_account")
    story.append(Paragraph(title, sty["title"]))
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

    box = summary_box(report, sty, label_keys=_SMM_SUMMARY_LABEL_KEYS)
    if box is not None:
        story.append(Spacer(1, 10))
        story.append(box)

    story.append(Paragraph(t("reports.smm.metrics_heading"), sty["heading"]))
    story.append(_account_metrics_grid(report, sty))
    best_post = (report.get("account_metrics") or {}).get("best_post")
    if best_post:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"{t('reports.smm.best_post')}: «{(best_post.get('caption') or '').replace(chr(10), ' ')}» — "
            f"ER {fmt(best_post.get('engagement_rate'), '%')}, {t('reports.client.reach_label')} {fmt(best_post.get('reach'))}",
            sty["body"],
        ))
    story.append(Paragraph(t("reports.smm.no_profile_visits_note"), sty["muted"]))

    trend_table = _trend_table(report, sty)
    if trend_table is not None:
        story.append(Paragraph(t("reports.smm.trend_heading"), sty["heading"]))
        story.append(trend_table)

    story.append(Paragraph(t("reports.smm.top_content_heading"), sty["heading"]))
    top_content = report.get("top_content") or {}
    if top_content.get("insufficient_data"):
        story.append(Paragraph(t("reports.smm.msg.insufficient_content_data"), sty["muted"]))
    else:
        top_table = _top_content_table(report, sty)
        if top_table is not None:
            if top_content.get("low_sample_warning"):
                story.append(Paragraph(t("reports.smm.msg.low_sample", n=top_content.get("dataset_size")), sty["muted"]))
            story.append(top_table)
        else:
            story.append(Paragraph(t("common.no_data"), sty["muted"]))
        best_hour = top_content.get("best_hour")
        best_weekday = top_content.get("best_weekday")
        if best_hour or best_weekday:
            story.append(Spacer(1, 4))
        if best_hour:
            story.append(Paragraph(
                f"{t('reports.smm.best_hour')}: {best_hour['label']} (ER {fmt(best_hour.get('avg_er'), '%')}, n={best_hour.get('count')})",
                sty["body"],
            ))
        if best_weekday:
            story.append(Paragraph(
                f"{t('reports.smm.best_weekday')}: {best_weekday['label']} (ER {fmt(best_weekday.get('avg_er'), '%')}, n={best_weekday.get('count')})",
                sty["body"],
            ))

    story.append(Paragraph(t("reports.smm.hooks_heading"), sty["heading"]))
    hooks_table = _hooks_table(report, sty)
    if hooks_table is not None:
        story.append(hooks_table)
    else:
        story.append(Paragraph(t("reports.smm.msg.no_hooks_data"), sty["muted"]))

    story.append(Paragraph(t("reports.smm.categories_heading"), sty["heading"]))
    categories_table = _categories_table(report, sty)
    if categories_table is not None:
        story.append(categories_table)
    else:
        story.append(Paragraph(t("reports.smm.msg.no_categories_data"), sty["muted"]))

    story_count = (report.get("stories") or {}).get("count", 0)
    story.append(Paragraph(t("reports.smm.stories_heading"), sty["heading"]))
    if story_count:
        story.append(_stories_summary_grid(report, sty))
        story.append(Spacer(1, 6))
        stories_table = _stories_table(report, sty)
        if stories_table is not None:
            story.append(stories_table)
    else:
        story.append(Paragraph(t("reports.smm.msg.no_stories_data"), sty["muted"]))

    business_plain = (report.get("summary") or {}).get("business_plain")
    if business_plain:
        story.append(Paragraph(t("reports.client.business_heading"), sty["heading"]))
        story.append(Paragraph(business_plain, sty["body"]))

    doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
    return buf.getvalue()
