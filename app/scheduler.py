"""
Фоновые задачи (пункты B и D ТЗ, + авто-обновление данных):
1. Проверка/автопродление IG-токена — чтобы токен не истекал незаметно (см. token_refresh.py).
2. Сбор ежедневного среза активной рекламы в историю отчётов (см. daily_report.py).
3. Авто-обновление метрик Instagram и структуры рекламного кабинета — раз в AUTO_REFRESH_HOURS
   часов, чтобы не нажимать «Синхронизировать» вручную.

BackgroundScheduler живёт в том же процессе, что и Flask.

Этап 1 веб-версії: раніше все це проганялось по ВСІХ проєктах ОДНОГО (єдиного) юзера напряму
через project_store.py. Тепер юзерів багато, а project_store.py/config_store.py — тонкі фасади
над flask_login.current_user (див. ті файли) — поза HTTP-запитом current_user просто немає.
Тому для кожної (юзер, проєкт) пари окремо піднімається test_request_context() + login_user(user)
(сам Flask-Login так і документує "залогінитись" у фоновому скрипті) — і всередині цього контексту
вся існуюча бізнес-логіка (collect_daily_snapshot, refresh_if_needed, run_metrics_sync,
run_ads_sync) працює НЕЗМІННО, як і раніше, просто в рамках "поточного" юзера/проєкту.

Этап 2: черга + пауза між елементами (JOB_ITEM_DELAY_SEC), а не тугий цикл підряд по всіх
юзерах/проєктах одразу — інакше 50 юзерів по 3 проєкти це 150 синків Meta API поспіль в один
момент, і навіть при робочому per-call retry+backoff (app/instagram_api.py, app/ads_api.py)
це невиправдано б'є по rate limit і затримує процес. Список (юзер, проєкт) будується ОДИН РАЗ
на початку job'у напряму через app/db_store.py (явний user_id, без login) — легше і безпечніше,
ніж тримати відкритим test_request_context() під час усієї паузи. Авто-оновлення метрик/реклами
тепер проходиться по ВСІХ проєктах усіх юзерів (не лише активному) — інакше дані неактивного
клієнта тихо застарівали б між заходами в UI (мультипроєкт, Этап 2).

Розклад (daily_report_hour/auto_refresh_interval_hours) поки СПІЛЬНИЙ для всіх юзерів
(фіксовані константи нижче), не per-user — per-user динамічний розклад лишається на майбутнє.
"""
import logging
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask_login import login_user

logger = logging.getLogger("reels_dashboard")

_scheduler = None

# Спільний розклад для всіх юзерів (per-user налаштування daily_report_hour/
# auto_refresh_interval_hours з UserSettings поки не читаються фоновими job'ами — лишається
# на майбутнє, коли з'явиться реальна потреба в персональному розкладі по юзерах).
DAILY_REPORT_HOUR = 20
AUTO_REFRESH_HOURS = 4

# Пауза між обробкою кожної (юзер, проєкт) пари в черзі — розтягує навантаження на Meta API
# замість того, щоб бити всіма запитами одночасно. Додатково подовжується, якщо попередній
# елемент явно впав через rate limit (RATE_LIMIT_BACKOFF_SEC), щоб дати Meta час "охолонути"
# перед наступним запитом, а не одразу тицяти в неї знову.
JOB_ITEM_DELAY_SEC = 1.5
RATE_LIMIT_BACKOFF_SEC = 20
# Ключевые фразы для м'якого розпізнавання rate-limit помилки з готового тексту {"error": ...}
# (переклад ads.msg.rate_limited АБО сире повідомлення Meta після вичерпаних retry в
# app/instagram_api.py/app/ads_api.py, де структурований код помилки вже втрачено) — не точна
# перевірка коду, лише підказка "притримати чергу довше, ніж звичайну паузу".
_RATE_LIMIT_HINTS = (
    "rate_limited", "rate limit", "request limit", "limit reached", "too many calls",
    "ліміт запитів", "лимит запросов",
)


def _is_rate_limit_message(text) -> bool:
    if not text:
        return False
    low = str(text).lower()
    return any(hint in low for hint in _RATE_LIMIT_HINTS)


def _all_user_project_pairs():
    """Список (user, project_dict) для ВСІХ юзерів і ВСІХ їхніх проєктів — читається НАПРЯМУ
    з БД (явний user_id, app/db_store.py), без login_user()/test_request_context(): це лише
    перелік, самі job'и логіняться під кожного user окремо в момент обробки ЙОГО елемента."""
    from app.db_store import load_user_projects
    from app.models import User

    pairs = []
    for user in User.query.all():
        for project in load_user_projects(user.id):
            pairs.append((user, project))
    return pairs


def _run_token_refresh_job(app):
    """Проходиться по ВСІХ проєктах ВСІХ юзерів — інакше токен клієнта, на якого зараз не
    перемкнуті (чи чужого юзера), тихо спливає непоміченим."""
    from app.token_refresh import refresh_if_needed

    with app.app_context():
        pairs = _all_user_project_pairs()

    for user, project in pairs:
        with app.test_request_context():
            login_user(user)
            try:
                result = refresh_if_needed(project_id=project["id"], force=False)
                if result["action"] == "refreshed":
                    logger.info("Плановая проверка токена (%s): продлён, годен до %s", project["name"], result.get("expires_at"))
                elif result["action"] == "failed":
                    logger.warning("Плановая проверка токена (%s): продление не удалось (%s)", project["name"], result.get("reason"))
            except Exception:
                logger.exception("Плановая проверка токена (%s) упала с исключением", project["name"])
        time.sleep(JOB_ITEM_DELAY_SEC)


def _run_daily_report_job(app):
    """Проходиться по ВСІХ проєктах ВСІХ юзерів — історія витрат кожного клієнта повинна
    збиратись незалежно від того, який проєкт зараз активний в UI і хто зараз залогінений."""
    from app.daily_report import collect_daily_snapshot

    with app.app_context():
        pairs = _all_user_project_pairs()

    for user, project in pairs:
        with app.test_request_context():
            login_user(user)
            try:
                report = collect_daily_snapshot(project_id=project["id"])
                if "error" in report:
                    logger.warning("Плановый сбор дневного отчёта (%s): %s", project["name"], report["error"])
            except Exception:
                logger.exception("Плановый сбор дневного отчёта (%s) упал с исключением", project["name"])
        time.sleep(JOB_ITEM_DELAY_SEC)


def _run_auto_refresh_job(app):
    """Авто-оновлення метрик + реклами по ВСІХ проєктах ВСІХ юзерів (Этап 2 — раніше тільки
    активний проєкт кожного юзера, чого недостатньо для мультипроєкту: дані неактивного клієнта
    мають лишатись свіжими, а не застарівати між заходами в UI). Rate-limit Meta вже оброблений
    на рівні одного виклику (retry+backoff, app/instagram_api.py/app/ads_api.py) — тут достатньо
    не дати одному впалому проєкту зупинити чергу і додатково притримати темп після rate-limit'у."""
    from app.routes.ads import run_ads_sync, save_ads_cache
    from app.routes.metrics import run_metrics_sync

    with app.app_context():
        pairs = _all_user_project_pairs()

    logger.info("Авто-обновление: в очереди %d проєкт(ів)", len(pairs))

    for user, project in pairs:
        project_id = project["id"]
        delay = JOB_ITEM_DELAY_SEC
        with app.test_request_context():
            login_user(user)

            try:
                metrics_result = run_metrics_sync(project_id=project_id)
                if "error" in metrics_result:
                    logger.info("Авто-обновление метрик (%s): пропущено (%s)", project["name"], metrics_result["error"])
                    if _is_rate_limit_message(metrics_result["error"]):
                        delay = max(delay, RATE_LIMIT_BACKOFF_SEC)
                else:
                    logger.info("Авто-обновление метрик (%s): готово, постов %s", project["name"], metrics_result.get("total_media"))
            except Exception:
                logger.exception("Авто-обновление метрик (%s) упало с исключением", project["name"])

            try:
                ads_result = run_ads_sync(project_id=project_id)
                if "error" in ads_result:
                    # Нет Ad Account ID/токена — обычная ситуация для чисто органического проекта,
                    # не ошибка, поэтому не логируем как warning.
                    logger.info("Авто-обновление рекламы (%s): пропущено (%s)", project["name"], ads_result["error"])
                    if _is_rate_limit_message(ads_result["error"]):
                        delay = max(delay, RATE_LIMIT_BACKOFF_SEC)
                else:
                    save_ads_cache(ads_result, project_id=project_id)
                    logger.info("Авто-обновление рекламы (%s): готово, кампаний %s", project["name"], len(ads_result.get("campaigns", [])))
            except Exception:
                logger.exception("Авто-обновление рекламы (%s) упало с исключением", project["name"])

        time.sleep(delay)


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
        "авто-обновление метрик/рекламы каждые %d ч. (для всех юзеров и всех их проєктов).", DAILY_REPORT_HOUR, AUTO_REFRESH_HOURS,
    )
    return _scheduler
