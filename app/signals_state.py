"""
Состояние сигналов (вкладка/блок "Сигнали") — какие алерты пользователь уже отклонил
или отметил выполненными, чтобы один и тот же сигнал не показывался снова при каждом
пересчёте правил. Тот же паттерн, что app/ads_kpi.py/app/daily_plan.py: отдельный JSON
в data/, не секрет конфига, атомарная запись.

ID сигнала намеренно строится в app/signals.py так, чтобы оставаться стабильным, пока
условие живёт (например, включает since_date усталости крео или ISO-неделю для вялотекущих
метрик) — так "Відхилити" реально прячет именно ЭТУ ситуацию, а не глушит правило навсегда.
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from app.project_store import project_data_dir

_lock = threading.Lock()


def _state_path() -> str:
    return os.path.join(project_data_dir(), "signals_state.json")

# Записи по сигналам, которых давно не пересчитывали (сама ситуация явно неактуальна),
# просто мусор в файле — чистим лениво при каждой загрузке, как в daily_plan.py.
PRUNE_AFTER_DAYS = 90


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_raw() -> dict:
    if not os.path.exists(_state_path()):
        return {}
    with _lock:
        try:
            with open(_state_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_state_path()), prefix=".signals_state_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _state_path())
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def load_state() -> dict:
    """{signal_id: {"status": "dismissed"|"done", "updated_at": iso}}, с чисткой протухших записей."""
    data = _load_raw()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    pruned = {sid: v for sid, v in data.items() if v.get("updated_at", "") >= cutoff}
    if len(pruned) != len(data):
        _save(pruned)
    return pruned


def set_status(signal_id: str, status: str) -> dict:
    data = _load_raw()
    data[signal_id] = {"status": status, "updated_at": _now_iso()}
    _save(data)
    return data[signal_id]
