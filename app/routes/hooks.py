from flask import Blueprint, jsonify

from app.hooks_ai import compute_hook_stats, generate_hook_summary
from app.i18n import current_lang, t
from app.insights_diagnostic import run_diagnostic
from app.instagram_api import InstagramAPIError
from app.project_store import get_effective_config
from app.routes.metrics import load_cache
from app.transcription import (
    DEFAULT_MODEL,
    MODEL_SIZE_HINTS,
    is_model_downloaded,
    load_transcripts,
    process_media,
    save_transcript,
)

hooks_bp = Blueprint("hooks", __name__)


@hooks_bp.route("/model-status", methods=["GET"])
def model_status():
    model_name = get_effective_config().get("whisper_model") or DEFAULT_MODEL
    return jsonify(
        {
            "model": model_name,
            "downloaded": is_model_downloaded(model_name),
            "size_hint": MODEL_SIZE_HINTS.get(model_name, ""),
        }
    )


@hooks_bp.route("", methods=["GET"])
def get_hooks():
    cache = load_cache()
    transcripts = load_transcripts()
    stats = compute_hook_stats(cache, transcripts)
    return jsonify(
        {
            "items": stats["items"],
            "hook_type_summary": stats["hook_type_summary"],
            "skip_rate_summary": stats["skip_rate_summary"],
            "engagement_rate_summary": stats["engagement_rate_summary"],
            "ig_username": cache.get("ig_username", ""),
        }
    )


@hooks_bp.route("/ai-summary", methods=["POST"])
def ai_summary():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("hooks.msg.no_api_key")}), 400

    try:
        summary = generate_hook_summary(api_key, current_lang())
    except Exception as e:
        return jsonify({"error": t("hooks.msg.ai_summary_error", error=e)}), 500

    return jsonify({"summary": summary})


@hooks_bp.route("/metrics-diagnostic", methods=["GET"])
def metrics_diagnostic():
    """Эмпирическая проверка: какие продвинутые метрики хука/удержания реально отдаёт API
    для ЭТОГО аккаунта/токена. Живые запросы к Graph API по кнопке — не автоматически."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("hooks.msg.no_token")}), 400

    cache = load_cache()
    reels_with_insights = [
        p
        for p in cache.get("posts", [])
        if p.get("media_product_type") == "REELS" and p.get("insights_status") == "ok"
    ]
    if not reels_with_insights:
        return jsonify({"error": t("hooks.msg.no_reels_with_insights")}), 400

    sample = reels_with_insights[:3]
    media_ids = [p["id"] for p in sample]

    try:
        groups = run_diagnostic(token, media_ids)
    except Exception as e:
        return jsonify({"error": t("hooks.msg.graph_api_error", error=e)}), 500

    return jsonify({"groups": groups, "checked_media_ids": media_ids, "checked_count": len(media_ids)})


@hooks_bp.route("/transcribe/<media_id>", methods=["POST"])
def transcribe_one(media_id):
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("hooks.msg.no_token")}), 400

    try:
        record = process_media(
            token,
            media_id,
            model_name=cfg.get("whisper_model") or DEFAULT_MODEL,
            language=cfg.get("content_language") or None,
            anthropic_api_key=cfg.get("anthropic_api_key") or None,
        )
    except InstagramAPIError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": t("hooks.msg.transcription_error", error=e)}), 500

    save_transcript(media_id, record)
    return jsonify({"id": media_id, **record})
