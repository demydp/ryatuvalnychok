"""
Автопродление Instagram Access Token — заявленная в TZ причина, почему пользователю
приходится "заново вводить ключи": долгоживущий IG-токен живёт ограниченное время
(обычно 60 дней у токенов Instagram Login), и без автопродления любой синк после
истечения падает с ошибкой авторизации, а пользователь воспринимает это как "программа
сломалась и просит ключи заново".

Два независимых механизма, оба честные (не выдумывают статус, которого не знают):
1. check_token_status — спрашивает Meta напрямую (/debug_token), сколько токену осталось
   жить. Использует сам токен как app-token для интроспекции (стандартный паттерн Graph API
   для токенов пользователя/страницы, не требует отдельного App ID/Secret).
2. try_refresh_token — продлевает токен через graph.instagram.com/refresh_access_token
   (ig_refresh_token grant) — это единственный вид продления, для которого НЕ нужен
   App ID/Secret (в отличие от fb_exchange_token для Facebook Login for Business, который
   программа не запрашивает у пользователя и поэтому поддержать не может). Работает только
   для токенов, выданных через Instagram Login (instagram_business_basic и т.п.) — для
   Page Access Token (Facebook Login for Business) Meta вернёт ошибку, и мы её честно
   показываем, а не притворяемся, что продлили.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from app.i18n import t

GRAPH_BASE = "https://graph.facebook.com/v21.0"
IG_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"

# Продлеваем заранее, не дожидаясь истечения — оставляем запас на случай, если планировщик
# в какой-то день не сработает (компьютер был выключен и т.п.)
REFRESH_MARGIN_DAYS = 10

logger = logging.getLogger("reels_dashboard")


class TokenRefreshError(Exception):
    """Понятная причина, почему продлить/проверить токен не вышло."""


def check_token_status(access_token: str) -> dict:
    """
    Возвращает {"is_valid": bool, "expires_at": datetime|None (None = не удалось узнать
    или токен бессрочный), "scopes": [...]}. Никогда не бросает исключение — по сети/API
    может не получиться, тогда is_valid=None (неизвестно, не "ошибка" и не "всё ок").
    """
    if not access_token:
        return {"is_valid": None, "expires_at": None, "scopes": [], "error": t("token_refresh.error.no_token")}

    try:
        resp = requests.get(
            f"{GRAPH_BASE}/debug_token",
            params={"input_token": access_token, "access_token": access_token},
            timeout=20,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        return {"is_valid": None, "expires_at": None, "scopes": [], "error": t("token_refresh.error.check_unavailable", error=e)}

    if "error" in payload:
        return {"is_valid": False, "expires_at": None, "scopes": [], "error": payload["error"].get("message", t("token_refresh.error.invalid"))}

    data = payload.get("data", {})
    expires_at_ts = data.get("expires_at")
    # 0 у Meta означает "бессрочный токен" (Page Token, полученный через долгоживущий User Token)
    expires_at = None
    if expires_at_ts:
        expires_at = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)

    return {
        "is_valid": bool(data.get("is_valid")),
        "expires_at": expires_at,
        "scopes": data.get("scopes", []),
        "error": None,
    }


def try_refresh_token(access_token: str) -> dict:
    """Продлевает токен через ig_refresh_token grant. Возвращает {"access_token", "expires_at"}.
    Бросает TokenRefreshError с понятной причиной, если продление недоступно для этого токена."""
    try:
        resp = requests.get(
            IG_REFRESH_URL,
            params={"grant_type": "ig_refresh_token", "access_token": access_token},
            timeout=20,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise TokenRefreshError(t("token_refresh.error.service_unavailable", error=e)) from None

    if "error" in payload or "access_token" not in payload:
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else payload.get("error")
        raise TokenRefreshError(message or t("token_refresh.error.cannot_refresh"))

    expires_in = payload.get("expires_in")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
    return {"access_token": payload["access_token"], "expires_at": expires_at}


def refresh_if_needed(project_id: str = None, force: bool = False) -> dict:
    """
    Оркестрация для планировщика и кнопки "Обновить сейчас": проверяет статус IG-токена
    проекта, продлевает если срок подходит к концу (или force=True), сохраняет результат
    обратно в этот проект. Возвращает сводку для UI/лога — никогда не бросает исключение
    наружу (вызывается из фонового потока планировщика, где некому его поймать).

    project_id — явно указанный проект (планировщик проходится по ВСЕМ проектам, чтобы
    токен неактивного клиента не истёк незаметно); None = текущий активный (кнопка в UI).
    """
    from app.project_store import get_effective_config, get_project, update_active_project, update_project

    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    token = cfg.get("ig_access_token")
    if not token:
        return {"action": "skipped", "reason": t("token_refresh.reason.no_token")}

    status = check_token_status(token)
    # Сериализуем datetime сразу — этот словарь может уйти напрямую в jsonify() из роута
    # ручного обновления, а datetime не JSON-сериализуем "из коробки".
    status_out = {**status, "expires_at": status["expires_at"].isoformat() if status["expires_at"] else None}

    if status["is_valid"] is False:
        return {"action": "none", "reason": status["error"] or t("token_refresh.reason.invalid_reenter"), "status": status_out}

    needs_refresh = force
    if status["expires_at"]:
        needs_refresh = needs_refresh or (status["expires_at"] - datetime.now(timezone.utc) <= timedelta(days=REFRESH_MARGIN_DAYS))

    if not needs_refresh:
        return {"action": "none", "reason": t("token_refresh.reason.not_needed_yet"), "status": status_out}

    try:
        refreshed = try_refresh_token(token)
    except TokenRefreshError as e:
        logger.warning("Автопродление IG-токена не удалось: %s", e)
        return {"action": "failed", "reason": str(e), "status": status_out}

    updates = {
        "ig_access_token": refreshed["access_token"],
        "ig_token_obtained_at": datetime.now(timezone.utc).isoformat(),
        "ig_token_expires_at": refreshed["expires_at"].isoformat() if refreshed["expires_at"] else "",
    }
    if project_id:
        update_project(project_id, updates)
    else:
        update_active_project(updates)
    logger.info("IG-токен успешно продлён, годен до %s", refreshed["expires_at"])
    return {"action": "refreshed", "reason": None, "expires_at": refreshed["expires_at"].isoformat() if refreshed["expires_at"] else None}
