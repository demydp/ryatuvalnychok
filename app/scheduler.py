"""
Фоновые задачи (пункты B и D ТЗ, + авто-обновление данных):
1. Проверка/автопродление IG-токена — чтобы токен не истекал незаметно (см. token_refresh.py).
2. Сбор ежедневного среза активной рекламы в историю отчётов (см. daily_report.py).
3. Авто-обновление метрик Instagram и структуры рекламного кабинета активного проекта —
   раз в auto_refresh_interval_hours часов, чтобы не нажимать «Синхронизировать» вручную
   (заготовка под веб-версию, где это будет делаться на сервере по каждому аккаунту).

BackgroundScheduler живёт в том же процессе, что и Flask — при pythonw.exe (без консоли)
это единственный практичный способ иметь расписание без отдельного Windows Task Scheduler,
который пользователю пришлось бы настраивать руками.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("reels_dashboard")

_scheduler = None


def _run_token_refresh_job(app):
    """Проходится по ВСЕМ проектам (не только активному) — иначе токен клиента, на которого
    сейчас не переключены, тихо истекает незамеченным."""
    from app.project_store import load_projects
    from app.token_refresh import refresh_if_needed

    # t() (используется глубже по цепочке вызовов через i18n) читает request.headers —
    # без активного контекста запроса это падает с RuntimeError, а фоновый job планировщика
    # не имеет реального HTTP-запроса. test_request_context эмулирует пустой запрос
    # (язык по умолчанию — ru), этого достаточно для серверных логов/сохранения в файл.
    for project in load_projects():
        try:
            with app.test_request_context():
                result = refresh_if_needed(project_id=project["id"], force=False)
            if result["action"] == "refreshed":
                logger.info("Плановая проверка токена (%s): продлён, годен до %s", project["name"], result.get("expires_at"))
            elif result["action"] == "failed":
                logger.warning("Плановая проверка токена (%s): продление не удалось (%s)", project["name"], result.get("reason"))
        except Exception:
            logger.exception("Плановая проверка токена (%s) упала с исключением", project["name"])


def _run_daily_report_job(app):
    """Проходится по ВСЕМ проектам — история расходов каждого клиента должна собираться
    независимо от того, какой проект сейчас активен в UI."""
    from app.daily_report import collect_daily_snapshot
    from app.project_store import load_projects

    for project in load_projects():
        try:
            with app.test_request_context():
                report = collect_daily_snapshot(project_id=project["id"])
            if "error" in report:
                logger.warning("Плановый сбор дневного отчёта (%s): %s", project["name"], report["error"])
        except Exception:
            logger.exception("Плановый сбор дневного отчёта (%s) упал с исключением", project["name"])


def _run_auto_refresh_job(app):
    """Авто-обновление метрик + рекламы ТОЛЬКО активного проекта (не всех, в отличие от
    job'ов выше) — пользователь смотрит дашборд одного проекта за раз, и именно его данные
    должны быть свежими без ручного клика. Rate-limit Meta уже обработан внутри самих
    fetch-функций (retry+backoff, см. app/instagram_api.py и app/ads_api.py) — здесь достаточно
    просто не дать одной сбойной части (например, не настроен Ad Account) уронить другую."""
    from app.project_store import get_active_project

    project = get_active_project()
    if not project:
        return

    with app.test_request_context():
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

    from app.config_store import load_config

    cfg = load_config()
    hour = cfg.get("daily_report_hour", 20)
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        hour = 20
    hour = max(0, min(23, hour))

    refresh_hours = cfg.get("auto_refresh_interval_hours", 4)
    try:
        refresh_hours = int(refresh_hours)
    except (TypeError, ValueError):
        refresh_hours = 4
    refresh_hours = max(3, min(6, refresh_hours))

    _scheduler = BackgroundScheduler(daemon=True)
    # Проверка токена раз в сутки в 03:00 — задолго до рабочего часа синка, продление
    # (когда нужно) успеет пройти и не помешает синку в дневное время.
    _scheduler.add_job(_run_token_refresh_job, "cron", hour=3, minute=0, id="token_refresh_daily", args=[app])
    _scheduler.add_job(_run_daily_report_job, "cron", hour=hour, minute=0, id="daily_report_snapshot", args=[app])
    # Первый прогон — вскоре после старта (не сразу: даём Flask/сети время подняться), дальше
    # строго каждые refresh_hours часов, пока процесс работает.
    _scheduler.add_job(
        _run_auto_refresh_job, IntervalTrigger(hours=refresh_hours), id="auto_refresh_metrics_ads", args=[app],
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    _scheduler.start()
    logger.info(
        "Планировщик запущен: продление токена в 03:00, сбор дневного отчёта в %02d:00, "
        "авто-обновление метрик/рекламы каждые %d ч.", hour, refresh_hours,
    )
    return _scheduler
