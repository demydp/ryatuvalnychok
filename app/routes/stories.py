import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from app.i18n import t
from app.instagram_api import (
    InstagramAPIError,
    fetch_active_stories,
    fetch_reach_follow_type_breakdown,
    fetch_story_insights,
)
from app.project_data_store import get_json, set_json
from app.project_store import get_effective_config

stories_bp = Blueprint("stories", __name__)
logger = logging.getLogger("reels_dashboard")

_STORIES_CACHE_KEY = "stories_history.json"

STORY_METRIC_FIELDS = (
    "reach", "replies", "navigation", "profile_activity", "profile_visits",
    "shares", "total_interactions", "follows",
)


def load_cache(project_id: str = None) -> dict:
    return get_json(
        _STORIES_CACHE_KEY,
        default={"stories": [], "reach_follow_type": None, "synced_at": None, "active_count": 0, "ig_username": ""},
        project_id=project_id,
    )


def save_cache(data: dict, project_id: str = None):
    set_json(_STORIES_CACHE_KEY, data, project_id=project_id)


def _build_story_record(story: dict, insight: dict, existing: dict = None) -> dict:
    now = _now_iso()
    record = {
        "id": story.get("id"),
        "media_type": story.get("media_type"),
        "media_product_type": story.get("media_product_type"),
        "timestamp": story.get("timestamp"),
        "permalink": story.get("permalink"),
        "thumbnail_url": story.get("thumbnail_url") or story.get("media_url"),
        "insights_status": insight["status"],
        "insights_reason": insight.get("reason"),
        "first_synced_at": (existing or {}).get("first_synced_at") or now,
        "last_synced_at": now,
    }

    metrics = insight.get("metrics", {})
    for field in STORY_METRIC_FIELDS:
        record[field] = metrics.get(field)

    # Сирі відповіді API — для звірки цифр, той самий підхід, що в app/routes/metrics.py
    record["_raw_insights"] = insight.get("raw", [])

    return record


def run_stories_sync(project_id: str = None) -> dict:
    """Тіло синка сторіс — спільна логіка для ручної кнопки та фонового авто-оновлення
    (див. app/scheduler.py). Instagram Graph API віддає /{ig-user-id}/stories лише живі сторіс
    (до ~24 год з публікації, інсайти доступні ще трохи довше), тому кожен синк ДОДАЄ нові записи
    до існуючої історії за id, а не перезаписує її — так дані нікуди не зникають після того, як
    сторіс сама зникне з Instagram."""
    cfg = get_effective_config(project_id)
    token = cfg["ig_access_token"]
    ig_user_id = cfg["ig_user_id"]

    if not token or not ig_user_id:
        return {"error": t("metrics.msg.setup_first")}

    cache = load_cache(project_id=project_id)
    existing_by_id = {s["id"]: s for s in cache.get("stories", [])}

    try:
        active_stories = fetch_active_stories(token, ig_user_id)
    except InstagramAPIError as e:
        return {"error": t("metrics.msg.media_load_error", error=e)}

    for story in active_stories:
        try:
            insight = fetch_story_insights(token, story["id"])
        except Exception as e:
            logger.error("Не удалось получить инсайты сторис %s: %s", story.get("id"), e)
            insight = {"status": "unavailable_error", "reason": t("metrics.reason.fetch_error", error=e)}
        record = _build_story_record(story, insight, existing_by_id.get(story["id"]))
        existing_by_id[record["id"]] = record

    reach_follow_type = fetch_reach_follow_type_breakdown(token, ig_user_id)

    result = {
        "stories": sorted(existing_by_id.values(), key=lambda r: r.get("timestamp") or "", reverse=True),
        "reach_follow_type": reach_follow_type,
        "active_count": len(active_stories),
        "ig_username": cfg.get("ig_username", ""),
        "synced_at": _now_iso(),
    }

    save_cache(result, project_id=project_id)
    return result


@stories_bp.route("/sync", methods=["POST"])
def sync_stories():
    result = run_stories_sync()
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@stories_bp.route("", methods=["GET"])
def get_stories():
    return jsonify(load_cache())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
