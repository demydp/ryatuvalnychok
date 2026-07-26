"""
Эмпирическая проверка продвинутых метрик хука/удержания Instagram Graph API — вместо того
чтобы верить документации (Meta сама помечает часть этих метрик "estimated"/"in development"
и они могут отличаться по аккаунтам), реально запрашиваем каждую метрику по отдельности
у /{media-id}/insights и смотрим, что ответит API.

Каждая метрика запрашивается ИЗОЛИРОВАННО (не пачкой), чтобы получить точную причину отказа
именно по ней, а не общую ошибку "что-то из пачки не то". Гоняется по кнопке на вкладке
«Хук-анализ» (несколько десятков запросов к API — не делаем это автоматически при каждой загрузке).

Результат этой проверки (июль 2026, живой аккаунт): reels_skip_rate, ig_reels_avg_watch_time,
ig_reels_video_view_total_time, views, reach, saved, shares, likes, comments, total_interactions,
reposts — реально возвращают данные через органический Media Insights API. ThruPlay, кривая
удержания 25/50/75/100% (video_pXX_watched_actions) и любые "hook_rate" — endpoint их в принципе
не знает (см. перечисление в сообщении об ошибке #100) — это метрики видеорекламы Marketing API,
для органических Reels в Instagram их не существует физически, не только "не хватает доступа".
crossposted_views/facebook_views — валидные имена метрик (есть в перечислении ошибки), но падают
с "Fatal" на постах без кросспостинга на Facebook.
"""
import requests

from app.i18n import t

GRAPH_BASE = "https://graph.facebook.com/v21.0"

# error_subcode, наблюдаемый на постах без кросспостинга на Facebook (crossposted_views/facebook_views)
SUBCODE_NOT_CROSSPOSTED = 2207086

# группа (для UI) -> [(имя метрики в API, ключ i18n человекочитаемого названия)]
CANDIDATE_GROUPS_RAW = [
    (
        "diag.group.skip_rate",
        [("reels_skip_rate", "diag.metric.skip_rate")],
    ),
    (
        "diag.group.watch_time",
        [
            ("ig_reels_avg_watch_time", "diag.metric.avg_watch_time"),
            ("ig_reels_video_view_total_time", "diag.metric.view_total_time"),
        ],
    ),
    (
        "diag.group.views",
        [("views", "diag.metric.views")],
    ),
    (
        "diag.group.retention_curve",
        [
            ("video_p25_watched_actions", "diag.metric.p25"),
            ("video_p50_watched_actions", "diag.metric.p50"),
            ("video_p75_watched_actions", "diag.metric.p75"),
            ("video_p100_watched_actions", "diag.metric.p100"),
        ],
    ),
    (
        "diag.group.thruplay",
        [("video_thruplay_watched_actions", "diag.metric.thruplay")],
    ),
    (
        "diag.group.hook_rate",
        [
            ("hook_rate", "diag.metric.hook_rate"),
            ("ig_reels_hook_rate", "diag.metric.ig_reels_hook_rate"),
        ],
    ),
    (
        "diag.group.reposts_crosspost",
        [
            ("reposts", "diag.metric.reposts"),
            ("crossposted_views", "diag.metric.crossposted_views"),
            ("facebook_views", "diag.metric.facebook_views"),
        ],
    ),
]


def _probe_one(media_id: str, metric: str, token: str) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}/{media_id}/insights",
        params={"metric": metric, "access_token": token},
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        err = data["error"]
        return {"ok": False, "code": err.get("code"), "subcode": err.get("error_subcode"), "message": err.get("message")}
    entries = data.get("data", [])
    if not entries:
        return {"ok": False, "code": None, "subcode": None, "message": t("diag.msg.empty_response")}
    entry = entries[0]
    value = entry["total_value"].get("value") if "total_value" in entry else (entry.get("values") or [{}])[0].get("value")
    return {"ok": True, "value": value}


def _classify(results: list) -> dict:
    oks = [r for r in results if r["ok"]]
    if oks:
        return {"status": "ok", "sample_values": [r["value"] for r in oks]}

    first_error = results[0]
    code = first_error.get("code")
    subcode = first_error.get("subcode")
    message = first_error.get("message") or ""

    if code == 100 and "must be one of the following values" in message:
        reason = t("diag.reason.not_supported_for_organic")
    elif code == 100 and "does not support" in message:
        reason = t("diag.reason.rejected_for_media_type")
    elif subcode == SUBCODE_NOT_CROSSPOSTED:
        reason = t("diag.reason.not_crossposted")
    else:
        reason = message or t("diag.reason.unknown")

    return {"status": "no_data", "reason": reason, "raw_message": message}


def run_diagnostic(token: str, media_ids: list) -> list:
    """Возвращает список групп {group, metrics: [{metric, label, status, ...}]}."""
    output = []
    for group_key, metrics in CANDIDATE_GROUPS_RAW:
        group_metrics = []
        for metric_name, label_key in metrics:
            results = [_probe_one(mid, metric_name, token) for mid in media_ids]
            classified = _classify(results)
            group_metrics.append({"metric": metric_name, "label": t(label_key), **classified})
        output.append({"group": t(group_key), "metrics": group_metrics})
    return output
