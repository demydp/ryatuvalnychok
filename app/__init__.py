import logging

from flask import Flask, jsonify, render_template

from app.config_store import load_config
from app.i18n import load_translations, t
from app.logging_setup import setup_logging
from app.project_store import ensure_migrated, get_active_project, load_projects
from app.version import __version__


def create_app():
    setup_logging()
    logger = logging.getLogger("reels_dashboard")

    ensure_migrated()

    app = Flask(__name__)

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

    @app.route("/")
    def index():
        cfg = load_config()
        if not cfg.get("setup_completed"):
            return render_template("onboarding.html", i18n=load_translations())
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
