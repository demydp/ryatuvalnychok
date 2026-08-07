"""
Реєстрація/вхід/вихід (Этап 1 веб-версії) — Flask-Login. Звичайні HTML-форми (без fetch/JS) —
ці дві сторінки відкриваються один раз до логіну, ускладнювати їх окремим auth.js сенсу нема.

Чесність/безпека: паролі ніколи не логуються (Werkzeug access-log пише лише метод+шлях+статус,
не тіло форми); email не логується в error-шляхах цього файлу. Хешування — werkzeug.security
(той самий пакет, що вже тягне Flask), шифрування секретів у БД — окремо, див. app/crypto.py."""
from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.db_store import create_user, get_user_by_email
from app.i18n import load_translations, t

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 8


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if not email or "@" not in email:
            error = t("auth.msg.invalid_email")
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = t("auth.msg.password_too_short")
        elif password != password2:
            error = t("auth.msg.passwords_dont_match")
        elif get_user_by_email(email):
            error = t("auth.msg.email_taken")
        else:
            user = create_user(email, password)
            login_user(user)
            return redirect(url_for("index"))

    return render_template("register.html", i18n=load_translations(), error=error, email=email)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        user = get_user_by_email(email)
        if not user or not user.check_password(password):
            error = t("auth.msg.invalid_credentials")
        else:
            login_user(user)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("index"))

    return render_template("login.html", i18n=load_translations(), error=error, email=email)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
