"""
Фоновые задачи (пункты B и D ТЗ, + авто-обновление данных):
1. Проверка/автопродление IG-токена — чтобы токен не истекал незаметно (см. token_refresh.py).
2. Сбор ежедневного среза активной рекламы в историю отчётов (см. daily_report.py).
3. Авто-обновление метрик Instagram и структуры рекламного кабинета активного проекта —
   раз в auto_refresh_interval_hours часов, чтобы не нажимать «Синхронизировать» вручную.

BackgroundScheduler живёт в том же процессе, что и Flask.

Этап 1 веб-версії: раніше все це проганялось по ВСІХ проєктах ОДНОГО (єдиного) юзера напряму
через project_store.py. Тепер юзерів багато, а project_store.py/config_store.py — тонкі фасади
над flask_login.current_user (див. ті файли) — поза HTTP-запитом current_user просто немає.
Тому тут для кожного юзера окремо піднімається test_request_context() + login_user(user) (сам
Flask-Login так і документує "залогінитись" у фоновому скрипті — це виставляє current_user
на час контексту БЕЗ реальної HTTP-сесії) — і всередині цього контексту вся існуюча бізнес-логіка
(collect_daily_snapshot, refresh_if_needed, run_metrics_sync, run_ads_sync) працює НЕЗМІННО,
як і раніше, просто в рамках "поточного" юзера цієї ітерації.

Розклад (daily_report_hour/auto_refresh_interval_hours) поки СПІЛЬНИЙ для всіх юзерів
(фіксовані константи нижче), не per-user — per-user динамічний розклад лишається на Этап 2.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask_login import login_user

logger = logging.getLogger("reels_dashboard")

_scheduler = None

# Спільний розклад для всіх юзерів (Этап 1 — per-user налаштування daily_report_hour/
# auto_refresh_interval_hours з UserSettings поки не читаються фоновими job'ами, лишається
# на Этап 2, коли з'явиться реальна потреба в персональному розкладі по юзерах).
DAILY_REPORT_HOUR = 20
AUTO_REFRESH_HOURS = 4


def _all_users():
    from app.models import User

    return User.query.all()


def _run_token_refresh_job(app):
    """Проходится по ВСЕМ проектам ВСЕХ юзеров — иначе токен клиента, на которого сейчас не
    переключены (или чужого юзера), тихо истекает незамеченным."""
    from app.project_store import load_projects
    from app.token_refresh import refresh_if_needed

    for user in _all_users():
        with app.test_request_context():
            login_user(user)
            for project in load_projects():
                try:
                    result = refresh_if_needed(project_id=project["id"], force=False)
                    if result["action"] == "refreshed":
                        logger.info("Плановая проверка токена (%s): продлён, годен до %s", project["name"], result.get("expires_at"))
                    elif result["action"] == "failed":
                        logger.warning("Плановая проверка токена (%s): продление не удалось (%s)", project["name"], result.get("reason"))
                except Exception:
                    logger.exception("Плановая проверка токена (%s) упала с исключением", project["name"])


def _run_daily_report_job(app):
    """Проходится по ВСЕМ проектам ВСЕХ юзеров — история расходов каждого клиента должна
    собираться независимо от того, какой проект сейчас активен в UI и кто сейчас залогинен."""
    from app.daily_report import collect_daily_snapshot
    from app.project_store import load_projects

    for user in _all_users():
        with app.test_request_context():
            login_user(user)
            for project in load_projects():
                try:
                    report = collect_daily_snapshot(project_id=project["id"])
                    if "error" in report:
                        logger.warning("Плановый сбор дневного отчёта (%s): %s", project["name"], report["error"])
                except Exception:
                    logger.exception("Плановый сбор дневного отчёта (%s) упал с исключением", project["name"])


def _run_auto_refresh_job(app):
    """Авто-обновление метрик + рекламы ТОЛЬКО активного проекта КАЖДОГО юзера (не всех его
    проектов) — пользователь смотрит дашборд одного проекта за раз, и именно его данные должны
    быть свежими без ручного клика. Rate-limit Meta уже обработан внутри самих fetch-функций
    (retry+backoff, см. app/instagram_api.py и app/ads_api.py) — здесь достаточно просто не дать
    одной сбойной части (например, не настроен Ad Account) уронить другую."""
    from app.project_store import get_active_project

    for user in _all_users():
        with app.test_request_context():
            login_user(user)
            project = get_active_project()
            if not project:
                continue

            from app.routes.metrics import run_metrics_sync

            try:
                metrics_result = run_metrics_sync()
                if "error" in metrics_result:
                    logger.info("Авто-обновление метрик (%s): пропущено (%s)", project["name"], metrics_result["error"])
                else:
                    logger.info("Авто-обновление метрик (%s): готово, постов %s", project["name"], metrics_result.get("total_media"))
            except Exception:
                logger.exception("Авто-обновление метрик (%s) упало с исключением", project["name"])

            from app.routes.ads import run_ads_sync, save_ads_cache

            try:
                ads_result = run_ads_sync()
                if "error" in ads_result:
                    # Нет Ad Account ID/токена — обычная ситуация для чисто органического проекта,
                    # не ошибка, поэтому не логируем как warning.
                    logger.info("Авто-обновление рекламы (%s): пропущено (%s)", project["name"], ads_result["error"])
                else:
                    save_ads_cache(ads_result)
                    logger.info("Авто-обновление рекламы (%s): готово, кампаний %s", project["name"], len(ads_result.get("campaigns", [])))
            except Exception:
                logger.exception("Авто-обновление рекламы (%s) упало с исключением", project["name"])


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    # Проверка токена раз в сутки в 03:00 — задолго до рабочего часа синка, продление
    # (когда нужно) успеет пройти и не помешает синку в дневное время.
    _scheduler.add_job(_run_token_refresh_job, "cron", hour=3, minute=0, id="token_refresh_daily", args=[app])
    _scheduler.add_job(_run_daily_report_job, "cron", hour=DAILY_REPORT_HOUR, minute=0, id="daily_report_snapshot", args=[app])
    # Первый прогон — вскоре после старта (не сразу: даём Flask/сети время подняться), дальше
    # строго каждые AUTO_REFRESH_HOURS часов, пока процесс работает.
    _scheduler.add_job(
        _run_auto_refresh_job, IntervalTrigger(hours=AUTO_REFRESH_HOURS), id="auto_refresh_metrics_ads", args=[app],
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    _scheduler.start()
    logger.info(
        "Планировщик запущен: продление токена в 03:00, сбор дневного отчёта в %02d:00, "
        "авто-обновление метрик/рекламы каждые %d ч. (для всех юзеров).", DAILY_REPORT_HOUR, AUTO_REFRESH_HOURS,
    )
    return _scheduler
