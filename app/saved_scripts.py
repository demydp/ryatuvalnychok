"""
Сохранённые сгенерированные скрипты. Каждый сгенерированный скрипт пишется на диск
автоматически (см. app/routes/generator.py) — ничего не теряется при перезапуске.
"""
import json
import os
import uuid
from datetime import datetime, timezone

from app.project_store import project_data_dir


def _saved_scripts_path() -> str:
    return os.path.join(project_data_dir(), "saved_scripts.json")

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


def load_saved_scripts() -> list:
    if not os.path.exists(_saved_scripts_path()):
        return []
    with open(_saved_scripts_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def save_saved_scripts(scripts: list):
    os.makedirs(os.path.dirname(_saved_scripts_path()), exist_ok=True)
    with open(_saved_scripts_path(), "w", encoding="utf-8") as f:
        json.dump(scripts, f, ensure_ascii=False, indent=2)


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
