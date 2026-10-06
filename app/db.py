"""SQLite storage. On Render, DB_PATH points at the persistent disk."""
import os
import sqlite3
import threading

from .config import Config, DEFAULT_SETTINGS, now

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS pos (
    id INTEGER PRIMARY KEY,
    po_number TEXT UNIQUE NOT NULL,      -- as in Smartsheet, e.g. 0158142470
    order_no TEXT,
    dc_code TEXT,
    sheet_row_id TEXT,
    cases INTEGER,
    pallets INTEGER,
    ship_date TEXT,
    del_date TEXT,
    act_ship TEXT,
    sheet_status TEXT,
    state TEXT NOT NULL DEFAULT 'pending_request',
        -- pending_request | requested | booked | reschedule_requested | shipped | closed
    attention TEXT,                      -- non-null = shows in "Needs you"
    appt_date TEXT,
    appt_time TEXT,
    conf_no TEXT,
    keep INTEGER NOT NULL DEFAULT 0,
    reschedule_count INTEGER NOT NULL DEFAULT 0,
    requested_date TEXT,
    requested_time TEXT,
    request_sent_at TEXT,
    conversation_id TEXT,
    last_message_id TEXT,
    doc_status TEXT NOT NULL DEFAULT 'missing',   -- missing | sent | sent_manual | sent_detected | failed
    doc_filename TEXT,
    doc_sent_at TEXT,
    doc_error TEXT,
    no_answer_alerted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    po_id INTEGER,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,                 -- 'Cody' or 'Site'
    action TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id TEXT PRIMARY KEY,
    po_id INTEGER,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS unmatched_emails (
    id INTEGER PRIMARY KEY,
    message_id TEXT UNIQUE,
    sender TEXT,
    subject TEXT,
    received TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS location_overrides (
    key TEXT PRIMARY KEY,
    days TEXT,                           -- comma list of weekday numbers, e.g. "0,3,4"
    email TEXT
);
CREATE TABLE IF NOT EXISTS code_overrides (
    code TEXT PRIMARY KEY,
    location_key TEXT,
    bc_name TEXT,
    load_type TEXT,
    removed INTEGER NOT NULL DEFAULT 0
);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(os.path.abspath(Config.DB_PATH)), exist_ok=True)
        c = sqlite3.connect(Config.DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


NEW_COLUMNS = {"reschedule_override": "TEXT", "auto_send_at": "TEXT"}


def init():
    c = conn()
    c.executescript(SCHEMA)
    have = {r["name"] for r in c.execute("PRAGMA table_info(pos)")}
    for col, kind in NEW_COLUMNS.items():
        if col not in have:
            c.execute(f"ALTER TABLE pos ADD COLUMN {col} {kind}")
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    c.commit()
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)


def q(sql, args=()):
    return conn().execute(sql, args).fetchall()


def one(sql, args=()):
    return conn().execute(sql, args).fetchone()


def run(sql, args=()):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def stamp():
    return now().isoformat(timespec="seconds")


def update_po(po_id, **fields):
    fields["updated_at"] = stamp()
    cols = ", ".join(f"{k} = ?" for k in fields)
    run(f"UPDATE pos SET {cols} WHERE id = ?", (*fields.values(), po_id))


def log(po_id, action, detail=None, actor="Site"):
    run("INSERT INTO activity(po_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
        (po_id, stamp(), actor, action, detail))


def settings():
    return {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}


def setting_int(name):
    return int(settings().get(name, DEFAULT_SETTINGS[name]))


def set_setting(key, value):
    run("INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def meta_get(key):
    r = one("SELECT value FROM meta WHERE key = ?", (key,))
    return r["value"] if r else None


def meta_set(key, value):
    run("INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
