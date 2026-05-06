"""flask-applicatie voor denkmachine – initialisatie, logging en registratie van routes."""

import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, request
from flask_login import LoginManager, current_user
from loguru import logger

load_dotenv()

# loguru instellen voor bestandsrotatie en stdout
_BASE_DIR = Path(__file__).parent.parent
_LOGS_DIR = _BASE_DIR / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module} | {message}",
)
logger.add(
    str(_LOGS_DIR / "dm.log"),
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module} | {message}",
)

# database initialiseren
from src.state import init_db  # noqa: E402

init_db()

# flask-app aanmaken
import os  # noqa: E402

app = Flask(
    __name__,
    template_folder=str(_BASE_DIR / "templates"),
    static_folder=str(_BASE_DIR / "static"),
)
app.secret_key = os.environ.get("DM_SECRET_KEY", "dev-secret-key-vervang-mij")

# flask-login instellen
login_manager = LoginManager(app)
login_manager.login_view = "auth.login"

from src.app_user import SingleUser  # noqa: E402


@login_manager.user_loader
def load_user(user_id: str):
    """Laad de gebruiker op basis van het id uit de sessie-cookie."""
    if user_id == SingleUser.id:
        return SingleUser()
    return None


# request-logging via before/after hooks
@app.before_request
def before_request() -> None:
    """Sla het starttijdstip en een uniek request-id op voor logging."""
    g.request_id = str(uuid.uuid4())
    g.start_time = time.time()


@app.after_request
def after_request(response):
    """Log de requestgegevens na elke aanvraag."""
    duration_ms = int((time.time() - g.start_time) * 1000)
    user = current_user.get_id() if current_user.is_authenticated else "anonymous"
    logger.info(
        f"request_id={g.request_id} method={request.method} path={request.path} "
        f"user={user} status={response.status_code} duration_ms={duration_ms}"
    )
    return response


# blueprints registreren
from src.routes.auth import auth_bp  # noqa: E402
from src.routes.dashboard import dashboard_bp  # noqa: E402
from src.routes.plan import plan_bp  # noqa: E402
from src.routes.progress import progress_bp  # noqa: E402
from src.routes.projects import projects_bp  # noqa: E402
from src.routes.upload import upload_bp  # noqa: E402

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(progress_bp)

logger.info("denkmachine opgestart")
