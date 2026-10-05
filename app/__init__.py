import logging
import threading
import time
from datetime import timedelta

from flask import Flask

from . import db, jobs
from .config import Config

_scheduler_started = False


def _scheduler_loop():
    log = logging.getLogger("tj")
    while True:
        try:
            jobs.run_all()
        except Exception:
            log.exception("Scheduler pass failed")
        time.sleep(Config.POLL_MINUTES * 60)


def create_app():
    global _scheduler_started
    logging.basicConfig(level=logging.INFO)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=Config.SECRET_KEY,
        MAX_CONTENT_LENGTH=60 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.PUBLIC_BASE_URL.startswith("https"),
    )
    db.init()

    if Config.DEMO_MODE:
        from .graph import DemoGraph
        from .smartsheet import DemoSmartsheet
        jobs.Services.graph, jobs.Services.sheet = DemoGraph(), DemoSmartsheet()
    else:
        from .graph import GraphClient
        from .smartsheet import SmartsheetClient
        jobs.Services.graph = GraphClient(Config.MS_TENANT_ID, Config.MS_CLIENT_ID,
                                          Config.MS_CLIENT_SECRET, Config.MAILBOX)
        jobs.Services.sheet = SmartsheetClient(Config.SMARTSHEET_TOKEN, Config.SMARTSHEET_SHEET_ID)

    from . import auth, routes
    app.register_blueprint(auth.bp)
    app.register_blueprint(routes.bp)
    auth.require_login(app)

    # One gunicorn worker runs the background checks (see render.yaml).
    if Config.RUN_SCHEDULER and not Config.DEMO_MODE and not _scheduler_started:
        _scheduler_started = True
        threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler").start()
    return app
