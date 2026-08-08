"""
Клиент Instagram Graph API (graph.facebook.com/v21.0).

Честные правила:
- like_count / comments_count берём напрямую с ноды media (доступны всегда, без ограничений).
- reach / saved / shares / total_interactions / views берём через edge insights —
  эти метрики могут быть недоступны для аккаунтов <1000 подписчиков и постов,
  опубликованных до перехода в бизнес-аккаунт (error_subcode 2108006). В этих
  случаях НЕ показываем 0 и НЕ роняем синк — помечаем метрику как недоступную.
"""
import random
import time

import requests

from app.i18n import t

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Коды/подстроки, которыми Meta помечает "слишком много запросов" (User/Application request
# limit reached, code 4/17/32/613) — при них мягко ждём и повторяем, а не рушим весь синк.
# Тот же подход, что в app/ads_api.py (_is_rate_limit_error) — важно и здесь, потому что
# фоновый авто-синк (см. app/scheduler.py) дёргает fetch_media_insights по каждому посту
# подряд без паузы пользователя между кликами, и именно так легче всего упереться в лимит.
_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}
_MAX_RATE_LIMIT_RETRIES = 4
_RATE_LIMIT_BASE_DELAY_SEC = 2.0


def _is_rate_limit_error(error: dict) -> bool:
    if not error:
        return False
    if error.get("code") in _RATE_LIMIT_ERROR_CODES:
        return True
    message = (error.get("message") or "").lower()
    return "request limit reached" in message or "too many calls" in message


def _sleep_before_retry(attempt: int) -> None:
    delay = _RATE_LIMIT_BASE_DELAY_SEC * (2 ** (attempt - 1)) + random.uniform(0, 1)
    time.sleep(delay)

# error_subcode Meta для постов, опубликованных до перехода аккаунта в бизнес-режим
SUBCODE_PRE_BUSINESS = 2108006

# REASON_PRE_BUSINESS попадает в media_cache.json на синке (см. app/routes/metrics.py) —
# записывается на языке, активном в момент синка (сам /sync — live-запрос с X-Lang,
# поэтому t() тут корректно берёт текущий язык интерфейса пользователя).
REASON_PRE_BUSINESS_KEY = "instagram.reason.pre_business"
REASON_NO_DATA = "нет данных (аккаунт < 1000 подписчиков или ограничение API)"

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,timestamp,permalink,"
    "thumbnail_url,media_url,like_count,comments_count"
)


class InstagramAPIError(Exception):
    """Понятная ошибка для показа пользователю (проблема токена, прав и т.п.)."""


def _get(url, params=None):
    data, error = _get_raw(url, params)
    if error:
        raise InstagramAPIError(
            error.get("message", t("instagram.error.unknown_graph_api_error")),
        ) from None
    return data


def _get_raw(url, params=None):
    """Как _get, но возвращает (data, error_dict_or_None) вместо исключения. При ошибке
    лимита запросов Meta мягко ждёт и повторяет (см. _is_rate_limit_error), прежде чем
    честно отдать ошибку вызывающему коду."""
    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
        except requests.RequestException as e:
            return {}, {"message": t("instagram.error.api_unavailable", error=e)}
        except ValueError:
            return {}, {"message": t("instagram.error.bad_response")}

        error = data.get("error")
        if error and _is_rate_limit_error(error):
            attempt += 1
            if attempt <= _MAX_RATE_LIMIT_RETRIES:
                _sleep_before_retry(attempt)
                continue
        return data, error


def resolve_ig_user(access_token: str) -> dict:
    """
    Автоопределение Instagram business-аккаунта по токену.
    Возвращает {"id":..., "username":..., "name":...}
    либо {"accounts": [...]} если кандидатов несколько.

    Токены Instagram бывают двух видов, и /me у них ведёт себя по-разному:
    - Instagram Login (instagram_business_basic и т.п.) — /me и /me/accounts пустые,
      сам IG User ID лежит в granular_scopes токена.
    - Facebook Login for Business — IG-аккаунт привязан к Facebook-странице,
      ID страницы лежит в granular_scopes (pages_show_list), а IG ID достаём через саму страницу.
    Поэтому сначала интроспектируем токен через /debug_token, и только если это
    не помогло — пробуем классический путь через /me и /me/accounts.
    """
    granular_scopes = _debug_token_granular_scopes(access_token)

    # Вариант 1: IG User ID лежит прямо в granular_scopes (Instagram Login токены)
    ig_candidate_ids = _collect_target_ids(
        granular_scopes,
        lambda scope: scope.startswith("instagram_business") or scope in ("instagram_basic", "instagram_manage_insights"),
    )
    found = _verify_ig_candidates(access_token, ig_candidate_ids)
    if found:
        return found[0] if len(found) == 1 else {"accounts": found}

    # Вариант 2: в granular_scopes лежат ID Facebook-страниц — берём IG-аккаунт со страницы напрямую
    page_candidate_ids = _collect_target_ids(
        granular_scopes,
        lambda scope: scope.startswith("pages_"),
    )
    found = _ig_accounts_from_pages(access_token, page_candidate_ids)
    if found:
        return found[0] if len(found) == 1 else {"accounts": found}

    # Вариант 3 (фоллбэк): классический путь для Page Access Token и User Access Token
    found = _legacy_resolve(access_token)
    if found:
        return found[0] if len(found) == 1 else {"accounts": found}

    raise InstagramAPIError(t("instagram.error.cannot_resolve_account"))


def _debug_token_granular_scopes(access_token: str) -> list:
    """Интроспекция токена: какие granular scopes выданы и на какие ID (IG-аккаунт / страница)."""
    try:
        data = _get(f"{GRAPH_BASE}/debug_token", {"input_token": access_token, "access_token": access_token})
    except InstagramAPIError:
        return []
    return data.get("data", {}).get("granular_scopes", []) or []


def _collect_target_ids(granular_scopes: list, scope_predicate) -> list:
    ids = []
    for entry in granular_scopes:
        if not scope_predicate(entry.get("scope", "")):
            continue
        for target_id in entry.get("target_ids", []) or []:
            if target_id not in ids:
                ids.append(target_id)
    return ids


def _verify_ig_candidates(access_token: str, ig_ids: list) -> list:
    found = []
    for ig_id in ig_ids:
        try:
            info = _get(f"{GRAPH_BASE}/{ig_id}", {"fields": "id,username,name", "access_token": access_token})
        except InstagramAPIError:
            continue
        found.append({"id": info["id"], "username": info.get("username", ""), "name": info.get("name", "")})
    return found


def _ig_accounts_from_pages(access_token: str, page_ids: list) -> list:
    found = []
    for page_id in page_ids:
        try:
            page = _get(
                f"{GRAPH_BASE}/{page_id}",
                {"fields": "id,name,instagram_business_account{id,username,name}", "access_token": access_token},
            )
        except InstagramAPIError:
            continue
        iba = page.get("instagram_business_account")
        if iba:
            found.append({"id": iba["id"], "username": iba.get("username", ""), "name": iba.get("name", "")})
    return found


def _legacy_resolve(access_token: str) -> list:
    try:
        data = _get(
            f"{GRAPH_BASE}/me",
            {"fields": "id,name,instagram_business_account{id,username,name}", "access_token": access_token},
        )
        iba = data.get("instagram_business_account")
        if iba:
            return [{"id": iba["id"], "username": iba.get("username", ""), "name": iba.get("name", "")}]
    except InstagramAPIError:
        pass

    try:
        accounts_data = _get(
            f"{GRAPH_BASE}/me/accounts",
            {"fields": "id,name,instagram_business_account{id,username,name}", "access_token": access_token},
        )
    except InstagramAPIError:
        return []

    found = []
    for page in accounts_data.get("data", []):
        iba = page.get("instagram_business_account")
        if iba:
            found.append({"id": iba["id"], "username": iba.get("username", ""), "name": iba.get("name", "")})
    return found


def get_account_info(access_token: str, ig_user_id: str) -> dict:
    """Имя аккаунта, юзернейм, число подписчиков (для проверки подключения)."""
    return _get(
        f"{GRAPH_BASE}/{ig_user_id}",
        {
            "fields": "id,username,name,followers_count,media_count,profile_picture_url",
            "access_token": access_token,
        },
    )


def get_media_url(access_token: str, media_id: str) -> str:
    """Свежая ссылка на файл видео — media_url отдаёт временную подписанную CDN-ссылку,
    поэтому запрашивать нужно непосредственно перед скачиванием, а не брать из старого кэша."""
    data = _get(f"{GRAPH_BASE}/{media_id}", {"fields": "media_url", "access_token": access_token})
    url = data.get("media_url")
    if not url:
        raise InstagramAPIError(t("instagram.error.no_media_url"))
    return url


def fetch_all_media(access_token: str, ig_user_id: str, max_media: int) -> list:
    """Тянет все медиа (рилсы/посты) с пагинацией через paging.next, до max_media штук."""
    items = []
    limit = min(max_media, 50) if max_media else 50
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    params = {"fields": MEDIA_FIELDS, "limit": limit, "access_token": access_token}

    while url:
        data = _get(url, params)
        items.extend(data.get("data", []))
        if max_media and len(items) >= max_media:
            items = items[:max_media]
            break
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        url = next_url
        params = None  # next_url уже содержит все параметры, включая access_token

    return items


# Skip Rate (3с) — метрика из обновлённого Insights API (дек. 2025). Имя подтверждено
# официальной справкой Meta (developers.facebook.com/docs/instagram-platform/reference/
# instagram-media/insights/): "reels_skip_rate — процент просмотров, где зритель
# пропустил рилс в первые 3 секунды". Если Graph API её всё же отклонит (например,
# метрика ещё не раскатана на все аккаунты) — сработает штатный фоллбэк на "нет данных"
# с точной причиной от API, а не с угадыванием.
SKIP_RATE_METRIC_CANDIDATES: list = ["reels_skip_rate"]


def _metric_candidates(media_type: str, media_product_type: str) -> list:
    base = ["reach", "saved", "shares", "total_interactions"]
    if media_product_type == "REELS" or media_type == "VIDEO":
        base.append("views")
    if media_product_type == "REELS":
        base += ["ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
    base += SKIP_RATE_METRIC_CANDIDATES
    return base


def fetch_media_insights(access_token: str, media_id: str, media_type: str, media_product_type: str) -> dict:
    """
    Возвращает:
      {"status": "ok", "metrics": {...}, "unsupported": {...}, "raw": [...]}
      либо {"status": "unavailable_pre_business", "reason": "..."} — весь insights-запрос
      недоступен для поста целиком (пост до перехода в бизнес-аккаунт).

    Каждая метрика запрашивается с честным фоллбэком: если объединённый запрос падает,
    делим список метрик пополам и повторяем рекурсивно, пока не найдём, какие именно
    метрики поддерживаются для этого медиа, а какие — нет (и почему). Так одна
    неподдерживаемая метрика (например views для карусели) не роняет остальные.
    Никогда не бросает исключение наружу — используется в цикле синка.
    """
    candidates = _metric_candidates(media_type, media_product_type)
    if not candidates:
        return {"status": "ok", "metrics": {}, "unsupported": {}, "raw": []}

    metrics, unsupported, raw_responses, pre_business = _fetch_metrics_recursive(
        access_token, media_id, candidates
    )

    if pre_business:
        return {"status": "unavailable_pre_business", "reason": t(REASON_PRE_BUSINESS_KEY)}

    return {"status": "ok", "metrics": metrics, "unsupported": unsupported, "raw": raw_responses}


def _fetch_metrics_recursive(access_token: str, media_id: str, metric_names: list):
    """Возвращает (metrics_values, unsupported_reasons, raw_responses, hit_pre_business)."""
    url = f"{GRAPH_BASE}/{media_id}/insights"
    data, error = _get_raw(url, {"metric": ",".join(metric_names), "access_token": access_token})

    if not error:
        values = {}
        for entry in data.get("data", []):
            name = entry.get("name")
            if "total_value" in entry:
                value = entry["total_value"].get("value")
            else:
                vs = entry.get("values", [])
                value = vs[0].get("value") if vs else None
            values[name] = value
        return values, {}, [data], False

    subcode = error.get("error_subcode")
    message = error.get("message", t("instagram.error.metric_unavailable"))
    if subcode == SUBCODE_PRE_BUSINESS:
        return {}, {}, [{"error": error}], True

    if len(metric_names) == 1:
        return {}, {metric_names[0]: message}, [{"metric": metric_names[0], "error": error}], False

    mid = len(metric_names) // 2
    left_vals, left_unsupported, left_raw, left_pb = _fetch_metrics_recursive(
        access_token, media_id, metric_names[:mid]
    )
    if left_pb:
        return {}, {}, left_raw, True
    right_vals, right_unsupported, right_raw, right_pb = _fetch_metrics_recursive(
        access_token, media_id, metric_names[mid:]
    )
    if right_pb:
        return {}, {}, right_raw, True

    values = {**left_vals, **right_vals}
    unsupported = {**left_unsupported, **right_unsupported}
    return values, unsupported, left_raw + right_raw, False


# Сторіс (Stories) — перевірено емпірично на реальному акаунті (діагностика 08.08.2026):
# 1. /{ig-user-id}/stories віддає ЛИШЕ живі сторіс (до ~24 год з публікації), з полями нижче.
# 2. Легітимний список метрик /{media-id}/insights для media_product_type=STORY отриманий
#    ПРЯМО з відповіді Graph API на невалідну назву метрики (код 100 сам перелічує весь список
#    для цього медіа) — з нього для сторіс підходять саме ці; impressions/saved/likes/comments
#    Graph API для сторіс мовчки ігнорує (це метрики постів/рілсів, не сторіс).
# 3. Старих окремих метрик taps_forward/taps_back/exits у поточній версії API вже НЕМА —
#    Meta прибрала їх. Лишилась лише агрегована "navigation" без розбивки напряму: жодна
#    перевірена назва breakdown ("story_navigation_action_type", "action_type") не відкрила
#    реальний розподіл — breakdown або відхиляється помилкою "Incompatible breakdowns", або
#    мовчки ігнорується без ефекту. Чесно показуємо лише сумарний navigation.
STORY_FIELDS = "id,media_type,media_product_type,timestamp,permalink,media_url,thumbnail_url"

STORY_METRICS = [
    "reach", "replies", "navigation", "profile_activity", "profile_visits",
    "shares", "total_interactions", "follows",
]

# Graph API повертає це для сторіс із замало переглядів (перевірено емпірично) — окремий
# код помилки, не error_subcode як SUBCODE_PRE_BUSINESS вище, і стосується САМЕ сторіс.
CODE_NOT_ENOUGH_VIEWERS = 10
REASON_INSUFFICIENT_VIEWERS_KEY = "instagram.reason.insufficient_viewers"


def fetch_active_stories(access_token: str, ig_user_id: str) -> list:
    """Живі сторіс просто зараз. Пагінації свідомо нема — живих сторіс завжди мало (Instagram
    сам обмежує їх кількість і час життя ~24 год), на відміну від fetch_all_media."""
    data = _get(f"{GRAPH_BASE}/{ig_user_id}/stories", {"fields": STORY_FIELDS, "access_token": access_token})
    return data.get("data", [])


def fetch_story_insights(access_token: str, story_id: str) -> dict:
    """Як fetch_media_insights, але для сторіс: свій список метрик (STORY_METRICS) і своя чесна
    причина повної недоступності — "недостатньо переглядів" (CODE_NOT_ENOUGH_VIEWERS), а не
    "до переходу в бізнес-акаунт" (SUBCODE_PRE_BUSINESS), як у звичайних постів."""
    metrics, unsupported, raw, insufficient = _fetch_story_metrics_recursive(access_token, story_id, STORY_METRICS)
    if insufficient:
        return {"status": "unavailable_insufficient_viewers", "reason": t(REASON_INSUFFICIENT_VIEWERS_KEY)}
    return {"status": "ok", "metrics": metrics, "unsupported": unsupported, "raw": raw}


def _fetch_story_metrics_recursive(access_token: str, story_id: str, metric_names: list):
    """Той самий чесний рекурсивний фоллбек, що й _fetch_metrics_recursive для постів, але
    термінальна умова інша: CODE_NOT_ENOUGH_VIEWERS означає недоступність УСІХ метрик сторіс
    цілком (поріг переглядів на рівні медіа), а не однієї конкретної метрики."""
    url = f"{GRAPH_BASE}/{story_id}/insights"
    data, error = _get_raw(url, {"metric": ",".join(metric_names), "access_token": access_token})

    if not error:
        values = {}
        for entry in data.get("data", []):
            name = entry.get("name")
            if "total_value" in entry:
                value = entry["total_value"].get("value")
            else:
                vs = entry.get("values", [])
                value = vs[0].get("value") if vs else None
            values[name] = value
        return values, {}, [data], False

    if error.get("code") == CODE_NOT_ENOUGH_VIEWERS:
        return {}, {}, [{"error": error}], True

    message = error.get("message", t("instagram.error.metric_unavailable"))
    if len(metric_names) == 1:
        return {}, {metric_names[0]: message}, [{"metric": metric_names[0], "error": error}], False

    mid = len(metric_names) // 2
    left_vals, left_unsupported, left_raw, left_insufficient = _fetch_story_metrics_recursive(
        access_token, story_id, metric_names[:mid]
    )
    if left_insufficient:
        return {}, {}, left_raw, True
    right_vals, right_unsupported, right_raw, right_insufficient = _fetch_story_metrics_recursive(
        access_token, story_id, metric_names[mid:]
    )
    if right_insufficient:
        return {}, {}, right_raw, True

    values = {**left_vals, **right_vals}
    unsupported = {**left_unsupported, **right_unsupported}
    return values, unsupported, left_raw + right_raw, False


def fetch_reach_follow_type_breakdown(access_token: str, ig_user_id: str) -> dict:
    """Розбивка охоплення акаунта на підписників/не підписників (breakdown=follow_type) —
    ПРАЦЮЄ ЛИШЕ на рівні акаунта. Перевірено емпірично: на рівні звичайного поста і на рівні
    сторіс Graph API однаково відповідає помилкою "Incompatible breakdowns (follow_type) for
    metric (reach)" — Instagram ЧЕСНО цього не дає для окремого поста/сторіс, це не наш недогляд.
    period=day для reach обов'язковий (без period Graph API взагалі відхиляє запит з breakdown)."""
    params = {
        "metric": "reach",
        "period": "day",
        "metric_type": "total_value",
        "breakdown": "follow_type",
        "access_token": access_token,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{ig_user_id}/insights", params)
    if error:
        return {
            "available": False, "follower": None, "non_follower": None,
            "total": None, "follower_pct": None, "note": error.get("message") or REASON_NO_DATA,
        }

    entries = data.get("data") or []
    total_value = entries[0].get("total_value") if entries else None
    total = (total_value or {}).get("value")
    breakdowns = (total_value or {}).get("breakdowns") if total_value else None
    results = (breakdowns[0].get("results") if breakdowns else None) or []
    if not results:
        return {
            "available": False, "follower": None, "non_follower": None,
            "total": total, "follower_pct": None, "note": REASON_NO_DATA,
        }

    by_type = {}
    for r in results:
        dims = r.get("dimension_values") or []
        value = r.get("value") or 0
        if dims:
            by_type[dims[0]] = value

    follower = by_type.get("FOLLOWER", 0)
    non_follower = by_type.get("NON_FOLLOWER", 0)
    follower_pct = round(follower / total * 100, 1) if total else None

    return {
        "available": True, "follower": follower, "non_follower": non_follower,
        "total": total, "follower_pct": follower_pct, "note": None,
    }


def fetch_follower_demographics(access_token: str, ig_user_id: str) -> dict:
    """Реальная органическая аудитория аккаунта (возраст/пол подписчиков) — follower_demographics
    из Instagram Graph API. Нужен Business/Creator-аккаунт с 100+ подписчиками и обязательный
    timeframe (since/until тут не работают — Meta требует именно timeframe для этой метрики).
    Если подписчиков меньше 100 или метрика недоступна — честно {"available": False}, не 0/выдумка.

    Используется, чтобы рекомендации по рекламной аудитории (app/ads_audience.py, app/ads_opus.py)
    опирались на РЕАЛЬНУЮ органическую аудиторию бренда, а не только на цифры самой рекламы."""
    params = {
        "metric": "follower_demographics",
        "period": "lifetime",
        "timeframe": "last_30_days",
        "breakdown": "age,gender",
        "metric_type": "total_value",
        "access_token": access_token,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{ig_user_id}/insights", params)
    if error:
        return {"available": False, "by_age": {}, "by_gender": {}, "note": error.get("message") or REASON_NO_DATA}

    entries = data.get("data") or []
    breakdowns = (entries[0].get("total_value") or {}).get("breakdowns") if entries else None
    results = (breakdowns[0].get("results") if breakdowns else None) or []
    if not results:
        return {"available": False, "by_age": {}, "by_gender": {}, "note": REASON_NO_DATA}

    by_age, by_gender = {}, {}
    for r in results:
        dims = r.get("dimension_values") or []
        value = r.get("value") or 0
        if len(dims) != 2:
            continue
        age, gender = dims
        by_age[age] = by_age.get(age, 0) + value
        by_gender[gender] = by_gender.get(gender, 0) + value

    return {"available": True, "by_age": by_age, "by_gender": by_gender, "note": None}
