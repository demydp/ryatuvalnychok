"""
Банк збережених ідей контенту (вкладка "Ідеї") — той самий патерн, що app/saved_scripts.py:
кожна збережена ідея пишеться на диск одразу, без окремої кнопки синку.
"""
import uuid
from datetime import datetime, timezone

from app.project_data_store import get_json, set_json

_KEY = "ideas_bank.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ideas_bank() -> list:
    return get_json(_KEY, default=[])


def save_ideas_bank(items: list):
    set_json(_KEY, items)


def add_idea(record: dict) -> dict:
    items = load_ideas_bank()
    record = dict(record)
    record["id"] = uuid.uuid4().hex[:12]
    record.setdefault("created_at", now_iso())
    items.insert(0, record)  # новые сверху
    save_ideas_bank(items)
    return record


def delete_idea(idea_id: str) -> bool:
    items = load_ideas_bank()
    remaining = [i for i in items if i["id"] != idea_id]
    if len(remaining) == len(items):
        return False
    save_ideas_bank(remaining)
    return True
