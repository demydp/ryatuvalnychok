"""
Клиент TikTok for Developers (Login Kit OAuth v2 + Display API v2).

Честно про статус на момент написания (до первой живой диагностики на реальном аккаунте
владельца, см. app/routes/tiktok.py::run_diagnostic): набор реально возвращаемых полей
user.info/video.list зависит от того, какие scope одобрены конкретному TikTok-приложению
(sandbox-приложения часто получают урезанный набор, даже если сам код запрашивает scope
из SCOPES). Этот модуль запрашивает ПОЛНЫЙ документированный набор полей и передаёт сырой
ответ наверх как есть — какие поля реально пришли, а какие нет, решает диагностика по
факту, а не этот код заранее.

OAuth v2 обязательно требует PKCE (code_verifier/code_challenge, S256) для веб-приложений —
без него TikTok отклоняет /v2/auth/authorize/ с ошибкой конфигурации приложения.
"""
import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"

# video.list — нужен, чтобы вообще тянуть список роликов; user.info.basic/stats — аккаунт
# и его агрегаты (подписчики/лайки). Ничего сверх запрошенного в ТЗ владельца.
SCOPES = ("user.info.basic", "user.info.stats", "video.list")

# Полный документированный набор полей /v2/user/info/ — часть требует user.info.profile
# (username, bio_description, profile_deep_link, is_verified), которого нет в SCOPES выше
# (владелец не просил показывать био/профильную ссылку) — оставлены в запросе намеренно,
# чтобы диагностика честно показала, что именно API готов отдать УЖЕ выданными scope,
# а не просто повторяла список SCOPES.
USER_INFO_FIELDS = (
    "open_id,union_id,avatar_url,avatar_url_100,avatar_large_url,display_name,"
    "bio_description,profile_deep_link,is_verified,username,follower_count,"
    "following_count,likes_count,video_count"
)

VIDEO_FIELDS = (
    "id,create_time,cover_image_url,share_url,video_description,duration,height,"
    "width,title,embed_link,like_count,comment_count,share_count,view_count"
)


class TikTokAPIError(Exception):
    """Понятная ошибка для показа пользователю (проблема токена, прав, сети и т.п.)."""


class TikTokConfigError(Exception):
    """TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET/TIKTOK_REDIRECT_URI не заданы в оточенні —
    чесна помилка замість тихого провалу підключення."""


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise TikTokConfigError(
            f"{name} не задано в оточенні — підключення TikTok неможливе, поки власник "
            f"застосунку не додасть цю змінну (Render Variables / .env)."
        )
    return value


def client_key() -> str:
    return _get_env("TIKTOK_CLIENT_KEY")


def client_secret() -> str:
    return _get_env("TIKTOK_CLIENT_SECRET")


def redirect_uri() -> str:
    return _get_env("TIKTOK_REDIRECT_URI")


def is_configured() -> bool:
    return bool(
        os.environ.get("TIKTOK_CLIENT_KEY")
        and os.environ.get("TIKTOK_CLIENT_SECRET")
        and os.environ.get("TIKTOK_REDIRECT_URI")
    )


def generate_pkce_pair() -> tuple:
    """(code_verifier, code_challenge) — verifier 43-128 символів (специфікація PKCE
    RFC 7636), challenge = base64url(sha256(verifier)) без паддінгу, як вимагає TikTok."""
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "client_key": client_key(),
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _post_form(url: str, data: dict) -> dict:
    """/v2/oauth/token/ отвечает в "плоском" OAuth2-стиле (access_token напрямую в корне
    успеха; {"error": "...", "error_description": "..."} при провале) — не в конверте
    {"data":..., "error":{"code":"ok"}}, которым отвечают /v2/user/info/ и /v2/video/list/
    (см. _call_open_api ниже). Это два разных семейства эндпоинтов TikTok, не наша путаница."""
    try:
        resp = requests.post(
            url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30
        )
        payload = resp.json()
    except requests.RequestException as e:
        raise TikTokAPIError(f"TikTok API недоступний: {e}") from None
    except ValueError:
        raise TikTokAPIError("TikTok API повернув невалідну відповідь") from None

    error = payload.get("error")
    if error:
        if isinstance(error, dict):
            raise TikTokAPIError(error.get("message") or error.get("code") or str(error))
        raise TikTokAPIError(payload.get("error_description") or str(error))
    if "access_token" not in payload:
        raise TikTokAPIError("TikTok не повернув access_token")
    return payload


def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """Возвращает сырой ответ TikTok: access_token, expires_in, open_id, refresh_token,
    refresh_expires_in, scope, token_type."""
    data = {
        "client_key": client_key(),
        "client_secret": client_secret(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
        "code_verifier": code_verifier,
    }
    return _post_form(TOKEN_URL, data)


def refresh_access_token(refresh_token: str) -> dict:
    data = {
        "client_key": client_key(),
        "client_secret": client_secret(),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return _post_form(TOKEN_URL, data)


def _call_open_api(url: str, access_token: str, method: str = "GET", params: dict = None, json_body: dict = None):
    """/v2/user/info/ и /v2/video/list/ — общий конверт ответа:
    {"data": {...}, "error": {"code": "ok"|"...", "message": "...", "log_id": "..."}}.
    Возвращает (data_dict, error_dict) — error_dict с code=="ok" означает успех (TikTok
    всегда присылает объект error, даже при успехе, просто с кодом "ok")."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        else:
            headers["Content-Type"] = "application/json"
            resp = requests.post(url, headers=headers, params=params, json=json_body, timeout=30)
        payload = resp.json()
    except requests.RequestException as e:
        raise TikTokAPIError(f"TikTok API недоступний: {e}") from None
    except ValueError:
        raise TikTokAPIError("TikTok API повернув невалідну відповідь") from None

    error = payload.get("error") or {}
    if error.get("code") not in (None, "ok"):
        raise TikTokAPIError(error.get("message") or error.get("code") or "Невідома помилка TikTok API")
    return payload.get("data", {}) or {}, error


def get_user_info_raw(access_token: str, fields: str = USER_INFO_FIELDS) -> dict:
    """Сырой data-блок ответа (обычно {"user": {...}}) — диагностика (app/routes/tiktok.py)
    сама решает, какие из запрошенных полей реально пришли."""
    data, _ = _call_open_api(USER_INFO_URL, access_token, params={"fields": fields})
    return data


def get_user_info(access_token: str, fields: str = USER_INFO_FIELDS) -> dict:
    return get_user_info_raw(access_token, fields).get("user", {})


def list_videos_raw(access_token: str, cursor: int = 0, max_count: int = 20, fields: str = VIDEO_FIELDS) -> dict:
    """Сырой data-блок ({"videos": [...], "cursor": ..., "has_more": bool})."""
    data, _ = _call_open_api(
        f"{VIDEO_LIST_URL}?fields={fields}",
        access_token,
        method="POST",
        json_body={"cursor": cursor, "max_count": max_count},
    )
    return data


def fetch_all_videos(access_token: str, max_videos: int = 100) -> list:
    """Пагинация через cursor/has_more, до max_videos штук — та же логика постраничного
    сбора, что app/instagram_api.py::fetch_all_media, только курсор вместо paging.next."""
    items = []
    cursor = 0
    while True:
        page = list_videos_raw(access_token, cursor=cursor, max_count=min(20, max_videos - len(items)))
        items.extend(page.get("videos", []) or [])
        if max_videos and len(items) >= max_videos:
            return items[:max_videos]
        if not page.get("has_more"):
            return items
        cursor = page.get("cursor", 0)
        if not cursor:
            return items
