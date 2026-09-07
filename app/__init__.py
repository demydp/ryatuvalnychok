import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager, current_user, login_user
from werkzeug.middleware.proxy_fix import ProxyFix

from app.deploy_mode import is_web_deployment
from app.i18n import load_translations, t
from app.logging_setup import setup_logging
from app.version import __version__

# Довгоживучий cookie анонімної сесії (Этап 3: без реєстрації/логіну) — рік, як і просив
# власник; саме він, а не Flask-сесія за замовчуванням, переживає закриття браузера.
ANON_SESSION_DURATION = timedelta(days=365)


def _is_production() -> bool:
    """Той самий сигнал, що вже розрізняє SQLite/Postgres у app/db.py::get_database_uri()
    (винесений в app/deploy_mode.py::is_web_deployment(), щоб ним же гейтились і
    desktop-only ендпоінти в app/routes/settings.py/updates.py) — DATABASE_PUBLIC_URL/
    DATABASE_URL заданий лише на веб-деплої (Render), ніколи в локальній розробці.
    Перевикористовуємо його замість заведення окремої змінної оточення (Этап 3: продові
    налаштування — secure cookies, HTTPS, жорсткі перевірки секретів — вмикаються тим самим
    "ми на Render", яким уже керується вибір БД)."""
    return is_web_deployment()


def create_app():
    load_dotenv()  # DATABASE_URL/ENCRYPTION_KEY/SECRET_KEY з .env (Render їх задає як env vars напряму)

    setup_logging()
    logger = logging.getLogger("reels_dashboard")

    is_production = _is_production()

    app = Flask(__name__)
    # Render (як і будь-який PaaS) термінує HTTPS на своєму реверс-проксі й передає застосунку
    # звичайний HTTP — без ProxyFix Flask вважав би кожен запит незахищеним (request.scheme,
    # url_for(_external=True) тощо), хоча в браузері адреса вже https://. x_for/x_proto=1 —
    # довіряємо рівно ОДНОМУ хопу проксі (сам Render), як і рекомендує документація Werkzeug.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or _dev_secret_key_fallback(logger, is_production)
    app.config["REMEMBER_COOKIE_DURATION"] = ANON_SESSION_DURATION
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Secure-прапорець (cookie тільки по HTTPS) — лише на проді: локально (http://127.0.0.1)
    # браузер такий cookie просто відкинув би, і залогінитись під час розробки стало б неможливо.
    app.config["SESSION_COOKIE_SECURE"] = is_production
    app.config["REMEMBER_COOKIE_SECURE"] = is_production
    if is_production:
        app.config["DEBUG"] = False
        if not os.environ.get("ENCRYPTION_KEY"):
            # Падаємо ще на старті процесу (до першого запиту), а не на першому шифруванні
            # секрету десь усередині випадкового HTTP-запиту (app/crypto.py) — незрозуміла
            # помилка в середині обробки запиту гірша за чіткий крах під час деплою.
            raise RuntimeError(
                "ENCRYPTION_KEY не задано в оточенні Render — обов'язково для продакшену. "
                "Згенеруйте: python -c \"from app.crypto import generate_key; print(generate_key())\""
            )

    from app.db import db, init_db

    init_db(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User

        return db.session.get(User, int(user_id))

    from app.routes.home import home_bp
    from app.routes.settings import settings_bp
    from app.routes.metrics import metrics_bp
    from app.routes.stories import stories_bp
    from app.routes.facebook import facebook_bp
    from app.routes.tiktok import tiktok_bp
    from app.routes.analysis import analysis_bp
    from app.routes.hooks import hooks_bp
    from app.routes.generator import generator_bp
    from app.routes.categories import categories_bp
    from app.routes.help import help_bp
    from app.routes.ads import ads_bp
    from app.routes.reports import reports_bp
    from app.routes.onboarding import onboarding_bp
    from app.routes.companion import companion_bp
    from app.routes.ideas import ideas_bp
    from app.routes.signals import signals_bp
    from app.routes.projects import projects_bp

    app.register_blueprint(onboarding_bp, url_prefix="/api/onboarding")
    if not is_production:
        # Самообновлення через встановлювач (app/update_checker.py) — має сенс лише для
        # desktop-збірки з ярликом на диску. На веб-деплої (спільний веб-сервер, анонімний вхід)
        # /api/updates/apply качав би довільний .exe і намагався запустити інсталятор —
        # тому в проді роут навіть не реєструється, а не просто ховається за перевіркою ключа.
        from app.routes.updates import updates_bp

        app.register_blueprint(updates_bp, url_prefix="/api/updates")
    app.register_blueprint(home_bp, url_prefix="/api/home")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(metrics_bp, url_prefix="/api/metrics")
    app.register_blueprint(stories_bp, url_prefix="/api/stories")
    app.register_blueprint(facebook_bp, url_prefix="/api/facebook")
    app.register_blueprint(tiktok_bp, url_prefix="/api/tiktok")
    app.register_blueprint(analysis_bp, url_prefix="/api/analysis")
    app.register_blueprint(hooks_bp, url_prefix="/api/hooks")
    app.register_blueprint(generator_bp, url_prefix="/api/generator")
    app.register_blueprint(categories_bp, url_prefix="/api/categories")
    app.register_blueprint(help_bp, url_prefix="/api/help")
    app.register_blueprint(ads_bp, url_prefix="/api/ads")
    app.register_blueprint(reports_bp, url_prefix="/api/reports")
    app.register_blueprint(companion_bp, url_prefix="/api/companion")
    app.register_blueprint(ideas_bp, url_prefix="/api/ideas")
    app.register_blueprint(signals_bp, url_prefix="/api/signals")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")

    # Анонімна сесія (Этап 3, за рішенням власника): реєстрація/логін прибрані повністю —
    # перший запит будь-якого нового відвідувача (крім статики) мовчки заводить йому User-рядок
    # (app/db_store.py::create_anonymous_user) і залогінює з довгоживучим remember-cookie
    # (ANON_SESSION_DURATION, рік). Ізоляція даних між сесіями лишається такою самою, як була
    # в Этапі 1 (усе в db_store.py прив'язане до user_id) — просто user_id тепер видає не форма
    # входу, а сам браузер через cookie. Ніяких 401/редіректів на /login більше немає:
    # current_user.is_authenticated після цього блоку завжди True.
    @app.before_request
    def ensure_anonymous_session():
        # "health" виключено так само, як "static": UptimeRobot/Render health-check б'ють
        # сюди без кукі кожні кілька хвилин — без цього винятку кожен пінг мовчки заводив би
        # новий рядок у users (create_anonymous_user), засмічуючи БД юзерами, яких ніхто
        # не створював.
        if request.endpoint is None or request.endpoint in ("static", "health"):
            return None
        if not current_user.is_authenticated:
            from app.db_store import create_anonymous_user

            user = create_anonymous_user()
            login_user(user, remember=True, duration=ANON_SESSION_DURATION)
        return None

    @app.route("/health")
    def health():
        # Лёгкий ендпоінт без звернення до БД — для зовнішнього пінгера (UptimeRobot),
        # щоб безкоштовний Render-інстанс не засинав від відсутності трафіку (інакше
        # разом із процесом засинає й фоновий APScheduler — автопродовження IG-токена,
        # денний звіт, авто-синк метрик, див. app/scheduler.py). Свідомо не звертається до
        # Neon — Neon засинає незалежно від Render (власний autosuspend) і прокидається сам
        # на перший реальний SQL-запит (pool_pre_ping=True в app/db.py вже покриває цей
        # випадок), тому пінгувати БД звідси не потрібно.
        return "ok", 200

    @app.route("/")
    def index():
        from app.project_store import get_active_project, load_projects

        return render_template(
            "index.html",
            i18n=load_translations(),
            app_version=__version__,
            projects=load_projects(),
            active_project=get_active_project(),
        )

    @app.errorhandler(Exception)
    def handle_uncaught_exception(e):
        # Без этого любое непойманное исключение при запуске через pythonw.exe (без консоли)
        # просто "тихо" рвёт запрос, и пользователь видит зависшую кнопку без единой подсказки.
        # Логируем полный traceback в data/app.log и отдаём фронту понятный JSON вместо HTML
        # страницы Flask-ошибки (fetch() на фронте ожидает JSON).
        logger.exception("Необработанная ошибка: %s", e)
        return jsonify({"error": t("common.msg.unexpected_error", error=str(e))}), 500

    # RUN_SCHEDULER (Этап 3): за замовчуванням увімкнено — так само, як і завжди (desktop,
    # flask run, один gunicorn-воркер на Render). Явно вимикається (RUN_SCHEDULER=0) лише якщо
    # колись знадобиться кілька gunicorn-воркерів АБО окремий процес-планувальник — інакше
    # кожен воркер підняв би СВІЙ BackgroundScheduler і всі cron/interval job'и дублювалися б
    # (двічі продовжений токен, подвійний денний звіт тощо). Render Start Command навмисно
    # тримає --workers 1, тому дублювання не станеться навіть без цього прапорця — він лише
    # запобіжник на майбутнє масштабування.
    if os.environ.get("RUN_SCHEDULER", "1") != "0":
        from app.scheduler import start_scheduler

        start_scheduler(app)

    return app


def _dev_secret_key_fallback(logger, is_production: bool) -> str:
    if is_production:
        raise RuntimeError(
            "SECRET_KEY не задано в оточенні Render — обов'язково для продакшену (без нього "
            "сесії/remember-cookie небезпечні й не переживуть рестарт процесу). Згенеруйте: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    logger.warning(
        "SECRET_KEY не задано в оточенні — використовую фіксований dev-ключ (сесії НЕ будуть "
        "безпечними/persistent між рестартами процесу). Обов'язково задайте SECRET_KEY у "
        "Render Variables / .env перед реальним використанням."
    )
    return "dev-insecure-secret-key-set-SECRET_KEY-env-var"
