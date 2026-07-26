from flask import Blueprint, jsonify, request

from app.daily_plan import add_task, delete_task, get_today_tasks, toggle_task, update_task_text
from app.home_summary import build_home_summary
from app.i18n import t

home_bp = Blueprint("home", __name__)


@home_bp.route("/summary", methods=["GET"])
def get_summary():
    return jsonify(build_home_summary())


@home_bp.route("/plan", methods=["GET"])
def get_plan():
    return jsonify({"tasks": get_today_tasks()})


@home_bp.route("/plan", methods=["POST"])
def post_plan():
    body = request.get_json(force=True) or {}
    try:
        task = add_task(body.get("text"))
    except ValueError:
        return jsonify({"error": t("home.plan.msg.empty_text")}), 400
    return jsonify(task), 201


@home_bp.route("/plan/<task_id>/toggle", methods=["POST"])
def post_plan_toggle(task_id):
    task = toggle_task(task_id)
    if not task:
        return jsonify({"error": t("home.plan.msg.task_not_found")}), 404
    return jsonify(task)


@home_bp.route("/plan/<task_id>", methods=["PUT"])
def put_plan(task_id):
    body = request.get_json(force=True) or {}
    try:
        task = update_task_text(task_id, body.get("text"))
    except ValueError:
        return jsonify({"error": t("home.plan.msg.empty_text")}), 400
    if not task:
        return jsonify({"error": t("home.plan.msg.task_not_found")}), 404
    return jsonify(task)


@home_bp.route("/plan/<task_id>", methods=["DELETE"])
def delete_plan(task_id):
    if not delete_task(task_id):
        return jsonify({"error": t("home.plan.msg.task_not_found")}), 404
    return jsonify({"id": task_id, "deleted": True})
