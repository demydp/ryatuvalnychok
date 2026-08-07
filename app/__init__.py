import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager, current_user, login_user

from app.i18n import load_translations, t
from app.logging_setup import setup_logging
from app.version import __version__

# Довгоживучий cookie анонімної сесії (Этап 3: без реєстрації/логіну) — рік, як і просив
# власник; саме він, а не Flask-сесія за замовчуванням, переживає закриття браузера.
ANON_SESSION_DURATION = timedelta(days=365)


def create_app():
    load_dotenv()  # DATABASE_PUBLIC_URL/ENCRYPTION_KEY/SECRET_KEY з .env (Railway їх задає як env vars напряму)

    setup_logging()
    logger = logging.getLogger("reels_dashboard")

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or _dev_secret_key_fallback(logger)
    app.config["REMEMBER_COOKIE_DURATION"] = ANON_SESSION_DURATION
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True

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
    from app.routes.analysis import analysis_bp
    from app.routes.hooks import hooks_bp
    from app.routes.generator import generator_bp
    from app.routes.categories import categories_bp
    from app.routes.help import help_bp
    from app.routes.ads import ads_bp
    from app.routes.reports import reports_bp
    from app.routes.onboarding import onboarding_bp
    from app.routes.updates import updates_bp
    from app.routes.companion import companion_bp
    from app.routes.ideas import ideas_bp
    from app.routes.signals import signals_bp
    from app.routes.projects import projects_bp

    app.register_blueprint(onboarding_bp, url_prefix="/api/onboarding")
    app.register_blueprint(updates_bp, url_prefix="/api/updates")
    app.register_blueprint(home_bp, url_prefix="/api/home")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(metrics_bp, url_prefix="/api/metrics")
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
        if request.endpoint is None or request.endpoint == "static":
            return None
        if not current_user.is_authenticated:
            from app.db_store import create_anonymous_user

            user = create_anonymous_user()
            login_user(user, remember=True, duration=ANON_SESSION_DURATION)
        return None

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

    from app.scheduler import start_scheduler

    start_scheduler(app)

    return app


def _dev_secret_key_fallback(logger) -> str:
    logger.warning(
        "SECRET_KEY не задано в оточенні — використовую фіксований dev-ключ (сесії НЕ будуть "
        "безпечними/persistent між рестартами процесу). Обов'язково задайте SECRET_KEY у "
        "Railway variables / .env перед реальним використанням."
    )
    return "dev-insecure-secret-key-set-SECRET_KEY-env-var"
