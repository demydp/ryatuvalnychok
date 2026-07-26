"""
Рубрики (тематические серии контента) и назначения рилс -> рубрика. Набор рубрик можно
получить автоматически через Claude (см. app/category_classifier.py) или вести вручную —
добавить/переименовать/объединить/удалить, перекинуть рилс в другую рубрику.
"""
import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.i18n import t
from app.project_store import project_data_dir

_EMPTY = {"categories": [], "assignments": {}, "last_auto_detect_at": None, "last_auto_detect_model": None}


def _categories_path() -> str:
    return os.path.join(project_data_dir(), "categories.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_categories() -> dict:
    if not os.path.exists(_categories_path()):
        return json.loads(json.dumps(_EMPTY))
    with open(_categories_path(), "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = json.loads(json.dumps(_EMPTY))
    merged.update(data)
    return merged


def save_categories(data: dict):
    os.makedirs(os.path.dirname(_categories_path()), exist_ok=True)
    with open(_categories_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_category(name: str, source: str = "manual") -> dict:
    data = load_categories()
    category = {
        "id": uuid.uuid4().hex[:10],
        "name": name.strip(),
        "source": source,
        "created_at": now_iso(),
    }
    data["categories"].append(category)
    save_categories(data)
    return category


def rename_category(category_id: str, name: str):
    data = load_categories()
    cat = next((c for c in data["categories"] if c["id"] == category_id), None)
    if not cat:
        return None
    cat["name"] = name.strip()
    save_categories(data)
    return cat


def delete_category(category_id: str) -> bool:
    data = load_categories()
    remaining = [c for c in data["categories"] if c["id"] != category_id]
    if len(remaining) == len(data["categories"]):
        return False
    data["categories"] = remaining
    data["assignments"] = {mid: cid for mid, cid in data["assignments"].items() if cid != category_id}
    save_categories(data)
    return True


def merge_categories(source_ids: list, name: str) -> dict:
    """Объединяет несколько рубрик в одну: первая из source_ids становится целевой (переименовывается
    в name), остальные удаляются, их рилсы переезжают на целевую рубрику."""
    data = load_categories()
    ids_set = set(source_ids)
    target_id = source_ids[0]
    target = next((c for c in data["categories"] if c["id"] == target_id), None)
    if not target:
        raise ValueError(t("categories.msg.target_not_found"))

    target["name"] = name.strip()
    target["source"] = "manual"
    data["categories"] = [c for c in data["categories"] if c["id"] == target_id or c["id"] not in ids_set]
    data["assignments"] = {
        mid: (target_id if cid in ids_set else cid) for mid, cid in data["assignments"].items()
    }
    save_categories(data)
    return target


def assign_media(media_id: str, category_id: str | None):
    data = load_categories()
    if category_id:
        if not any(c["id"] == category_id for c in data["categories"]):
            raise ValueError(t("categories.msg.not_found"))
        data["assignments"][media_id] = category_id
    else:
        data["assignments"].pop(media_id, None)
    save_categories(data)
    return data["assignments"].get(media_id)


def replace_auto_detected(categories: list, assignments_by_name: dict, model: str) -> dict:
    """categories: [{"name": ...}], assignments_by_name: {media_id: category_name}.
    ПОЛНОСТЬЮ заменяет текущий набор рубрик и назначений — пользователь предупреждён в UI,
    что повторный авто-детект перезапишет ручные правки."""
    data = json.loads(json.dumps(_EMPTY))
    name_to_id = {}
    for c in categories:
        cat = {
            "id": uuid.uuid4().hex[:10],
            "name": c["name"].strip(),
            "source": "auto",
            "created_at": now_iso(),
        }
        data["categories"].append(cat)
        name_to_id[c["name"]] = cat["id"]

    data["assignments"] = {
        media_id: name_to_id[name] for media_id, name in assignments_by_name.items() if name in name_to_id
    }
    data["last_auto_detect_at"] = now_iso()
    data["last_auto_detect_model"] = model
    save_categories(data)
    return data


def compute_category_stats(posts: list, transcripts: dict) -> list:
    """Эффективность по рубрикам — только по органическим Reels с готовыми инсайтами,
    та же логика исключений, что и в app/analysis.py (реклама искажает ER)."""
    data = load_categories()
    assignments = data["assignments"]
    posts_by_id = {p["id"]: p for p in posts}

    buckets = defaultdict(list)
    for media_id, category_id in assignments.items():
        post = posts_by_id.get(media_id)
        if post:
            buckets[category_id].append(post)

    stats = []
    for cat in data["categories"]:
        cat_posts = buckets.get(cat["id"], [])
        organic = [p for p in cat_posts if not p.get("is_ad") and p.get("insights_status") == "ok"]

        er_values = [p["engagement_rate"] for p in organic if p.get("engagement_rate") is not None]
        saves_values = [p["saves_rate"] for p in organic if p.get("saves_rate") is not None]

        hook_values = []
        for p in organic:
            t = transcripts.get(p["id"])
            duration = t.get("duration_sec") if t else None
            avg_watch = p.get("avg_watch_time")
            if t and duration and avg_watch is not None and duration > 0:
                hook_values.append((avg_watch / 1000) / duration * 100)

        stats.append(
            {
                "id": cat["id"],
                "name": cat["name"],
                "source": cat.get("source"),
                "reel_count": len(cat_posts),
                "organic_count": len(organic),
                "avg_er": round(mean(er_values), 2) if er_values else None,
                "avg_saves_rate": round(mean(saves_values), 2) if saves_values else None,
                "avg_hook_indicator": round(mean(hook_values), 1) if hook_values else None,
            }
        )

    stats.sort(key=lambda s: (s["avg_er"] is None, -(s["avg_er"] or 0)))
    return stats
