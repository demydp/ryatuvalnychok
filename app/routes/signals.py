from flask import Blueprint, jsonify

from app.signals import evaluate_signals
from app.signals_state import set_status

signals_bp = Blueprint("signals", __name__)


@signals_bp.route("", methods=["GET"])
def get_signals():
    signals = evaluate_signals()
    active = [s for s in signals if s["status"] == "new"]
    counts = {"red": 0, "yellow": 0, "green": 0}
    for s in active:
        if s["level"] in counts:
            counts[s["level"]] += 1
    return jsonify({
        "signals": signals,
        "active_count": len(active),
        "counts": counts,
    })


@signals_bp.route("/<signal_id>/dismiss", methods=["POST"])
def dismiss_signal(signal_id):
    return jsonify(set_status(signal_id, "dismissed"))


@signals_bp.route("/<signal_id>/done", methods=["POST"])
def complete_signal(signal_id):
    return jsonify(set_status(signal_id, "done"))
