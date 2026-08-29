"""
Автопродление TikTok access_token — access_token живёт ~24 часа (у TikTok это фиксированный,
короткий срок, не настраиваемый), refresh_token — обычно ~365 дней. Без автопродления любой
синк после суток простоя падает с ошибкой авторизации.

В отличие от app/token_refresh.py (IG, ig_refresh_token grant без App ID/Secret), TikTok
всегда требует client_key/client_secret для refresh_token grant — они у нас есть (то же
приложение, что и для самого OAuth, см. app/tiktok_api.py), поэтому продление работает
для любого токена, полученного через наш OAuth-флоу, без исключений вида "этот тип токена
продлить нельзя".
"""
import logging
from datetime import datetime, timedelta, timezone

from app.tiktok_api import TikTokAPIError, TikTokConfigError, refresh_access_token

logger = logging.getLogger("reels_dashboard")

# Продлеваем заранее — access_token живёт ~24ч, поэтому запас в часах, а не днях (в отличие
# от IG, где REFRESH_MARGIN_DAYS=10 при токене на 60 дней).
REFRESH_MARGIN_HOURS = 6


class TikTokTokenRefreshError(Exception):
    pass


def refresh_if_needed(project_id: str = None, force: bool = False) -> dict:
    """Аналог app/token_refresh.py::refresh_if_needed для TikTok — используется и планировщиком
    (app/scheduler.py), и (в будущем) кнопкой в Настройках. Никогда не бросает исключение
    наружу — вызывается из фонового потока, где некому его поймать."""
    from app.project_store import get_effective_config, get_project, update_active_project, update_project

    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    refresh_token = cfg.get("tiktok_refresh_token")
    if not refresh_token:
        return {"action": "skipped", "reason": "немає підключеного TikTok-акаунту"}

    expires_at_str = cfg.get("tiktok_access_token_expires_at")
    needs_refresh = force
    if not needs_refresh and expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
        except ValueError:
            expires_at = None
        if expires_at:
            needs_refresh = expires_at - datetime.now(timezone.utc) <= timedelta(hours=REFRESH_MARGIN_HOURS)
    elif not expires_at_str:
        # Немає збереженого часу закінчення — безпечніше продовжити, ніж мовчки лишити
        # протухлий токен непоміченим до першого невдалого синку.
        needs_refresh = True

    if not needs_refresh:
        return {"action": "none", "reason": "продовження ще не потрібне"}

    try:
        payload = refresh_access_token(refresh_token)
    except TikTokConfigError as e:
        return {"action": "skipped", "reason": str(e)}
    except TikTokAPIError as e:
        logger.warning("Автопродовження TikTok-токена не вдалося: %s", e)
        return {"action": "failed", "reason": str(e)}

    now = datetime.now(timezone.utc)
    access_expires_at = now + timedelta(seconds=payload.get("expires_in", 0))
    refresh_expires_at = now + timedelta(seconds=payload.get("refresh_expires_in", 0)) if payload.get("refresh_expires_in") else None

    updates = {
        "tiktok_access_token": payload["access_token"],
        "tiktok_refresh_token": payload.get("refresh_token", refresh_token),
        "tiktok_token_obtained_at": now.isoformat(),
        "tiktok_access_token_expires_at": access_expires_at.isoformat(),
        "tiktok_refresh_token_expires_at": refresh_expires_at.isoformat() if refresh_expires_at else "",
    }
    if project_id:
        update_project(project_id, updates)
    else:
        update_active_project(updates)
    logger.info("TikTok-токен успішно продовжено, дійсний до %s", access_expires_at)
    return {"action": "refreshed", "expires_at": access_expires_at.isoformat()}
