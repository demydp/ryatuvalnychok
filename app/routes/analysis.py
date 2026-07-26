from flask import Blueprint, jsonify

from app.analysis import compute_organic_analysis
from app.i18n import current_lang, t
from app.insights_ai import generate_insights_summary
from app.project_store import get_effective_config
from app.routes.metrics import load_cache

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("", methods=["GET"])
def get_analysis():
    cache = load_cache()
    posts = cache.get("posts", [])
    if not posts:
        return jsonify({"error": t("insights.msg.no_synced_data")}), 400

    analysis = compute_organic_analysis(posts)
    analysis["ig_username"] = cache.get("ig_username", "")
    analysis["synced_at"] = cache.get("synced_at")
    return jsonify(analysis)


@analysis_bp.route("/ai-summary", methods=["POST"])
def ai_summary():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("insights.msg.no_api_key")}), 400

    cache = load_cache()
    posts = cache.get("posts", [])
    if not posts:
        return jsonify({"error": t("insights.msg.no_synced_data")}), 400

    analysis = compute_organic_analysis(posts)
    try:
        summary = generate_insights_summary(api_key, current_lang(), analysis)
    except Exception as e:
        return jsonify({"error": t("insights.msg.ai_summary_error", error=e)}), 500

    return jsonify({"summary": summary})
