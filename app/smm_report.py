"""
СММ-звіт по контенту — аналог app/client_report.py (Фаза 7 "Звіт для клієнта"), тільки дані
беруться з уже наявних інста-модулів (app/analysis.py "Що заходить", app/hooks_ai.py
"Хук-аналіз", app/categories.py "Рубрики"), а не з Marketing API. Мета: щоб смм-щик міг
вивантажити всю статистику по інстаграму в ОДИН файл (PDF), так само як таргетолог вивантажує
Звіт по рекламі.

Період/порівняння з попереднім періодом такої ж довжини (_resolve_range), фільтрація постів
за період (_filter_posts_by_period) і форматування дельт (_pct_change/_delta_pct_text/_fmt)
навмисно ІМПОРТУЮТЬСЯ з client_report.py, а не дублюються — та сама логіка "денний/тижневий/
довільний період", що й у рекламному звіті, повинна лишатись єдиним визначенням.

Чесність понад усе (як і скрізь у проєкті): "переходи в профіль" і "приріст підписників" з
методики ТЗ Meta Graph API в цьому проєкті НЕ віддає і ніде в кодовій базі не збирається —
чесно "немає даних", а не вигадане число.
"""
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from statistics import mean

from app.ads_api import AdsAPIError
from app.analysis import compute_organic_analysis
from app.categories import compute_category_stats
from app.client_report import _filter_posts_by_period, _fmt, _pct_change, _delta_pct_text, _resolve_range
from app.hooks_ai import compute_hook_stats
from app.i18n import current_lang, t
from app.project_store import get_active_project, get_effective_config, project_data_dir
from app.style_profile import load_style_profile
from app.transcription import load_transcripts

logger = logging.getLogger("reels_dashboard")

_lock = threading.Lock()


def _reports_dir() -> str:
    path = os.path.join(project_data_dir(), "smm_reports")
    os.makedirs(path, exist_ok=True)
    return path


def _report_json_path(report_id: str) -> str:
    return os.path.join(_reports_dir(), f"{report_id}.json")


def _report_pdf_path(report_id: str) -> str:
    return os.path.join(_reports_dir(), f"{report_id}.pdf")


def _account_metrics(posts: list) -> dict:
    """Метрики акаунту за період — лише органіка (is_ad=False) з готовими інсайтами.
    reach_total — сума охоплення ПО ПОСТАХ (не унікальний акаунт-охват за період, Graph API
    такого не віддає) — та сама методика, що app/home_summary.py::build_content_summary()
    вже використовує для "охвату за 7 днів". profile_visits/followers_delta — чесно None:
    ні поточний média-кеш (app/routes/metrics.py), ні app/instagram_api.py не збирають ці
    метрики (get_account_info віддає лише СЬОГОДНІШНІЙ знімок followers_count, без історії)."""
    organic = [p for p in posts if not p.get("is_ad") and p.get("insights_status") == "ok"]

    reach_values = [p.get("reach") for p in organic if p.get("reach") is not None]
    interaction_values = [p.get("total_interactions") for p in organic if p.get("total_interactions") is not None]
    er_values = [p.get("engagement_rate") for p in organic if p.get("engagement_rate") is not None]
    saves_values = [p.get("saved") for p in organic if p.get("saved") is not None]
    saves_rate_values = [p.get("saves_rate") for p in organic if p.get("saves_rate") is not None]

    best_post = None
    with_er = [p for p in organic if p.get("engagement_rate") is not None]
    if with_er:
        best = max(with_er, key=lambda p: p["engagement_rate"])
        best_post = {
            "id": best.get("id"),
            "caption": (best.get("caption") or "")[:80],
            "permalink": best.get("permalink"),
            "engagement_rate": best.get("engagement_rate"),
            "reach": best.get("reach"),
        }

    return {
        "posts_count": len(organic),
        "reach_total": round(sum(reach_values)) if reach_values else None,
        "engagement_total": round(sum(interaction_values)) if interaction_values else None,
        "engagement_rate_avg": round(mean(er_values), 2) if er_values else None,
        "saves_total": round(sum(saves_values)) if saves_values else None,
        "saves_rate_avg": round(mean(saves_rate_values), 2) if saves_rate_values else None,
        "profile_visits": None,
        "followers_delta": None,
        "best_post": best_post,
    }


_TREND_FIELDS = [
    ("posts_count", "reports.smm.trend.posts_count"),
    ("reach_total", "reports.smm.trend.reach_total"),
    ("engagement_total", "reports.smm.trend.engagement_total"),
    ("engagement_rate_avg", "reports.smm.trend.er_avg"),
    ("saves_total", "reports.smm.trend.saves_total"),
]


def _build_trend(curr: dict, prev: dict) -> list:
    rows = []
    for key, label_key in _TREND_FIELDS:
        rows.append({
            "stage": key,
            "label": t(label_key),
            "value": curr.get(key),
            "prev_value": prev.get(key),
            "change_pct": _pct_change(curr.get(key), prev.get(key)),
        })
    return rows


def _fallback_main_fact(totals: dict, prev_totals: dict) -> str:
    """Без Anthropic-ключа (чи якщо виклик Opus не вдався) ПІДСУМОК все одно не порожній —
    головний факт рахується напряму з цифр, без AI: охват і ER періоду з дельтою до
    попереднього періоду (той самий підхід, що client_report.py::_fallback_main_fact)."""
    reach_line = f"{t('reports.smm.reach')}: {_fmt(totals.get('reach_total'))} ({_delta_pct_text(totals.get('reach_total'), prev_totals.get('reach_total'))})"
    er = totals.get("engagement_rate_avg")
    if er is not None:
        return f"{reach_line}, ER: {_fmt(er, '%')} ({_delta_pct_text(er, prev_totals.get('engagement_rate_avg'))})."
    return f"{reach_line}."


def _build_context_text(
    project_name, niche, report_type, date_from, date_to, prev_date_from, prev_date_to,
    account_metrics, prev_account_metrics, trend, organic_analysis, hook_stats, category_stats,
) -> str:
    lines = [
        f"Клиент/проект: «{project_name}»",
        f"Ниша/тематика: {niche or 'нет данных'}",
        f"Тип отчёта: {report_type} ({date_from} — {date_to})",
        f"Период сравнения (сразу предыдущий отрезок такой же длины): {prev_date_from} — {prev_date_to}",
        "",
        "МЕТРИКИ АККАУНТА ЗА ПЕРИОД (текущий период / предыдущий период):",
        f"Постов с данными: {account_metrics['posts_count']} / {prev_account_metrics['posts_count']}",
        f"Суммарный охват постов: {_fmt(account_metrics['reach_total'])} / {_fmt(prev_account_metrics['reach_total'])}",
        f"Вовлечённость (сумма реакций+сохранений+репостов): {_fmt(account_metrics['engagement_total'])} / {_fmt(prev_account_metrics['engagement_total'])}",
        f"Средний ER: {_fmt(account_metrics['engagement_rate_avg'], '%')} / {_fmt(prev_account_metrics['engagement_rate_avg'], '%')}",
        f"Сохранения: {_fmt(account_metrics['saves_total'])} / {_fmt(prev_account_metrics['saves_total'])}",
        "Переходы в профиль и прирост/отток подписчиков: нет данных (эти метрики сейчас технически не собираются — не выдумывай их).",
    ]

    lines.append("")
    lines.append("ДИНАМИКА К ПРЕДЫДУЩЕМУ ПЕРИОДУ:")
    for row in trend:
        change = f"{row['change_pct']:+.1f}%" if row["change_pct"] is not None else "нет данных для сравнения"
        lines.append(f"- {row['label']}: {row['value']} -> {row['prev_value']} ({change})")

    lines.append("")
    if organic_analysis.get("insufficient_data"):
        lines.append("ЩО ЗАХОДИТЬ (топ контента): недостаточно органических Reels с готовыми инсайтами за период — честно скажи это, не выдумывай топ.")
    else:
        if organic_analysis.get("low_sample_warning"):
            lines.append(f"ЩО ЗАХОДИТЬ (топ контента) — выборка маленькая ({organic_analysis['dataset_size']} рилсов), не делай самоуверенных выводов на этом объёме:")
        else:
            lines.append("ЩО ЗАХОДИТЬ — топ контента по ER за период:")
        for p in organic_analysis.get("top_er", [])[:5]:
            lines.append(f"- «{p['caption']}»: ER {p['engagement_rate']}%, охват {p['reach']}")
        if organic_analysis.get("best_hour"):
            bh = organic_analysis["best_hour"]
            lines.append(f"Лучшее время публикации: {bh['label']} (средний ER {bh['avg_er']}%, n={bh['count']})")
        if organic_analysis.get("best_weekday"):
            bw = organic_analysis["best_weekday"]
            lines.append(f"Лучший день публикации: {bw['label']} (средний ER {bw['avg_er']}%, n={bw['count']})")

    lines.append("")
    hook_summary = hook_stats.get("hook_type_summary") or []
    if hook_summary:
        lines.append("ХУК-АНАЛІЗ — какие заходы/хуки работают (индикатор удержания = % досмотра относительно длины видео):")
        for row in hook_summary[:8]:
            lines.append(f"- {row['type']}: индикатор удержания {row['avg_indicator']}% (n={row['count']})")
    else:
        lines.append("ХУК-АНАЛІЗ: нет расшифрованных Reels с определённым типом хука за период — честно скажи, что данных для вывода нет.")

    lines.append("")
    cat_with_data = [c for c in category_stats if c.get("organic_count")]
    if cat_with_data:
        lines.append("РУБРИКИ — эффективность за весь собранный период (не только текущий отрезок, рубрик мало и они не хранят даты назначения):")
        for row in cat_with_data[:10]:
            lines.append(
                f"- «{row['name']}»: ER {_fmt(row.get('avg_er'), '%')}, сохранения {_fmt(row.get('avg_saves_rate'), '%')}, "
                f"хук-индикатор {_fmt(row.get('avg_hook_indicator'), '%')} (n={row['organic_count']})"
            )
    else:
        lines.append("РУБРИКИ: рубрики не заведены или ни один пост не назначен — честно скажи это.")

    return "\n".join(lines)


def build_smm_report(report_type: str, date_from: str = None, date_to: str = None) -> dict:
    """Рахує СММ-звіт за період для АКТИВНОГО проєкту (ДЕННИЙ/ТИЖНЕВИЙ/довільний, з порівнянням
    до попереднього періоду такої ж довжини) — той самий контракт, що build_client_report()
    у app/client_report.py, тільки джерело даних органічне (media_cache.json), не Marketing API.
    Чесно повертає {"error": "..."}, якщо кеш медіа ще не синхронізований."""
    project = get_active_project()
    cfg = get_effective_config()
    niche = cfg.get("account_niche") or ""
    anthropic_key = cfg.get("anthropic_api_key")
    project_name = project.get("name") if project else ""

    try:
        since, until, prev_since, prev_until = _resolve_range(report_type, date_from, date_to)
    except AdsAPIError as e:
        return {"error": str(e)}

    try:
        from app.routes.metrics import load_cache

        cache = load_cache()
    except Exception:
        logger.exception("СММ-звіт: не вдалося прочитати media_cache.json")
        return {"error": t("reports.smm.msg.cache_error")}

    all_posts = cache.get("posts", [])
    if not all_posts:
        return {"error": t("reports.smm.msg.no_data")}

    posts = _filter_posts_by_period(all_posts, since, until)
    prev_posts = _filter_posts_by_period(all_posts, prev_since, prev_until)

    account_metrics = _account_metrics(posts)
    prev_account_metrics = _account_metrics(prev_posts)
    trend = _build_trend(account_metrics, prev_account_metrics)

    organic_posts = [p for p in posts if not p.get("is_ad")]
    organic_analysis = compute_organic_analysis(organic_posts)

    transcripts = load_transcripts()
    hook_stats = compute_hook_stats({"posts": organic_posts}, transcripts)
    # Рубрики навмисно рахуються по ВСІХ органічних постах з кешу (а не лише за період) —
    # призначення рілс -> рубрика не завʼязане на дату публікації, і рубрик зазвичай мало;
    # звужувати до періоду означало б майже завжди отримувати "n=0-1" по кожній рубриці.
    category_stats = compute_category_stats([p for p in all_posts if not p.get("is_ad")], transcripts)

    context_text = _build_context_text(
        project_name, niche, report_type, since.isoformat(), until.isoformat(),
        prev_since.isoformat(), prev_until.isoformat(),
        account_metrics, prev_account_metrics, trend, organic_analysis, hook_stats, category_stats,
    )

    summary, opus_note = {}, None
    if not anthropic_key:
        opus_note = t("reports.smm.msg.no_anthropic_key")
        summary = {"main_fact": _fallback_main_fact(account_metrics, prev_account_metrics)}
    else:
        try:
            from app.ads_opus import build_smm_report_prompt, call_opus, parse_client_report_response

            style_profile = load_style_profile()
            system_prompt, user_message = build_smm_report_prompt(context_text, style_profile, lang=current_lang())
            response_text = call_opus(anthropic_key, system_prompt, user_message, max_tokens=900)
            summary = parse_client_report_response(response_text)
            if not summary:
                summary = {"main_fact": response_text.strip()}
        except Exception as e:
            logger.warning("СММ-звіт: виклик Opus не вдався (%s)", e)
            opus_note = t("reports.smm.msg.opus_error", error=e)
            summary = {"main_fact": _fallback_main_fact(account_metrics, prev_account_metrics)}

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
        "ig_username": cache.get("ig_username", ""),
        "account_metrics": account_metrics,
        "prev_account_metrics": prev_account_metrics,
        "trend": trend,
        "top_content": organic_analysis,
        "hooks": hook_stats,
        "categories": category_stats,
        "summary": summary,
        "opus_note": opus_note,
    }
    save_smm_report(report)
    return report


def save_smm_report(report: dict) -> dict:
    path = _report_json_path(report["id"])
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=_reports_dir(), prefix=".smm_report_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    return report


def load_smm_reports() -> list:
    d = _reports_dir()
    reports = []
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                reports.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Пошкоджений СММ-звіт %s (%s) — пропускаю", name, e)
    reports.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
    return reports


def load_smm_report(report_id: str):
    path = _report_json_path(report_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_smm_report(report_id: str) -> bool:
    path = _report_json_path(report_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    pdf_path = _report_pdf_path(report_id)
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    return True


def load_cached_smm_pdf(report_id: str):
    path = _report_pdf_path(report_id)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def save_cached_smm_pdf(report_id: str, pdf_bytes: bytes):
    with open(_report_pdf_path(report_id), "wb") as f:
        f.write(pdf_bytes)
