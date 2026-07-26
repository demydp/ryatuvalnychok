import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.i18n import t
from app.instagram_api import InstagramAPIError, fetch_all_media, fetch_media_insights
from app.project_store import get_effective_config, project_data_dir
from app.script_verdict import recompute_all_verdicts
from app.transcription import load_transcripts

metrics_bp = Blueprint("metrics", __name__)
logger = logging.getLogger("reels_dashboard")


def media_cache_path() -> str:
    """Единственное место, откуда читают/пишут media_cache.json — остальные модули
    (companion.py, ideas.py, signals.py, home_summary.py и т.д.) импортируют load_cache
    отсюда же, а не держат свою копию пути."""
    return os.path.join(project_data_dir(), "media_cache.json")


def load_cache() -> dict:
    cache_path = media_cache_path()
    if not os.path.exists(cache_path):
        return {"posts": [], "total_media": 0, "synced_at": None}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("media_cache.json повреждён (%s) — начинаю с пустого кэша", e)
        return {"posts": [], "total_media": 0, "synced_at": None}


def save_cache(data: dict):
    # Атомарная запись (temp-файл + os.replace) — при аварийном завершении процесса
    # ровно во время сохранения кэш не должен превратиться в битый JSON, который потом
    # роняет весь дашборд при следующем чтении.
    cache_path = media_cache_path()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(cache_path), prefix=".media_cache_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

# metric name у Graph API -> имя поля в записи поста
INSIGHT_FIELD_MAP = {
    "reach": "reach",
    "saved": "saved",
    "shares": "shares",
    "total_interactions": "total_interactions",
    "views": "views",
    "ig_reels_avg_watch_time": "avg_watch_time",
    "ig_reels_video_view_total_time": "view_total_time",
    "reels_skip_rate": "skip_rate",
}

# Тексты причин рендерятся t() внутри _build_record() (в момент /sync, внутри запроса
# с X-Lang), а не как модульные константы — на уровне модуля current_lang() ещё не имеет
# контекста запроса и упал бы с RuntimeError.

# Пункт F ТЗ: Instagram отдаёт органическую статистику не мгновенно после публикации — свежий
# пост без данных это не ошибка синка, а нормальная задержка. Без этого различия пользователь
# видит "нет данных"/ошибку API рядом с постом, который просто вышел час назад, и решает,
# что синк сломан. 48 часов — заведомо больше типичной задержки Meta (обычно данные готовы
# за несколько часов), взято с запасом, чтобы не спутать с реальной недоступностью инсайтов.
FRESH_THRESHOLD_HOURS = 48


def _is_fresh(timestamp_str: str) -> bool:
    if not timestamp_str:
        return False
    try:
        published = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    return 0 <= age_hours < FRESH_THRESHOLD_HOURS


def _build_record(media: dict, insight: dict, is_ad: bool = False) -> dict:
    record = {
        "id": media.get("id"),
        "caption": media.get("caption", ""),
        "media_type": media.get("media_type"),
        "media_product_type": media.get("media_product_type"),
        "timestamp": media.get("timestamp"),
        "permalink": media.get("permalink"),
        "thumbnail_url": media.get("thumbnail_url") or media.get("media_url"),
        # like_count/comments_count — поля ноды media, НЕ insights, доступны всегда без ограничений
        "like_count": media.get("like_count"),
        "comments_count": media.get("comments_count"),
        "insights_status": insight["status"],
        "insights_reason": insight.get("reason"),
        # Ручной флаг пользователя: пост продвигался рекламой -> ER искажён (лайки/охват смешаны
        # с платным трафиком), исключать из органического анализа "Что заходит".
        "is_ad": bool(is_ad),
    }

    metrics = insight.get("metrics", {})
    unsupported = insight.get("unsupported", {})
    for api_name, field_name in INSIGHT_FIELD_MAP.items():
        record[field_name] = metrics.get(api_name)

    record["metric_notes"] = {INSIGHT_FIELD_MAP.get(k, k): v for k, v in unsupported.items()}

    # Пункт F: свежий пост (< FRESH_THRESHOLD_HOURS) без реальных данных — это задержка Meta,
    # а не сбой/ошибка синка. Переопределяем статус ПОСЛЕ основного разбора инсайтов, чтобы
    # не потерять реальные метрики, если они всё же уже подъехали, несмотря на свежесть поста.
    if _is_fresh(media.get("timestamp")):
        no_core_data = record.get("reach") is None and record.get("total_interactions") is None
        if record["insights_status"] != "ok" or no_core_data:
            record["insights_status"] = "pending_fresh"
            record["insights_reason"] = t("metrics.reason.pending_fresh")

    # Skip Rate (reels_skip_rate) сама метрика реальная, но может быть не раскатана на все
    # аккаунты/посты — если API её отклонил, причина уже лежит в metric_notes.skip_rate
    if record.get("skip_rate") is None:
        record["skip_rate_reason"] = record["metric_notes"].get(
            "skip_rate", t("metrics.reason.skip_rate_unavailable")
        )
    else:
        record["skip_rate_reason"] = None

    # Индикатор хука = средний досмотр / длина видео. Graph API не отдаёт длину видео,
    # поэтому честно показываем "нет данных", а не половинчатую метрику.
    record["hook_indicator"] = None
    record["hook_indicator_reason"] = t("metrics.reason.hook_indicator_unavailable")

    total_interactions = record.get("total_interactions")
    reach = record.get("reach")
    if isinstance(total_interactions, (int, float)) and isinstance(reach, (int, float)) and reach > 0:
        record["engagement_rate"] = round(total_interactions / reach * 100, 2)
    else:
        record["engagement_rate"] = None

    for rate_field, numerator_field in (("saves_rate", "saved"), ("shares_rate", "shares")):
        numerator = record.get(numerator_field)
        if isinstance(numerator, (int, float)) and isinstance(reach, (int, float)) and reach > 0:
            record[rate_field] = round(numerator / reach * 100, 2)
        else:
            record[rate_field] = None

    # Сырые ответы API — для сверки цифр с приложением Instagram (не для показа в обычном UI)
    record["_raw_media"] = media
    record["_raw_insights"] = insight.get("raw", [])

    return record


def run_metrics_sync() -> dict:
    """Тело синка метрик Instagram активного проекта — общая логика для ручной кнопки
    «Синхронизировать» (см. sync_metrics ниже) и фонового авто-обновления (см. app/scheduler.py),
    чтобы оба пути гарантированно вели себя одинаково и не расходились по багам/поведению.
    Возвращает {"error": ...} вместо исключения — вызывающий код сам решает, что за ошибка
    (пользовательский HTTP 400 в ручном режиме или просто строка в лог у фонового job'а)."""
    cfg = get_effective_config()
    token = cfg["ig_access_token"]
    ig_user_id = cfg["ig_user_id"]
    max_media = cfg.get("max_media") or 100

    if not token or not ig_user_id:
        return {"error": t("metrics.msg.setup_first")}

    try:
        media_items = fetch_all_media(token, ig_user_id, max_media)
    except InstagramAPIError as e:
        return {"error": t("metrics.msg.media_load_error", error=e)}

    # Флаг "была реклама" пользователь проставляет руками — при пересинке не должен слетать
    previous_ad_flags = {p["id"]: p.get("is_ad", False) for p in load_cache().get("posts", [])}

    records = []
    for media in media_items:
        try:
            insight = fetch_media_insights(
                token, media["id"], media.get("media_type"), media.get("media_product_type")
            )
        except Exception as e:
            # Один сбойный пост не должен обрушивать весь синк и терять уже собранные данные
            # по остальным. Честно помечаем причину вместо падения всего запроса.
            logger.error("Не удалось получить инсайты для медиа %s: %s", media.get("id"), e)
            insight = {"status": "unavailable_error", "reason": t("metrics.reason.fetch_error", error=e)}
        is_ad = previous_ad_flags.get(media["id"], False)
        try:
            records.append(_build_record(media, insight, is_ad))
        except Exception as e:
            logger.error("Не удалось собрать запись для медиа %s: %s", media.get("id"), e)

    ok_count = sum(1 for r in records if r["insights_status"] == "ok")
    pending_fresh_count = sum(1 for r in records if r["insights_status"] == "pending_fresh")
    unavailable_count = len(records) - ok_count - pending_fresh_count

    result = {
        "synced_at": _now_iso(),
        "ig_username": cfg.get("ig_username", ""),
        "total_media": len(records),
        "insights_ok": ok_count,
        "insights_pending_fresh": pending_fresh_count,
        "insights_unavailable": unavailable_count,
        "posts": records,
    }

    save_cache(result)

    # Метрики рилса дозревают несколько дней — пересчитываем вердикты привязанных
    # скриптов на каждом синке, чтобы ранние цифры не зафиксировали ложный результат.
    # Кэш уже сохранён выше — сбой здесь не должен превращать успешный синк в ошибку 500.
    try:
        recompute_all_verdicts(records, load_transcripts())
    except Exception as e:
        logger.error("Не удалось пересчитать вердикты скриптов после синка: %s", e)

    return result


@metrics_bp.route("/sync", methods=["POST"])
def sync_metrics():
    result = run_metrics_sync()
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@metrics_bp.route("", methods=["GET"])
def get_metrics():
    return jsonify(load_cache())


@metrics_bp.route("/<media_id>/ad-flag", methods=["POST"])
def set_ad_flag(media_id):
    body = request.get_json(force=True) or {}
    is_ad = bool(body.get("is_ad"))

    cache = load_cache()
    post = next((p for p in cache.get("posts", []) if p["id"] == media_id), None)
    if not post:
        return jsonify({"error": t("metrics.msg.post_not_found")}), 404

    post["is_ad"] = is_ad
    save_cache(cache)
    return jsonify({"id": media_id, "is_ad": is_ad})


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
