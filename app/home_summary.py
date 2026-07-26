"""
Сводка для стартовой вкладки "Головна" — быстрая статистика без лишних кликов и статус по
обоим направлениям (SMM/органика, таргет/реклама).

Органическая часть считается ТОЛЬКО из уже собранного data/media_cache.json (см.
app/routes/metrics.py) — без дополнительных живых вызовов Instagram API, поэтому открытие
"Головної" не задерживается синком. Рекламная часть переиспользует ту же логику, что и
предпросмотр дневного отчёта (app/daily_report.py) — тот же лёгкий live-запрос к Marketing
API, что пользователь и так видит на вкладке "Отчёты".

Честное правило как везде в проекте: нет кабинета/токена/данных за период — "нет данных"
с причиной, а не 0 и не выдумка.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.daily_report import build_daily_report

logger = logging.getLogger("reels_dashboard")

CONTENT_RECENT_DAYS = 7


def _load_metrics_cache() -> dict:
    from app.routes.metrics import load_cache

    return load_cache()


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


def _recent_organic_posts(posts: list, days: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for p in posts:
        if p.get("is_ad"):
            continue
        ts = _parse_ts(p.get("timestamp"))
        if ts and ts >= cutoff:
            out.append(p)
    return out


def _avg(values) -> float:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 2) if values else None


def build_content_summary() -> dict:
    """Охват/ER/skip rate за последние CONTENT_RECENT_DAYS дней + топ-рилс — только органика
    (реклама исключена, как и в app/analysis.py, иначе ER искажён платным трафиком)."""
    cache = _load_metrics_cache()
    posts = cache.get("posts") or []
    recent = _recent_organic_posts(posts, CONTENT_RECENT_DAYS)

    reach_values = [p.get("reach") for p in recent if p.get("reach") is not None]
    er_values = [p.get("engagement_rate") for p in recent]
    skip_values = [p.get("skip_rate") for p in recent]

    ranked_by_er = sorted(
        (p for p in recent if p.get("engagement_rate") is not None),
        key=lambda p: p["engagement_rate"],
        reverse=True,
    )
    top = ranked_by_er[0] if ranked_by_er else None

    return {
        "period_days": CONTENT_RECENT_DAYS,
        "posts_count": len(recent),
        "reach_total": sum(reach_values) if reach_values else None,
        "engagement_rate_avg": _avg(er_values),
        "skip_rate_avg": _avg(skip_values),
        "top_reel": (
            {
                "id": top.get("id"),
                "caption": (top.get("caption") or "")[:120],
                "permalink": top.get("permalink"),
                "thumbnail_url": top.get("thumbnail_url"),
                "engagement_rate": top.get("engagement_rate"),
                "reach": top.get("reach"),
            }
            if top else None
        ),
        "synced_at": cache.get("synced_at"),
        "total_media": cache.get("total_media", 0),
        "insights_ok": sum(1 for p in posts if p.get("insights_status") == "ok"),
        "ig_username": cache.get("ig_username", ""),
    }


def build_ads_summary() -> dict:
    """Активные кампании за сегодня + лидер по цене результата — тот же расчёт, что и
    /api/reports/preview (см. app/daily_report.py:build_daily_report)."""
    report = build_daily_report()
    if "error" in report:
        return {"available": False, "note": report["error"]}

    campaigns = report.get("campaigns") or []
    with_cost = [c for c in campaigns if (c.get("result") or {}).get("cost_per_result") is not None]
    best = min(with_cost, key=lambda c: c["result"]["cost_per_result"]) if with_cost else None

    return {
        "available": True,
        "campaigns_count": report["totals"]["campaigns_count"],
        "spend_today": report["totals"]["spend"],
        "best_campaign": (
            {
                "name": best.get("name"),
                "result_label": (best.get("result") or {}).get("label"),
                "result_value": (best.get("result") or {}).get("value"),
                "cost_per_result": (best.get("result") or {}).get("cost_per_result"),
            }
            if best else None
        ),
    }


def build_home_summary() -> dict:
    return {
        "content": build_content_summary(),
        "ads": build_ads_summary(),
    }
