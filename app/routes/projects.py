from flask import Blueprint, jsonify, request

from app.i18n import t
from app.project_store import (
    create_project,
    delete_project,
    get_active_project_id,
    load_projects,
    set_active_project_id,
    update_project,
)

projects_bp = Blueprint("projects", __name__)

# Те же поля, что раньше принимал общий allow-list в routes/settings.py:update_settings(),
# только теперь per-project, а не глобальные.
ALLOWED_FIELDS = {
    "name",
    "ig_access_token",
    "ads_account_id",
    "account_niche",
    "anthropic_api_key",
}


@projects_bp.route("", methods=["GET"])
def list_projects():
    return jsonify({"projects": load_projects(), "active_id": get_active_project_id()})


@projects_bp.route("", methods=["POST"])
def add_project():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": t("projects.msg.enter_name")}), 400
    project = create_project(name)
    return jsonify({"project": project})


@projects_bp.route("/<project_id>", methods=["PATCH"])
def edit_project(project_id):
    body = request.get_json(force=True) or {}
    updates = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    if "name" in updates and not updates["name"].strip():
        return jsonify({"error": t("projects.msg.enter_name")}), 400
    if "ads_account_id" in updates:
        from app.ads_api import normalize_account_id

        updates["ads_account_id"] = normalize_account_id(updates["ads_account_id"])
    if "anthropic_api_key" in updates:
        # Ключ поменяли — старую отметку "перевірено" для ЦЬОГО оверайду скидаємо, як і для
        # глобального ключа в routes/settings.py.
        from app.project_store import get_project

        current = get_project(project_id)
        if current and updates["anthropic_api_key"] != current.get("anthropic_api_key"):
            updates["anthropic_key_verified"] = False
    project = update_project(project_id, updates)
    if not project:
        return jsonify({"error": t("projects.msg.not_found")}), 404
    return jsonify({"project": project})


@projects_bp.route("/<project_id>", methods=["DELETE"])
def remove_project(project_id):
    if not delete_project(project_id):
        return jsonify({"error": t("projects.msg.cannot_delete_last")}), 400
    return jsonify({"deleted": True, "active_id": get_active_project_id()})


@projects_bp.route("/<project_id>/activate", methods=["POST"])
def activate_project(project_id):
    from app.project_store import get_project

    if not get_project(project_id):
        return jsonify({"error": t("projects.msg.not_found")}), 404
    set_active_project_id(project_id)
    return jsonify({"active_id": project_id})
