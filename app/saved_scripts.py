"""
Сохранённые сгенерированные скрипты. Каждый сгенерированный скрипт пишется на диск
автоматически (см. app/routes/generator.py) — ничего не теряется при перезапуске.
"""
import uuid
from datetime import datetime, timezone

from app.project_data_store import get_json, set_json

_KEY = "saved_scripts.json"

_FIELD_DEFAULTS = {
    "is_favorite": False,
    "linked_media_id": None,
    "linked_at": None,
    "verdict": None,
    "verdict_reason": None,
    "verdict_metrics": [],
    "verdict_computed_at": None,
    "baseline_used": None,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_saved_scripts(project_id: str = None) -> list:
    return get_json(_KEY, default=[], project_id=project_id)


def save_saved_scripts(scripts: list, project_id: str = None):
    set_json(_KEY, scripts, project_id=project_id)


def add_script(record: dict) -> dict:
    scripts = load_saved_scripts()
    record = dict(record)
    record["id"] = uuid.uuid4().hex[:12]
    record.setdefault("created_at", now_iso())
    for key, default in _FIELD_DEFAULTS.items():
        record.setdefault(key, default)
    scripts.insert(0, record)  # новые сверху
    save_saved_scripts(scripts)
    return record


def get_script(script_id: str):
    scripts = load_saved_scripts()
    return next((s for s in scripts if s["id"] == script_id), None)


def update_script(script_id: str, updates: dict):
    scripts = load_saved_scripts()
    for s in scripts:
        if s["id"] == script_id:
            s.update(updates)
            save_saved_scripts(scripts)
            return s
    return None


def delete_script(script_id: str) -> bool:
    scripts = load_saved_scripts()
    remaining = [s for s in scripts if s["id"] != script_id]
    if len(remaining) == len(scripts):
        return False
    save_saved_scripts(remaining)
    return True
