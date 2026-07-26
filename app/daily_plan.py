"""
"Мій план на день" (вкладка "Головна") — простой чек-лист задач на сегодня, хранится
локально в data/daily_plan.json. Невыполненные задачи автоматически переносятся на
следующий день при первом обращении в новый календарный день (локальное время машины) —
пользователю не нужно вручную копировать список, если вчера не успел.

Выполненные задачи остаются "приклеены" к дню, когда их отметили — это не журнал/история
(отдельной вкладки для неё нет), а просто чтобы не потерять сам факт до следующей чистки.
"""
import json
import os
import tempfile
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from app.project_store import project_data_dir

_lock = threading.Lock()


def _plan_path() -> str:
    return os.path.join(project_data_dir(), "daily_plan.json")

# Выполненные задачи старше этого — просто мусор в файле, не показываются нигде (нет вкладки
# истории) и только раздувают daily_plan.json. Чистим лениво при каждой загрузке.
PRUNE_DONE_AFTER_DAYS = 60


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not os.path.exists(_plan_path()):
        return {"tasks": []}
    try:
        with open(_plan_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"tasks": []}
    data.setdefault("tasks", [])
    return data


def _save(data: dict):
    os.makedirs(os.path.dirname(_plan_path()), exist_ok=True)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_plan_path()), prefix=".daily_plan_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _plan_path())
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def _prune_old_done(tasks: list) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_DONE_AFTER_DAYS)).date().isoformat()
    return [tsk for tsk in tasks if not (tsk.get("done") and tsk.get("date", "") < cutoff)]


def _carry_over_and_prune(data: dict) -> bool:
    """Переносит невыполненные задачи из прошлых дней на сегодня и чистит старые выполненные.
    Возвращает True, если данные изменились (тогда вызывающий код должен сохранить файл)."""
    today = _today()
    changed = False

    for task in data["tasks"]:
        if not task.get("done") and task.get("date", "") < today:
            task["date"] = today
            changed = True

    pruned = _prune_old_done(data["tasks"])
    if len(pruned) != len(data["tasks"]):
        data["tasks"] = pruned
        changed = True

    return changed


def get_today_tasks() -> list:
    """Задачи на сегодня — с уже применённым переносом невыполненных с прошлых дней."""
    data = _load()
    if _carry_over_and_prune(data):
        _save(data)

    today = _today()
    todays = [t for t in data["tasks"] if t.get("date") == today]
    # Невыполненные сверху (это то, чем занимаемся сегодня), внутри группы — по порядку добавления.
    todays.sort(key=lambda t: (t.get("done", False), t.get("created_at", "")))
    return todays


def add_task(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty task text")

    data = _load()
    _carry_over_and_prune(data)

    task = {
        "id": uuid.uuid4().hex[:10],
        "text": text,
        "done": False,
        "date": _today(),
        "created_at": _now_iso(),
        "done_at": None,
    }
    data["tasks"].append(task)
    _save(data)
    return task


def toggle_task(task_id: str):
    data = _load()
    _carry_over_and_prune(data)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        return None
    task["done"] = not task.get("done", False)
    task["done_at"] = _now_iso() if task["done"] else None
    _save(data)
    return task


def update_task_text(task_id: str, text: str):
    text = (text or "").strip()
    if not text:
        raise ValueError("empty task text")

    data = _load()
    _carry_over_and_prune(data)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        return None
    task["text"] = text
    _save(data)
    return task


def delete_task(task_id: str) -> bool:
    data = _load()
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    changed = len(data["tasks"]) != before
    if changed:
        _save(data)
    return changed
