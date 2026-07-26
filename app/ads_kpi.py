"""
Мои KPI по цели кампании (этап 4c) — цели, которые пользователь задаёт сам, и честный
вердикт факт vs цель ("успех / норма / провал"). Хранится отдельным JSON-файлом в data/,
как categories.json/style_profile.json — это пользовательские данные, а не секреты конфига.
"""
import json
import os
import threading

from app.i18n import t
from app.project_store import project_data_dir

_lock = threading.Lock()


def _kpi_path(project_id: str = None) -> str:
    return os.path.join(project_data_dir(project_id), "ads_kpi_targets.json")

TARGET_FIELDS = ("target_cpl", "target_cpm", "target_ctr", "target_roas", "target_cost_per_result")

# Цели ODAX, для которых имеет смысл задавать KPI (совпадает с OBJECTIVE_LABELS в ads_api.py
# для актуальных Outcome-целей — легаси-цели тоже можно завести вручную через тот же API).
# Ключи — коды ODAX (стабильные), подписи берутся из lang/*.json по ключу ads.objective.<код>.
_KPI_OBJECTIVE_CODES = (
    "OUTCOME_AWARENESS",
    "OUTCOME_TRAFFIC",
    "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS",
    "OUTCOME_SALES",
    "OUTCOME_APP_PROMOTION",
)


def get_kpi_objectives() -> dict:
    return {code: t(f"ads.objective.{code}") for code in _KPI_OBJECTIVE_CODES}


# Честные ориентиры "что хорошо" — намеренно грубые, с оговоркой про рынок/нишу (TZ п.6).
def get_benchmark_hints() -> dict:
    return {
        "CPM": t("ads.benchmark.cpm"),
        "CTR": t("ads.benchmark.ctr"),
        "CPL": t("ads.benchmark.cpl"),
        "ROAS": t("ads.benchmark.roas"),
        "Frequency": t("ads.benchmark.frequency"),
    }


def load_kpi_targets(project_id: str = None) -> dict:
    path = _kpi_path(project_id)
    if not os.path.exists(path):
        return {}
    with _lock:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def save_kpi_targets(objective: str, targets: dict) -> dict:
    current = load_kpi_targets()
    clean = {}
    for field in TARGET_FIELDS:
        value = targets.get(field)
        if value in (None, ""):
            clean[field] = None
            continue
        try:
            clean[field] = float(value)
        except (TypeError, ValueError):
            clean[field] = None
    current[objective] = clean
    os.makedirs(os.path.dirname(_kpi_path()), exist_ok=True)
    with _lock:
        with open(_kpi_path(), "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    return current[objective]


def delete_kpi_target(objective: str) -> bool:
    """Убирает цель по objective. Кампании с этой целью никуда не деваются — цель задаётся
    по коду цели (ODAX), а не по конкретной кампании, так что "удаление" — это просто отвязка
    числовых ориентиров, а не удаление чего-то, что относится к самой кампании."""
    current = load_kpi_targets()
    if objective not in current:
        return False
    del current[objective]
    with _lock:
        with open(_kpi_path(), "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    return True


def _verdict_for(fact, target, lower_is_better: bool, tolerance: float = 0.10):
    if fact is None or target is None:
        return None
    if lower_is_better:
        if fact <= target:
            return "success"
        if fact <= target * (1 + tolerance):
            return "ok"
        return "fail"
    if fact >= target:
        return "success"
    if fact >= target * (1 - tolerance):
        return "ok"
    return "fail"


def compute_kpi_verdicts(metrics: dict, result: dict, targets: dict) -> list:
    """Факт vs цель по каждой заданной метрике — успех/норма/провал (10% зона допуска на "норму").
    Метрики, для которых цель не задана, не показываем — честно, без вымышленных "0 целей"."""
    if not targets:
        return []

    result = result or {}
    checks = (
        ("CPM", metrics.get("cpm"), targets.get("target_cpm"), True),
        ("CTR", metrics.get("ctr"), targets.get("target_ctr"), False),
        ("CPL", result.get("cost_per_result"), targets.get("target_cpl"), True),
        (t("ads.kpi.cost_per_result"), result.get("cost_per_result"), targets.get("target_cost_per_result"), True),
        ("ROAS", result.get("roas"), targets.get("target_roas"), False),
    )

    rows = []
    for label, fact, target, lower_is_better in checks:
        if target is None:
            continue
        rows.append({
            "metric": label,
            "fact": fact,
            "target": target,
            "verdict": _verdict_for(fact, target, lower_is_better),
        })
    return rows
