from flask import Blueprint, jsonify, request

from app.categories import (
    add_category,
    assign_media,
    compute_category_stats,
    delete_category,
    load_categories,
    merge_categories,
    rename_category,
    replace_auto_detected,
)
from app.categories_ai import generate_categories_summary
from app.category_classifier import detect_categories, estimate_cost_usd
from app.i18n import current_lang, t
from app.project_store import get_effective_config
from app.routes.metrics import load_cache
from app.transcription import load_transcripts

categories_bp = Blueprint("categories", __name__)


@categories_bp.route("", methods=["GET"])
def get_categories():
    posts = load_cache().get("posts", [])
    transcripts = load_transcripts()
    data = load_categories()
    stats = compute_category_stats(posts, transcripts)

    reels = [
        {
            "id": p["id"],
            "caption": p.get("caption", ""),
            "permalink": p.get("permalink"),
            "thumbnail_url": p.get("thumbnail_url"),
            "timestamp": p.get("timestamp"),
            "is_ad": p.get("is_ad", False),
            "engagement_rate": p.get("engagement_rate"),
            "category_id": data["assignments"].get(p["id"]),
        }
        for p in posts
        if p.get("media_product_type") == "REELS"
    ]

    return jsonify(
        {
            "categories": stats,
            "reels": reels,
            "last_auto_detect_at": data.get("last_auto_detect_at"),
        }
    )


@categories_bp.route("/ai-summary", methods=["POST"])
def ai_summary():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("categories.msg.no_api_key")}), 400

    posts = load_cache().get("posts", [])
    transcripts = load_transcripts()
    cat_stats = compute_category_stats(posts, transcripts)
    try:
        summary = generate_categories_summary(api_key, current_lang(), cat_stats)
    except Exception as e:
        return jsonify({"error": t("categories.msg.ai_summary_error", error=e)}), 500

    return jsonify({"summary": summary})


@categories_bp.route("/auto-detect", methods=["POST"])
def auto_detect():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("categories.msg.no_api_key")}), 400

    posts = load_cache().get("posts", [])
    transcripts = load_transcripts()
    try:
        result = detect_categories(posts, transcripts, api_key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": t("settings.msg.anthropic_api_error", error=e)}), 500

    replace_auto_detected(result["categories"], result["assignments"], result["model"])
    stats = compute_category_stats(posts, transcripts)

    return jsonify(
        {
            "categories": stats,
            "analyzed_count": result["analyzed_count"],
            "truncated": result["truncated"],
            "estimated_cost_usd": round(
                estimate_cost_usd(result["usage"]["input_tokens"], result["usage"]["output_tokens"]), 5
            ),
        }
    )


@categories_bp.route("", methods=["POST"])
def create_category():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": t("categories.msg.enter_name")}), 400
    return jsonify({"category": add_category(name, source="manual")})


@categories_bp.route("/<category_id>", methods=["PATCH"])
def update_category(category_id):
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": t("categories.msg.enter_name")}), 400
    category = rename_category(category_id, name)
    if not category:
        return jsonify({"error": t("categories.msg.not_found")}), 404
    return jsonify({"category": category})


@categories_bp.route("/<category_id>", methods=["DELETE"])
def remove_category(category_id):
    if not delete_category(category_id):
        return jsonify({"error": t("categories.msg.not_found")}), 404
    return jsonify({"deleted": True})


@categories_bp.route("/merge", methods=["POST"])
def merge():
    body = request.get_json(force=True) or {}
    source_ids = body.get("source_ids") or []
    name = (body.get("name") or "").strip()
    if len(source_ids) < 2 or not name:
        return jsonify({"error": t("categories.msg.merge_requirements")}), 400
    try:
        category = merge_categories(source_ids, name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"category": category})


@categories_bp.route("/assign", methods=["POST"])
def assign():
    body = request.get_json(force=True) or {}
    media_id = body.get("media_id")
    category_id = body.get("category_id") or None
    if not media_id:
        return jsonify({"error": t("categories.msg.no_reel_specified")}), 400
    try:
        assigned = assign_media(media_id, category_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"media_id": media_id, "category_id": assigned})
