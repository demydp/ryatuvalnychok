"""
Дженерик KV-сховище per-project поверх models.ProjectData (Этап 2 веб-версії) — заміняє файлові
data/projects/<id>/*.json усіх модулів, що досі писали напряму на диск (project_data_dir(),
app/project_store.py). Причина: на Railway диск ефемерний, будь-який рестарт/редеплой стирав би
рубрики/скрипти/звіти/кеші — усе, що раніше лежало в цих файлах.

Один рядок ProjectData = один "файл": key лишився тим самим ім'ям, що раніше було ім'ям файлу
("categories.json", "media_cache.json" тощо) — тільки тепер це просто рядок-ключ, не шлях на
диску. value — серіалізований текст (JSON або base64 для бінарних даних типу кешованого PDF).

Ізоляція та сама, що для Project/UserSettings: project_id або явний, або резолвиться в АКТИВНИЙ
проєкт ПОТОЧНОЇ сесії через project_store.get_active_project_id() — той самий інваріант, що раніше
мала project_data_dir() без явного project_id. Кожен рядок прив'язаний до project_id, а той —
до user_id (FK у Project, app/models.py) — тому одна сесія фізично не може прочитати/переписати
рядок чужого проєкту, навіть знаючи ключ.
"""
import base64
import json

from app.db import db
from app.models import ProjectData


def _resolve_project_id(project_id: str | None) -> str:
    if project_id:
        return project_id
    from app.project_store import get_active_project_id

    resolved = get_active_project_id()
    if not resolved:
        raise ValueError("no active project for this session")
    return resolved


def get_text(key: str, project_id: str | None = None) -> str | None:
    project_id = _resolve_project_id(project_id)
    row = ProjectData.query.filter_by(project_id=project_id, key=key).first()
    return row.value if row else None


def set_text(key: str, text: str, project_id: str | None = None) -> None:
    project_id = _resolve_project_id(project_id)
    row = ProjectData.query.filter_by(project_id=project_id, key=key).first()
    if row is None:
        db.session.add(ProjectData(project_id=project_id, key=key, value=text))
    else:
        row.value = text
    db.session.commit()


def delete_key(key: str, project_id: str | None = None) -> bool:
    project_id = _resolve_project_id(project_id)
    row = ProjectData.query.filter_by(project_id=project_id, key=key).first()
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def get_json(key: str, default=None, project_id: str | None = None):
    text = get_text(key, project_id)
    if text is None:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def set_json(key: str, value, project_id: str | None = None) -> None:
    set_text(key, json.dumps(value, ensure_ascii=False), project_id)


def get_bytes(key: str, project_id: str | None = None) -> bytes | None:
    text = get_text(key, project_id)
    if text is None:
        return None
    return base64.b64decode(text)


def set_bytes(key: str, data: bytes, project_id: str | None = None) -> None:
    set_text(key, base64.b64encode(data).decode("ascii"), project_id)


def list_json_by_prefix(prefix: str, project_id: str | None = None) -> list:
    """Розпарсені value всіх рядків, чий key починається з prefix — заміна os.listdir(dir)
    для сценаріїв "багато елементів на проєкт під спільним префіксом" (звіти: report:<id>,
    report_pdf:<id> — префікс "report:" НЕ зачіпає "report_pdf:*", бо після спільної частини
    відразу різні символи, ":" проти "_")."""
    project_id = _resolve_project_id(project_id)
    rows = ProjectData.query.filter(
        ProjectData.project_id == project_id, ProjectData.key.like(f"{prefix}%")
    ).all()
    items = []
    for row in rows:
        try:
            items.append(json.loads(row.value))
        except (json.JSONDecodeError, TypeError):
            continue
    return items
