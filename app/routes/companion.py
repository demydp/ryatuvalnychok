import anthropic
from flask import Blueprint, jsonify, request

from app.companion import ALLOWED_MODELS, DEFAULT_MODEL, chat
from app.companion_history import append_exchange, clear_companion_history, load_companion_history
from app.i18n import current_lang, t
from app.project_store import get_effective_config

companion_bp = Blueprint("companion", __name__)

MAX_HISTORY_MESSAGES = 20


def _sanitize_history(raw: list, message: str) -> list:
    history = []
    for item in raw or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})
    history = history[-MAX_HISTORY_MESSAGES:]
    history.append({"role": "user", "content": message})
    return history


@companion_bp.route("/chat", methods=["POST"])
def companion_chat():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("companion.msg.no_key")}), 400

    body = request.get_json(force=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": t("companion.msg.empty_message")}), 400

    model = body.get("model")
    if model not in ALLOWED_MODELS:
        model = DEFAULT_MODEL

    # Джерело правди для діалогу — те, що вже збережено на диску (app/companion_history.py),
    # а не те, що прислав браузер: так продовження розмови однакове незалежно від того, чи
    # клієнт щойно перезавантажив сторінку і відновив історію з /history, чи ще тримає її
    # в пам'яті з поточної сесії.
    stored = load_companion_history()
    history = _sanitize_history(stored, message)

    try:
        reply = chat(api_key, model, current_lang(), history)
    except anthropic.AuthenticationError:
        return jsonify({"error": t("settings.msg.anthropic_auth_error")}), 400
    except anthropic.PermissionDeniedError:
        return jsonify({"error": t("settings.msg.anthropic_permission_error")}), 400
    except anthropic.APIError as e:
        return jsonify({"error": t("settings.msg.anthropic_api_error", error=e)}), 400

    append_exchange(message, reply)
    return jsonify({"reply": reply})


@companion_bp.route("/history", methods=["GET"])
def companion_history():
    return jsonify({"history": load_companion_history()})


@companion_bp.route("/history", methods=["DELETE"])
def companion_clear_history():
    clear_companion_history()
    return jsonify({"cleared": True})
