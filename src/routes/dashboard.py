"""dashboard-route: overzicht van alle projecten."""

from flask import Blueprint, render_template
from flask_login import login_required

from src.state import get_session
from src.models import Project

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    """Toon het dashboard met een lijst van alle projecten."""
    with get_session() as session:
        projects = session.query(Project).order_by(Project.created_at.desc()).all()
    return render_template("dashboard.html", projects=projects)
