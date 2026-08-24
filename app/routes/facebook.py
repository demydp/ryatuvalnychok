import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from app.facebook_api import FacebookAPIError, fetch_page_posts, get_page_summary, resolve_fb_pages
from app.i18n import t
from app.project_data_store import get_json, set_json
from app.project_store import get_effective_config

facebook_bp = Blueprint("facebook", __name__)
logger = logging.getLogger("reels_dashboard")

_FACEBOOK_CACHE_KEY = "facebook_pages.json"


def load_cache(project_id: str = None) -> dict:
    return get_json(_FACEBOOK_CACHE_KEY, default={"pages": [], "synced_at": None}, project_id=project_id)


def save_cache(data: dict, project_id: str = None):
    set_json(_FACEBOOK_CACHE_KEY, data, project_id=project_id)


def run_facebook_sync(project_id: str = None) -> dict:
    """Тянет страницы Facebook, до которых у уже сохранённого IG/FB Business Login токена
    есть доступ, и для каждой — только подтверждённо рабочие данные (см. app/facebook_api.py):
    fan_count/followers_count и список последних постов без метрик вовлечённости."""
    cfg = get_effective_config(project_id)
    token = cfg["ig_access_token"]

    if not token:
        return {"error": t("metrics.msg.setup_first")}

    try:
        pages = resolve_fb_pages(token)
    except FacebookAPIError as e:
        return {"error": str(e)}

    if not pages:
        return {"error": t("facebook.msg.no_pages")}

    result_pages = []
    for page in pages:
        page_id, page_token = page["id"], page["access_token"]
        try:
            summary = get_page_summary(page_id, page_token)
        except FacebookAPIError as e:
            logger.error("Не удалось получить сводку по странице %s: %s", page_id, e)
            summary = {"id": page_id, "name": page["name"], "fan_count": None, "followers_count": None}

        try:
            posts = fetch_page_posts(page_id, page_token)
        except FacebookAPIError as e:
            logger.error("Не удалось получить посты страницы %s: %s", page_id, e)
            posts = []

        result_pages.append(
            {
                "id": page_id,
                "name": summary.get("name") or page["name"],
                "fan_count": summary.get("fan_count"),
                "followers_count": summary.get("followers_count"),
                "posts": posts,
            }
        )

    result = {"pages": result_pages, "synced_at": _now_iso()}
    save_cache(result, project_id=project_id)
    return result


@facebook_bp.route("/sync", methods=["POST"])
def sync_facebook():
    result = run_facebook_sync()
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@facebook_bp.route("", methods=["GET"])
def get_facebook():
    return jsonify(load_cache())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
