"""
Клиент Facebook Page Graph API (graph.facebook.com/v21.0) — намеренно ограниченный.

Диагностика (август 2026, живой аккаунт, PAGE access token) показала, что реально
отдаётся без ошибок:
- fan_count / followers_count на самой странице,
- список постов страницы (id, message, created_time, permalink_url, full_picture).

Всё остальное честно недоступно этому токену прямо сейчас:
- реакции/лайки/комментарии поста (edge reactions.summary()/likes.summary()) — падают
  с (#10) "требуется pages_read_user_content permission или Page Public Content Access
  feature" — это ОТДЕЛЬНОЕ разрешение, не совпадает с уже выданным pages_read_engagement;
- метрики уровня поста (post_clicks, post_video_views, post_impressions через
  /{post-id}/insights) — падают с (#100) "must be a valid insights metric": имена
  метрик вообще не существуют в текущей версии API, это не вопрос прав;
- метрики уровня страницы (page_post_engagements, page_follows, page_video_views через
  /{page-id}/insights) — валидные имена метрик, но всегда возвращают HTTP 200 с пустым
  data: [] независимо от периода/диапазона дат — тот же дефицит read_insights, только
  без явного текста ошибки;
- page_impressions* — падают с тем же (#100) "must be a valid insights metric":
  Meta убрала read_insights как отдельное выдаваемое разрешение в 2026 (нет в Graph API
  Explorer, Live-приложения с ним блокируются), и вместе с ним эти имена метрик.

Поэтому этот модуль НЕ пытается запрашивать что-либо из перечисленного выше — только
то, что реально подтверждено рабочим.
"""
import requests

from app.i18n import t

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

PAGE_POST_FIELDS = "id,message,created_time,permalink_url,full_picture"


class FacebookAPIError(Exception):
    """Понятная ошибка для показа пользователю (проблема токена, прав и т.п.)."""


def _get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    try:
        resp = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=30)
        data = resp.json()
    except requests.RequestException as e:
        raise FacebookAPIError(t("instagram.error.api_unavailable", error=e)) from None
    except ValueError:
        raise FacebookAPIError(t("instagram.error.bad_response")) from None

    if "error" in data:
        raise FacebookAPIError(data["error"].get("message", t("instagram.error.unknown_graph_api_error")))
    return data


def _debug_token_granular_scopes(access_token: str) -> list:
    try:
        data = _get("debug_token", access_token, input_token=access_token)
    except FacebookAPIError:
        return []
    return data.get("data", {}).get("granular_scopes", []) or []


def resolve_fb_pages(access_token: str) -> list:
    """Список Facebook-страниц, до которых у токена есть pages_* доступ. Business Login
    токены отдают пустой /me/accounts (та же ситуация, что и в app/instagram_api.py
    resolve_ig_user) — реальный источник page id это granular_scopes токена."""
    page_ids = []
    for entry in _debug_token_granular_scopes(access_token):
        if not entry.get("scope", "").startswith("pages_"):
            continue
        for target_id in entry.get("target_ids", []) or []:
            if target_id not in page_ids:
                page_ids.append(target_id)

    pages = []
    for page_id in page_ids:
        try:
            info = _get(page_id, access_token, fields="id,name,access_token")
        except FacebookAPIError:
            continue
        page_token = info.get("access_token")
        if not page_token:
            continue
        pages.append({"id": info["id"], "name": info.get("name", ""), "access_token": page_token})
    return pages


def get_page_summary(page_id: str, page_token: str) -> dict:
    """fan_count/followers_count — единственные подтверждённо рабочие числовые поля страницы."""
    return _get(page_id, page_token, fields="id,name,fan_count,followers_count")


def fetch_page_posts(page_id: str, page_token: str, limit: int = 10) -> list:
    """Последние посты страницы без метрик вовлечённости (см. модульный докстринг —
    почему метрики недоступны). Только то, что отдаёт сама нода поста."""
    data = _get(f"{page_id}/posts", page_token, fields=PAGE_POST_FIELDS, limit=limit)
    return data.get("data", []) or []
