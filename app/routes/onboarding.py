from flask import Blueprint, jsonify, request

from app.config_store import save_config
from app.i18n import t
from app.model_downloader import get_download_status, start_download
from app.project_store import get_effective_config
from app.transcription import DEFAULT_MODEL, is_model_downloaded

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("/status", methods=["GET"])
def status():
    cfg = get_effective_config()
    return jsonify(
        {
            "setup_completed": bool(cfg.get("setup_completed")),
            "ig_ok": bool(cfg.get("ig_user_id")),
            "ig_username": cfg.get("ig_username", ""),
            "ads_ok": bool(cfg.get("ads_account_id")),
            "ads_account_id": cfg.get("ads_account_id", ""),
            "anthropic_ok": bool(cfg.get("anthropic_key_verified")),
            "model_downloaded": is_model_downloaded(DEFAULT_MODEL),
        }
    )


@onboarding_bp.route("/complete", methods=["POST"])
def complete():
    cfg = get_effective_config()
    if not (cfg.get("ig_user_id") and cfg.get("ads_account_id") and cfg.get("anthropic_key_verified")):
        return jsonify({"error": t("onboarding.msg.not_ready")}), 400
    save_config({"setup_completed": True})
    return jsonify({"ok": True})


@onboarding_bp.route("/download-model", methods=["POST"])
def download_model():
    body = request.get_json(force=True) or {}
    model_name = body.get("model") or DEFAULT_MODEL
    start_download(model_name)
    return jsonify({"ok": True})


@onboarding_bp.route("/download-model/status", methods=["GET"])
def download_model_status():
    return jsonify(get_download_status())
