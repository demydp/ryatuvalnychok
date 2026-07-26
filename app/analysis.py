"""
Анализ "Что заходит" — считается ТОЛЬКО по органическим Reels (media_product_type == REELS,
insights_status == "ok", is_ad != True). У постов с рекламой ER искажён: лайки/сохранения
считаются с общего (органика + платный) трафика, а reach в Graph API органический —
делить одно на другое нечестно, поэтому такие посты полностью исключаются из выборки.

Никаких LLM здесь нет — только статистика по цифрам, которые реально есть в API.
Там, где данных недостаточно (нет длины видео, маленькая выборка) — честно говорим об этом,
а не выдумываем вывод.
"""
from collections import defaultdict
from datetime import datetime
from statistics import mean

from app.i18n import t

MIN_SAMPLE_FOR_CONFIDENT_BUCKET = 2
LOW_SAMPLE_THRESHOLD = 8

HOUR_BUCKET_KEYS = [
    ("analysis.hour.night", range(0, 6)),
    ("analysis.hour.morning", range(6, 12)),
    ("analysis.hour.day", range(12, 18)),
    ("analysis.hour.evening", range(18, 24)),
]

WEEKDAY_KEYS = [
    "analysis.weekday.mon",
    "analysis.weekday.tue",
    "analysis.weekday.wed",
    "analysis.weekday.thu",
    "analysis.weekday.fri",
    "analysis.weekday.sat",
    "analysis.weekday.sun",
]


def compute_organic_analysis(posts: list) -> dict:
    reels = [p for p in posts if p.get("media_product_type") == "REELS"]
    reels_with_data = [p for p in reels if p.get("insights_status") == "ok" and p.get("reach") is not None]
    organic = [p for p in reels_with_data if not p.get("is_ad")]

    result = {
        "total_reels": len(reels),
        "reels_with_insights": len(reels_with_data),
        "ad_excluded_count": len(reels_with_data) - len(organic),
        "no_insights_excluded_count": len(reels) - len(reels_with_data),
        "dataset_size": len(organic),
        "low_sample_warning": len(organic) < LOW_SAMPLE_THRESHOLD,
    }

    if not organic:
        result["insufficient_data"] = True
        return result
    result["insufficient_data"] = False

    by_er_desc = sorted(organic, key=lambda p: p["engagement_rate"], reverse=True)
    by_er_asc = sorted(organic, key=lambda p: p["engagement_rate"])

    result["top_er"] = _brief(by_er_desc[:5])
    result["bottom_er"] = _brief(list(reversed(by_er_asc[:5])))

    with_saves = [p for p in organic if (p.get("saved") or 0) > 0]
    result["top_saves_rate"] = _brief(sorted(with_saves, key=lambda p: p["saves_rate"], reverse=True)[:5])
    result["saves_note"] = None if with_saves else t("analysis.note.no_saves")

    with_shares = [p for p in organic if (p.get("shares") or 0) > 0]
    result["top_shares"] = _brief(
        sorted(with_shares, key=lambda p: p["shares"], reverse=True)[:5], extra=("shares",)
    )
    result["shares_note"] = None if with_shares else t("analysis.note.no_shares")

    result["results_top"] = _brief(
        sorted(organic, key=lambda p: p.get("total_interactions") or 0, reverse=True)[:5],
        extra=("like_count", "comments_count", "saved", "shares", "total_interactions"),
    )

    result["by_hour"] = _hour_breakdown(organic)
    result["by_weekday"] = _weekday_breakdown(organic)
    result["best_hour"] = _best_bucket(result["by_hour"])
    result["best_weekday"] = _best_bucket(result["by_weekday"])

    result["video_length_note"] = t("analysis.note.video_length_unavailable")

    result["recommendations"] = _build_recommendations(organic, by_er_desc, by_er_asc, result)

    return result


def _brief(posts: list, extra: tuple = ()) -> list:
    out = []
    for p in posts:
        item = {
            "id": p["id"],
            "caption": (p.get("caption") or "")[:80],
            "permalink": p.get("permalink"),
            "thumbnail_url": p.get("thumbnail_url"),
            "timestamp": p.get("timestamp"),
            "reach": p.get("reach"),
            "engagement_rate": p.get("engagement_rate"),
        }
        for field in extra:
            item[field] = p.get(field)
        out.append(item)
    return out


def _parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _hour_breakdown(organic: list) -> list:
    buckets = defaultdict(list)
    for p in organic:
        dt = _parse_ts(p.get("timestamp"))
        if not dt:
            continue
        for label_key, hours in HOUR_BUCKET_KEYS:
            if dt.hour in hours:
                buckets[label_key].append(p["engagement_rate"])
                break
    return [
        {"label": t(label_key), "count": len(buckets[label_key]), "avg_er": round(mean(buckets[label_key]), 2)}
        for label_key, _ in HOUR_BUCKET_KEYS
        if buckets[label_key]
    ]


def _weekday_breakdown(organic: list) -> list:
    buckets = defaultdict(list)
    for p in organic:
        dt = _parse_ts(p.get("timestamp"))
        if not dt:
            continue
        buckets[WEEKDAY_KEYS[dt.weekday()]].append(p["engagement_rate"])
    return [
        {"label": t(label_key), "count": len(buckets[label_key]), "avg_er": round(mean(buckets[label_key]), 2)}
        for label_key in WEEKDAY_KEYS
        if buckets[label_key]
    ]


def _best_bucket(breakdown: list):
    confident = [b for b in breakdown if b["count"] >= MIN_SAMPLE_FOR_CONFIDENT_BUCKET]
    if not confident:
        return None
    return max(confident, key=lambda b: b["avg_er"])


def _caption_stats(posts: list) -> dict:
    if not posts:
        return {"avg_words": None, "question_share": None}
    word_counts = [len((p.get("caption") or "").split()) for p in posts]
    question_count = sum(1 for p in posts if "?" in (p.get("caption") or ""))
    return {
        "avg_words": round(mean(word_counts), 1),
        "question_share": round(question_count / len(posts) * 100),
    }


def _build_recommendations(organic: list, by_er_desc: list, by_er_asc: list, result: dict) -> list:
    recs = []
    n = len(organic)

    top5 = by_er_desc[:5]
    bottom5 = by_er_asc[:5]

    if len(top5) >= 2 and len(bottom5) >= 2:
        top_avg = round(mean(p["engagement_rate"] for p in top5), 2)
        bottom_avg = round(mean(p["engagement_rate"] for p in bottom5), 2)
        if bottom_avg > 0:
            ratio = round(top_avg / bottom_avg, 1)
            recs.append(t("analysis.rec.top_bottom_gap", n=len(top5), top_avg=top_avg, bottom_avg=bottom_avg, ratio=ratio))
        else:
            recs.append(t("analysis.rec.top_bottom_gap_zero", n=len(top5), top_avg=top_avg))

    top_stats = _caption_stats(top5)
    bottom_stats = _caption_stats(bottom5)
    if top_stats["question_share"] is not None and bottom_stats["question_share"] is not None:
        diff = top_stats["question_share"] - bottom_stats["question_share"]
        if diff >= 20:
            recs.append(t(
                "analysis.rec.question_more_top",
                top_share=top_stats["question_share"], bottom_share=bottom_stats["question_share"],
            ))
        elif diff <= -20:
            recs.append(t(
                "analysis.rec.question_more_bottom",
                top_share=top_stats["question_share"], bottom_share=bottom_stats["question_share"],
            ))

    if top_stats["avg_words"] is not None and bottom_stats["avg_words"] is not None:
        word_diff = top_stats["avg_words"] - bottom_stats["avg_words"]
        if abs(word_diff) >= 5:
            direction = t("analysis.rec.shorter") if word_diff < 0 else t("analysis.rec.longer")
            recs.append(t(
                "analysis.rec.caption_length",
                direction=direction, top_words=top_stats["avg_words"], bottom_words=bottom_stats["avg_words"],
            ))

    if result.get("saves_note"):
        recs.append(result["saves_note"])

    if result.get("best_hour"):
        bh = result["best_hour"]
        recs.append(t("analysis.rec.best_hour", label=bh["label"], avg_er=bh["avg_er"], count=bh["count"]))
    else:
        recs.append(t("analysis.rec.no_best_hour"))

    if result.get("best_weekday"):
        bw = result["best_weekday"]
        recs.append(t("analysis.rec.best_weekday", label=bw["label"], avg_er=bw["avg_er"], count=bw["count"]))
    else:
        recs.append(t("analysis.rec.no_best_weekday"))

    if result.get("low_sample_warning"):
        recs.append(t("analysis.rec.low_sample", n=n))

    return recs
