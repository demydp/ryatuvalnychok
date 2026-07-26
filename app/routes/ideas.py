import anthropic
from flask import Blueprint, jsonify, request

from app.i18n import current_lang, t
from app.ideas import ALLOWED_MODELS, DEFAULT_MODEL, generate_ideas
from app.ideas_bank import add_idea, delete_idea, load_ideas_bank
from app.project_store import get_effective_config

ideas_bp = Blueprint("ideas", __name__)

_SAVE_FIELDS = ("format", "rubric", "audience_segment", "hook", "script", "script_steps", "slides", "cta", "why")


@ideas_bp.route("/generate", methods=["POST"])
def generate():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("ideas.msg.no_key")}), 400

    body = request.get_json(force=True) or {}
    model = body.get("model")
    if model not in ALLOWED_MODELS:
        model = DEFAULT_MODEL

    try:
        result = generate_ideas(api_key, model, current_lang())
    except anthropic.AuthenticationError:
        return jsonify({"error": t("settings.msg.anthropic_auth_error")}), 400
    except anthropic.PermissionDeniedError:
        return jsonify({"error": t("settings.msg.anthropic_permission_error")}), 400
    except anthropic.APIError as e:
        return jsonify({"error": t("settings.msg.anthropic_api_error", error=e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(result)


@ideas_bp.route("/bank", methods=["GET"])
def list_bank():
    return jsonify({"ideas": load_ideas_bank()})


@ideas_bp.route("/bank", methods=["POST"])
def save_to_bank():
    body = request.get_json(force=True) or {}
    idea = {k: (body.get(k) or None) for k in _SAVE_FIELDS}
    if not (idea.get("hook") or idea.get("script") or idea.get("script_steps") or idea.get("slides")):
        return jsonify({"error": t("ideas.msg.nothing_to_save")}), 400
    saved = add_idea(idea)
    return jsonify({"idea": saved})


@ideas_bp.route("/bank/<idea_id>", methods=["DELETE"])
def remove_from_bank(idea_id):
    if not delete_idea(idea_id):
        return jsonify({"error": t("ideas.msg.idea_not_found")}), 404
    return jsonify({"deleted": True})
