from flask import Blueprint, jsonify, request

from app.i18n import t
from app.update_checker import apply_update, check_for_update

updates_bp = Blueprint("updates", __name__)


@updates_bp.route("/check", methods=["GET"])
def check():
    result = check_for_update()
    if "error" in result:
        # Пока не опубликован реальный GitHub Release, UPDATE_MANIFEST_URL — плейсхолдер
        # и всегда отвечает 404 (см. app/update_checker.py). Это не ошибка с точки зрения
        # пользователя — неотличимо от "обновлений нет", поэтому не пугаем красным текстом.
        return jsonify({"update_available": False})
    return jsonify(result)


@updates_bp.route("/apply", methods=["POST"])
def apply():
    body = request.get_json(force=True) or {}
    url = body.get("url")
    if not url:
        return jsonify({"error": t("updates.msg.missing_url")}), 400
    apply_update(url)
    return jsonify({"ok": True})
