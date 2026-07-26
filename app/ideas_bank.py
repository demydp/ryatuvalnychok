"""
Банк збережених ідей контенту (вкладка "Ідеї") — той самий патерн, що app/saved_scripts.py:
кожна збережена ідея пишеться на диск одразу, без окремої кнопки синку.
"""
import json
import os
import uuid
from datetime import datetime, timezone

from app.project_store import project_data_dir


def _ideas_bank_path() -> str:
    return os.path.join(project_data_dir(), "ideas_bank.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ideas_bank() -> list:
    if not os.path.exists(_ideas_bank_path()):
        return []
    with open(_ideas_bank_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def save_ideas_bank(items: list):
    os.makedirs(os.path.dirname(_ideas_bank_path()), exist_ok=True)
    with open(_ideas_bank_path(), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


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
