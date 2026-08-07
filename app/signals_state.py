"""
Состояние сигналов (вкладка/блок "Сигнали") — какие алерты пользователь уже отклонил
или отметил выполненными, чтобы один и тот же сигнал не показывался снова при каждом
пересчёте правил. Тот же паттерн, что app/ads_kpi.py/app/daily_plan.py: отдельный JSON
в data/, не секрет конфига, атомарная запись.

ID сигнала намеренно строится в app/signals.py так, чтобы оставаться стабильным, пока
условие живёт (например, включает since_date усталости крео или ISO-неделю для вялотекущих
метрик) — так "Відхилити" реально прячет именно ЭТУ ситуацию, а не глушит правило навсегда.
"""
from datetime import datetime, timedelta, timezone

from app.project_data_store import get_json, set_json

_KEY = "signals_state.json"

# Записи по сигналам, которых давно не пересчитывали (сама ситуация явно неактуальна),
# просто мусор — чистим лениво при каждой загрузке, как в daily_plan.py.
PRUNE_AFTER_DAYS = 90


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_raw() -> dict:
    return get_json(_KEY, default={})


def _save(data: dict):
    set_json(_KEY, data)


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
