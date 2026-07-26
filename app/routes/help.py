from flask import Blueprint, jsonify

from app.i18n import current_lang
from app.metrics_help import load_metrics_help

help_bp = Blueprint("help", __name__)


@help_bp.route("/metrics", methods=["GET"])
def get_metrics_help():
    return jsonify(load_metrics_help(current_lang()))
