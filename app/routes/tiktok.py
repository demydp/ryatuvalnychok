"""
OAuth-підключення TikTok (Login Kit v2, PKCE) + жива діагностика того, що API реально
віддає для підключеного акаунту (Этап діагностики — без цього неможливо чесно побудувати
вкладку "TikTok": набір полів, які реально повертає /v2/user/info//v2/video/list/, залежить
від схвалених scope конкретного застосунку і перевіряється лише живим викликом).

Потік:
1. GET /connect?project_id=... — генерує state+PKCE, кладе їх у Flask-сесію (той самий
   браузер повернеться на /callback, сесія переживає редірект туди-назад), редіректить
   на TikTok.
2. GET /callback — TikTok повертає code+state; звіряємо state із сесією, обмінюємо code
   на токени, тягнемо user info, зберігаємо зашифровано в Project, редіректимо назад у
   застосунок з коротким статусом у query-рядку (?tiktok=connected|error).
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, redirect, request, session

from app.i18n import t
from app.project_store import get_effective_config, get_project, update_active_project, update_project
from app.tiktok_api import (
    TikTokAPIError,
    TikTokConfigError,
    USER_INFO_FIELDS,
    VIDEO_FIELDS,
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
    generate_state,
    get_user_info_raw,
    is_configured,
    list_videos_raw,
)

tiktok_bp = Blueprint("tiktok", __name__)
logger = logging.getLogger("reels_dashboard")

_SESSION_KEY = "tiktok_oauth"


def _target_updater(project_id):
    if project_id:
        return lambda updates: update_project(project_id, updates)
    return update_active_project


@tiktok_bp.route("/status", methods=["GET"])
def status():
    """Стан підключення для конкретного (або активного) проєкту — без самих токенів,
    лише те, що безпечно показати у Настройках/вкладці TikTok."""
    project_id = request.args.get("project_id")
    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    return jsonify(
        {
            "configured": is_configured(),
            "connected": bool(cfg.get("tiktok_open_id")),
            "open_id": cfg.get("tiktok_open_id") or "",
            "username": cfg.get("tiktok_username") or "",
            "display_name": cfg.get("tiktok_display_name") or "",
            "avatar_url": cfg.get("tiktok_avatar_url") or "",
            "token_obtained_at": cfg.get("tiktok_token_obtained_at") or "",
            "access_token_expires_at": cfg.get("tiktok_access_token_expires_at") or "",
        }
    )


@tiktok_bp.route("/connect", methods=["GET"])
def connect():
    """Повноцінний редірект браузера (не fetch) — кнопка "Підключити TikTok" це звичайне
    посилання на цей роут."""
    project_id = request.args.get("project_id") or ""
    try:
        code_verifier, code_challenge = generate_pkce_pair()
        state = generate_state()
        authorize_url = build_authorize_url(state, code_challenge)
    except TikTokConfigError as e:
        return redirect(f"/?tab=settings&tiktok=error&tiktok_message={_q(str(e))}")

    session[_SESSION_KEY] = {
        "state": state,
        "code_verifier": code_verifier,
        "project_id": project_id,
    }
    return redirect(authorize_url)


@tiktok_bp.route("/callback", methods=["GET"])
def callback():
    error = request.args.get("error")
    if error:
        description = request.args.get("error_description") or error
        return redirect(f"/?tab=settings&tiktok=error&tiktok_message={_q(description)}")

    saved = session.pop(_SESSION_KEY, None)
    state = request.args.get("state")
    code = request.args.get("code")

    if not saved or not state or state != saved.get("state"):
        return redirect(f"/?tab=settings&tiktok=error&tiktok_message={_q(t('tiktok.msg.state_mismatch'))}")
    if not code:
        return redirect(f"/?tab=settings&tiktok=error&tiktok_message={_q(t('tiktok.msg.no_code'))}")

    project_id = saved.get("project_id") or None

    try:
        token_payload = exchange_code_for_token(code, saved["code_verifier"])
    except (TikTokAPIError, TikTokConfigError) as e:
        logger.warning("TikTok: обмін коду на токен не вдався: %s", e)
        return redirect(f"/?tab=settings&tiktok=error&tiktok_message={_q(str(e))}")

    access_token = token_payload["access_token"]

    try:
        user_info = get_user_info_raw(access_token).get("user", {})
    except TikTokAPIError as e:
        logger.warning("TikTok: user info після підключення не вдалось отримати: %s", e)
        user_info = {}

    now = datetime.now(timezone.utc)
    access_expires_at = now + timedelta(seconds=token_payload.get("expires_in", 0))
    refresh_expires_at = (
        now + timedelta(seconds=token_payload.get("refresh_expires_in", 0))
        if token_payload.get("refresh_expires_in")
        else None
    )

    _target_updater(project_id)(
        {
            "tiktok_access_token": access_token,
            "tiktok_refresh_token": token_payload.get("refresh_token", ""),
            "tiktok_open_id": token_payload.get("open_id") or user_info.get("open_id", ""),
            "tiktok_username": user_info.get("username", ""),
            "tiktok_display_name": user_info.get("display_name", ""),
            "tiktok_avatar_url": user_info.get("avatar_url", ""),
            "tiktok_token_obtained_at": now.isoformat(),
            "tiktok_access_token_expires_at": access_expires_at.isoformat(),
            "tiktok_refresh_token_expires_at": refresh_expires_at.isoformat() if refresh_expires_at else "",
        }
    )

    logger.info(
        "TikTok підключено: open_id=%s, username=%s, granted scope=%s",
        token_payload.get("open_id"), user_info.get("username"), token_payload.get("scope"),
    )
    return redirect("/?tab=settings&tiktok=connected")


@tiktok_bp.route("/disconnect", methods=["POST"])
def disconnect():
    body = request.get_json(force=True) or {}
    project_id = body.get("project_id")
    _target_updater(project_id)(
        {
            "tiktok_access_token": "",
            "tiktok_refresh_token": "",
            "tiktok_open_id": "",
            "tiktok_username": "",
            "tiktok_display_name": "",
            "tiktok_avatar_url": "",
            "tiktok_token_obtained_at": "",
            "tiktok_access_token_expires_at": "",
            "tiktok_refresh_token_expires_at": "",
        }
    )
    return jsonify({"ok": True})


@tiktok_bp.route("/diagnostic", methods=["GET"])
def diagnostic():
    """Жива перевірка: які саме поля /v2/user/info/ і /v2/video/list/ реально повертають
    для ЦЬОГО підключеного акаунту. Ніколи не кешується — по кнопці, як insights_diagnostic.py
    для Instagram (app/routes/hooks.py::metrics_diagnostic)."""
    project_id = request.args.get("project_id")
    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    access_token = cfg.get("tiktok_access_token")
    if not access_token:
        return jsonify({"error": t("tiktok.msg.not_connected")}), 400

    result = {"requested_user_fields": USER_INFO_FIELDS.split(","), "requested_video_fields": VIDEO_FIELDS.split(",")}

    try:
        user_raw = get_user_info_raw(access_token)
        user = user_raw.get("user", {})
        result["user_info"] = {
            "raw": user_raw,
            "fields_present": sorted(k for k in user.keys()),
            "fields_missing": sorted(f for f in USER_INFO_FIELDS.split(",") if f not in user),
        }
        logger.info("TikTok diagnostic user.info: present=%s missing=%s", result["user_info"]["fields_present"], result["user_info"]["fields_missing"])
    except TikTokAPIError as e:
        result["user_info"] = {"error": str(e)}
        logger.warning("TikTok diagnostic user.info error: %s", e)

    try:
        videos_raw = list_videos_raw(access_token, cursor=0, max_count=5)
        videos = videos_raw.get("videos", []) or []
        sample_fields = sorted(videos[0].keys()) if videos else []
        result["videos"] = {
            "raw": videos_raw,
            "count_returned": len(videos),
            "sample_fields_present": sample_fields,
            "fields_missing_in_sample": sorted(f for f in VIDEO_FIELDS.split(",") if f not in sample_fields) if videos else None,
        }
        logger.info("TikTok diagnostic video.list: count=%d sample_fields=%s", len(videos), sample_fields)
    except TikTokAPIError as e:
        result["videos"] = {"error": str(e)}
        logger.warning("TikTok diagnostic video.list error: %s", e)

    return jsonify(result)


def _q(text: str) -> str:
    from urllib.parse import quote

    return quote((text or "")[:300])
