import os
from datetime import datetime
from zoneinfo import ZoneInfo


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


class Config:
    SECRET_KEY = env("SECRET_KEY", "dev-only-change-me")
    DEMO_MODE = env("DEMO_MODE", "0") == "1"
    DATA_DIR = env("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    DB_PATH = env("DB_PATH") or os.path.join(DATA_DIR, "tj_scheduler.db")
    UPLOAD_DIR = env("UPLOAD_DIR") or os.path.join(DATA_DIR, "uploads")
    SITE_TZ = ZoneInfo(env("SITE_TZ", "America/Denver"))

    # Microsoft 365 (one Entra app registration used for both mail and sign-in)
    MS_TENANT_ID = env("MS_TENANT_ID")
    MS_CLIENT_ID = env("MS_CLIENT_ID")
    MS_CLIENT_SECRET = env("MS_CLIENT_SECRET")
    MAILBOX = env("MAILBOX")                        # scheduling mailbox address
    ALLOWED_USER_EMAIL = (env("ALLOWED_USER_EMAIL") or "").lower()
    PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:5000")

    # Smartsheet
    SMARTSHEET_TOKEN = env("SMARTSHEET_TOKEN")
    SMARTSHEET_SHEET_ID = env("SMARTSHEET_SHEET_ID", "3871787909599108")

    RUN_SCHEDULER = env("RUN_SCHEDULER", "1") == "1"
    POLL_MINUTES = int(env("POLL_MINUTES", "10"))
    DEMO_NOW = env("DEMO_NOW")  # e.g. 2026-10-05T10:00 for screenshots


def now():
    """Current time in the site's time zone (naive local)."""
    if Config.DEMO_NOW:
        return datetime.fromisoformat(Config.DEMO_NOW)
    return datetime.now(Config.SITE_TZ).replace(tzinfo=None)


# Editable on the Settings page. Values are stored as strings.
DEFAULT_SETTINGS = {
    "reschedule_lead_hours": "48",     # send reschedule request this many hours before the appointment
    "no_answer_alert_hours": "24",     # alert if the DC hasn't confirmed by this many hours out
    "reschedule_min_gap_days": "2",    # new date must be at least this many days after the current one
    "reschedule_max_attempts": "3",    # after this many reschedules on one PO, alert instead
    "request_lead_days": "3",          # (no longer used; replaced by ship_prep_days + transit)
    "ship_prep_days": "0",             # days before a load can leave, added before transit
    "appointed_status": "APPOINT",     # STATUS written to Smartsheet when an appointment is set
    "request_default_time": "08:00",
    "auto_send_requests": "0",         # 0 = Cody reviews each request before it goes out
    "request_hold_minutes": "30",      # if auto-send is on, wait this long before sending a new request
    "paused": "0",                     # 1 = no automatic emails to DCs
    "review_reschedules": "1",         # 1 = reschedules wait for Cody's OK
    "daily_auto_limit": "10",          # more automatic emails than this in a day pauses the site
    "queue_horizon_hours": "72",       # how far ahead the upcoming list looks
    "docs_window_days": "2",           # Documents page: "Shipping soon" covers this many days ahead
    "reminder_hour": "8",              # daily reminder email hour (site time)
    "vendor": "SWEET CANDY",
    "carrier": "BROCK",
    "origin": "SALT LAKE CITY, UT",
    "contact": "APRIL",
    "signature": "Thank you,\nApril",
}
