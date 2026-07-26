import anthropic
from flask import Blueprint, jsonify, request

from app.app_restart import can_restart, restart_app
from app.config_store import load_config, save_config
from app.hook_classifier import MODEL_ID as ANTHROPIC_MODEL_ID
from app.i18n import t
from app.instagram_api import InstagramAPIError, get_account_info, resolve_ig_user
from app.network_info import PORT, get_local_ip
from app.project_store import get_effective_config, get_project, update_active_project, update_project
from app.token_refresh import check_token_status, refresh_if_needed

settings_bp = Blueprint("settings", __name__)


def _target_updater(project_id):
    """test-connection/test-anthropic-key/select-account используются і зі старого потоку
    (немає project_id -> активний проект), і з форми "Проєкт" в Налаштуваннях (є project_id ->
    саме цей проєкт, навіть якщо він ще не активний) — той самий ендпоінт для обох випадків."""
    if project_id:
        return lambda updates: update_project(project_id, updates)
    return update_active_project


@settings_bp.route("", methods=["GET"])
def get_settings():
    """Тільки глобальні налаштування (спільні для всіх проєктів) — per-project поля
    (IG-токен/Ad Account/ніша) віддає /api/projects."""
    cfg = load_config()
    return jsonify(cfg)


@settings_bp.route("/network-info", methods=["GET"])
def network_info():
    """Локальный IP + порт — чтобы открыть дашборд с телефона в той же Wi-Fi сети."""
    local_ip = get_local_ip()
    return jsonify(
        {
            "local_ip": local_ip,
            "port": PORT,
            "lan_url": f"http://{local_ip}:{PORT}",
            "local_url": f"http://127.0.0.1:{PORT}",
        }
    )


@settings_bp.route("", methods=["POST"])
def update_settings():
    """Тільки глобальні поля — IG-токен/Ad Account/ніша тепер зберігаються за проєктом
    через /api/projects (див. app/routes/projects.py)."""
    body = request.get_json(force=True) or {}
    allowed = {
        "anthropic_api_key",
        "max_media",
        "content_language",
        "whisper_model",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if "anthropic_api_key" in updates and updates["anthropic_api_key"] != load_config().get("anthropic_api_key"):
        updates["anthropic_key_verified"] = False
    if "max_media" in updates:
        try:
            updates["max_media"] = int(updates["max_media"])
        except (TypeError, ValueError):
            return jsonify({"error": t("settings.msg.max_media_not_number")}), 400
    if "content_language" in updates and updates["content_language"] not in ("", "uk", "ru"):
        return jsonify({"error": t("settings.msg.invalid_content_language")}), 400
    if "whisper_model" in updates and updates["whisper_model"] not in ("small", "medium"):
        return jsonify({"error": t("settings.msg.invalid_whisper_model")}), 400
    cfg = save_config(updates)
    return jsonify(cfg)


@settings_bp.route("/test-connection", methods=["POST"])
def test_connection():
    """project_id в тілі — опційний: форма проєкту в Налаштуваннях передає його явно (щоб
    перевіряти/зберігати саме цей проєкт, навіть якщо він не активний зараз); без нього —
    стара поведінка, працює з активним проєктом."""
    body = request.get_json(force=True) or {}
    project_id = body.get("project_id")
    fallback_cfg = get_project(project_id) if project_id else get_effective_config()
    token = body.get("ig_access_token") or (fallback_cfg or {}).get("ig_access_token")
    if not token:
        return jsonify({"error": t("settings.msg.enter_ig_token")}), 400

    try:
        resolved = resolve_ig_user(token)
    except InstagramAPIError as e:
        return jsonify({"error": str(e)}), 400

    if "accounts" in resolved:
        return jsonify({"multiple_accounts": resolved["accounts"]})

    try:
        info = get_account_info(token, resolved["id"])
    except InstagramAPIError as e:
        return jsonify({"error": str(e)}), 400

    _target_updater(project_id)(
        {
            "ig_access_token": token,
            "ig_user_id": info["id"],
            "ig_username": info.get("username", ""),
        }
    )

    return jsonify(
        {
            "id": info["id"],
            "username": info.get("username", ""),
            "name": info.get("name", ""),
            "followers_count": info.get("followers_count"),
            "media_count": info.get("media_count"),
        }
    )


@settings_bp.route("/test-anthropic-key", methods=["POST"])
def test_anthropic_key():
    """project_id — опційний: перевірка/збереження оверайду ключа для конкретного проєкту
    (без нього — старий потік для спільного глобального ключа, config.json)."""
    body = request.get_json(force=True) or {}
    project_id = body.get("project_id")
    if project_id:
        fallback_key = (get_project(project_id) or {}).get("anthropic_api_key")
    else:
        fallback_key = load_config().get("anthropic_api_key")
    key = body.get("anthropic_api_key") or fallback_key
    if not key:
        return jsonify({"error": t("settings.msg.enter_anthropic_key")}), 400

    client = anthropic.Anthropic(api_key=key)
    try:
        client.messages.create(
            model=ANTHROPIC_MODEL_ID,
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
    except anthropic.AuthenticationError:
        return jsonify({"error": t("settings.msg.anthropic_auth_error")}), 400
    except anthropic.PermissionDeniedError:
        return jsonify({"error": t("settings.msg.anthropic_permission_error")}), 400
    except anthropic.APIError as e:
        return jsonify({"error": t("settings.msg.anthropic_api_error", error=e)}), 400

    if project_id:
        update_project(project_id, {"anthropic_api_key": key, "anthropic_key_verified": True})
    else:
        save_config({"anthropic_api_key": key, "anthropic_key_verified": True})
    return jsonify({"ok": True})


@settings_bp.route("/select-account", methods=["POST"])
def select_account():
    """Если у токена доступ к нескольким IG-аккаунтам — пользователь выбирает нужный."""
    body = request.get_json(force=True) or {}
    project_id = body.get("project_id")
    ig_user_id = body.get("id")
    fallback_cfg = get_project(project_id) if project_id else get_effective_config()
    token = body.get("ig_access_token") or (fallback_cfg or {}).get("ig_access_token")
    if not ig_user_id or not token:
        return jsonify({"error": t("settings.msg.missing_account_data")}), 400

    try:
        info = get_account_info(token, ig_user_id)
    except InstagramAPIError as e:
        return jsonify({"error": str(e)}), 400

    _target_updater(project_id)(
        {
            "ig_access_token": token,
            "ig_user_id": info["id"],
            "ig_username": info.get("username", ""),
        }
    )
    return jsonify(
        {
            "id": info["id"],
            "username": info.get("username", ""),
            "name": info.get("name", ""),
            "followers_count": info.get("followers_count"),
            "media_count": info.get("media_count"),
        }
    )


@settings_bp.route("/token-status", methods=["GET"])
def token_status():
    """Статус IG-токена для пилюли в шапке и блока в Настройках. Никогда не 500-ит —
    если Meta недоступна, честно возвращает is_valid=None вместо падения."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"is_valid": None, "expires_at": None, "error": t("settings.msg.enter_ig_token")})

    status = check_token_status(token)
    return jsonify(
        {
            "is_valid": status["is_valid"],
            "expires_at": status["expires_at"].isoformat() if status["expires_at"] else None,
            "error": status["error"],
        }
    )


@settings_bp.route("/refresh-token", methods=["POST"])
def refresh_token():
    """Ручное продление по кнопке "Обновить токен" в Настройках."""
    result = refresh_if_needed(force=True)
    status_code = 400 if result["action"] == "failed" else 200
    return jsonify(result), status_code


@settings_bp.route("/restart", methods=["POST"])
def restart():
    """Кнопка "Перезапустить приложение" в Настройках — гарантированно поднимает свежий
    процесс поверх любых правок в коде, без ручного поиска и убийства pythonw.exe."""
    if not can_restart():
        return jsonify({"error": t("settings.msg.restart_unavailable_frozen")}), 400
    restart_app()
    return jsonify({"ok": True})
