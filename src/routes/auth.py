"""authenticatie-routes: /login en /logout."""

import hmac
import os

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user
from loguru import logger

from src.app_user import SingleUser

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Toon het loginformulier of verwerk de loginpoging."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        expected_user = os.environ.get("DM_USER", "")
        expected_password = os.environ.get("DM_PASSWORD", "")

        user_ok = hmac.compare_digest(username, expected_user)
        pass_ok = bool(expected_password) and hmac.compare_digest(password, expected_password)

        if user_ok and pass_ok:
            login_user(SingleUser())
            logger.info(f"gebruiker '{username}' ingelogd")
            return redirect(url_for("dashboard.index"))

        logger.warning(f"mislukte loginpoging voor gebruiker '{username}'")
        return render_template("login.html", error="ongeldige gebruikersnaam of wachtwoord"), 401

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    """Log de huidige gebruiker uit."""
    logger.info("gebruiker uitgelogd")
    logout_user()
    return redirect(url_for("auth.login"))
