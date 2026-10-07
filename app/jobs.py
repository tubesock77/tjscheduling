"""The workflow. Used by the background scheduler and by page actions."""
import logging
import os
from datetime import date, datetime, timedelta, timezone

from . import db, dc_lookup, emails, parser, rules
from .config import Config, now

log = logging.getLogger("tj")

OPEN_STATES = ("pending_request", "requested", "booked", "reschedule_requested")


class Services:
    """Holds the Graph + Smartsheet clients (real or demo)."""
    graph = None
    sheet = None


def _po(po_id):
    return db.one("SELECT * FROM pos WHERE id = ?", (po_id,))


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _iso(v):
    return str(v)[:10] if v else None


def _hhmm(v):
    """'8:00', '08:00', '0800', '8:00 AM' -> '08:00' (None if unreadable)."""
    if not v:
        return None
    t = str(v).strip().lower().replace(".", "")
    pm, am = t.endswith("pm"), t.endswith("am")
    t = t.replace("am", "").replace("pm", "").strip()
    if ":" in t:
        hh, mm = t.split(":")[:2]
    elif t.isdigit() and len(t) in (3, 4):
        hh, mm = t[:-2], t[-2:]
    else:
        return None
    try:
        h, m = int(hh), int(mm[:2])
    except ValueError:
        return None
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}" if h < 24 and m < 60 else None


def _apply_sheet_appointment(po, r):
    """If Cody changed APT DATE / APT TIME / CONF# in Smartsheet, adopt it."""
    if po["state"] not in OPEN_STATES:
        return
    sheet_date = _iso(r.get("APT DATE"))
    if not sheet_date:
        return
    sheet_time = _hhmm(r.get("APT TIME")) or po["appt_time"] or "08:00"
    sheet_conf = str(r.get("CONF#")).strip() if r.get("CONF#") else po["conf_no"]
    if (sheet_date, sheet_time, sheet_conf) == (po["appt_date"], po["appt_time"], po["conf_no"]):
        return  # same as ours (includes our own write-backs)
    before = f"{po['appt_date']} {po['appt_time']}" if po["appt_date"] else "none"
    db.update_po(po["id"], appt_date=sheet_date, appt_time=sheet_time, conf_no=sheet_conf,
                 state="booked", attention=None, no_answer_alerted=0,
                 reschedule_override=None, auto_send_at=None)
    db.log(po["id"], "Appointment changed in Smartsheet",
           f"{before} to {sheet_date} {sheet_time}" + (f", conf {sheet_conf}" if sheet_conf else ""), "Cody")


# ---------------------------------------------------------------- Smartsheet
def sync_smartsheet():
    """Pick up STATUS = APT. REQ. rows and keep known POs current."""
    rows = Services.sheet.fetch_rows()
    added = 0
    for r in rows:
        po_number = str(r.get("PO #") or "").strip()
        if po_number.endswith(".0"):
            po_number = po_number[:-2]
        if not po_number:
            continue  # group/header rows
        status = (r.get("STATUS") or "").strip()
        fields = dict(order_no=r.get("ORDER NO."), product=(str(r.get("PRODUCT")).strip() if r.get("PRODUCT") else None), dc_code=dc_lookup.normalize_code(r.get("DC #")),
                      sheet_row_id=r["_row_id"], cases=_num(r.get("CS")), pallets=_num(r.get("PLTS")),
                      ship_date=_iso(r.get("SHIP DATE")), del_date=_iso(r.get("DEL DATE")),
                      act_ship=_iso(r.get("ACT SHIP")), sheet_status=status)
        existing = db.one("SELECT * FROM pos WHERE po_number = ?", (po_number,))
        if existing is None:
            if status != "APT. REQ.":
                continue  # only APT. REQ. rows start tracking
            po_id = db.run("INSERT INTO pos(po_number, state, created_at, updated_at) VALUES (?,?,?,?)",
                           (po_number, "pending_request", db.stamp(), db.stamp()))
            db.update_po(po_id, **fields)
            added += 1
            db.log(po_id, "Picked up from Smartsheet", "STATUS is APT. REQ.")
            prepare_request(po_id)
        else:
            db.update_po(existing["id"], **fields)
            _apply_sheet_appointment(existing, r)
            if status in ("SHIPPED", "ARCHIVE") and existing["state"] in OPEN_STATES:
                db.update_po(existing["id"], state="shipped", attention=None)
                db.log(existing["id"], "Marked shipped", f"Smartsheet STATUS is {status}")
    db.meta_set("last_sync", db.stamp())
    return added


def earliest_for(po, dc):
    """Soonest the truck could reach this DC."""
    ship = date.fromisoformat(po["ship_date"]) if po["ship_date"] else None
    return rules.earliest_arrival(now().date(), ship, int(db.settings()["ship_prep_days"]), dc["transit"])


def prepare_request(po_id):
    """Fill default requested date/time and flag missing DC info."""
    po = _po(po_id)
    dc = dc_lookup.resolve(po["dc_code"])
    if dc is None:
        reason = ("No DC # on the Smartsheet row" if not po["dc_code"]
                  else f"DC # {po['dc_code']} isn't in the location list")
        db.update_po(po_id, attention=reason)
        return
    s = db.settings()
    if not po["requested_date"]:
        d = rules.default_request_date(earliest_for(po, dc), dc["days"])
        db.update_po(po_id, requested_date=d.isoformat(), requested_time=s["request_default_time"])
    if s["auto_send_requests"] == "1":
        hold = int(s["request_hold_minutes"])
        db.update_po(po_id, auto_send_at=(now() + timedelta(minutes=hold)).isoformat(timespec="seconds"))


def send_request(po_id, actor="Site"):
    po = _po(po_id)
    dc = dc_lookup.resolve(po["dc_code"])
    if dc is None or not po["requested_date"]:
        raise ValueError("This PO needs a known DC # and a requested date before it can be sent")
    s = db.settings()
    msg_id, conv_id = Services.graph.send_new(dc["email"], emails.request_subject(po, s),
                                              emails.request_body(po, dc, s))
    db.update_po(po_id, state="requested", conversation_id=conv_id, last_message_id=msg_id,
                 request_sent_at=db.stamp(), attention=None, no_answer_alerted=0, auto_send_at=None)
    db.log(po_id, "Appointment request sent",
           f"To {dc['email']} for {po['requested_date']} {po['requested_time']}", actor)


# ---------------------------------------------------------------- Inbox
def _match_po(msg, text):
    po = db.one("SELECT * FROM pos WHERE conversation_id = ?", (msg.get("conversationId"),))
    if po:
        return po
    found = parser.find_po_numbers((msg.get("subject") or "") + " " + text)
    if len(found) == 1:
        return db.one("SELECT * FROM pos WHERE po_number = ?", (found[0],))
    return None


DC_DOMAIN = "@wcdinc.net"


def process_inbox():
    """Only DC emails (@wcdinc.net) or replies on threads the site started.

    Everything else in April's inbox is left alone: not read, not marked, not listed.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for msg in Services.graph.unread_inbox(since):
        mid = msg["id"]
        if db.one("SELECT 1 FROM processed_messages WHERE message_id = ?", (mid,)):
            continue
        sender = ((msg.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
        known_thread = db.one("SELECT 1 FROM pos WHERE conversation_id = ?", (msg.get("conversationId"),))
        if not sender.endswith(DC_DOMAIN) and not known_thread:
            continue  # not a DC email; don't touch it
        text = parser.html_to_text((msg.get("uniqueBody") or {}).get("content", ""))
        po = _match_po(msg, text)
        if po is None:
            db.run("INSERT OR IGNORE INTO unmatched_emails(message_id, sender, subject, received) "
                   "VALUES (?,?,?,?)", (mid, sender, msg.get("subject"), msg.get("receivedDateTime")))
            db.run("INSERT INTO processed_messages VALUES (?,?,?)", (mid, None, db.stamp()))
            continue  # left unread so it stands out in Outlook
        handle_reply(po, mid, msg.get("conversationId"), text, sender)
        db.run("INSERT INTO processed_messages VALUES (?,?,?)", (mid, po["id"], db.stamp()))
        Services.graph.mark_read(mid)


def handle_reply(po, message_id, conversation_id, text, sender):
    db.update_po(po["id"], last_message_id=message_id,
                 conversation_id=po["conversation_id"] or conversation_id)
    parsed = parser.parse_reply(text)
    db.log(po["id"], "Reply received", f"From {sender}")
    if parsed["confident"]:
        confirm_appointment(po["id"], parsed["date"], parsed["time"] or po["appt_time"] or "08:00",
                            parsed["conf_no"] or po["conf_no"], actor="Site")
    elif parsed["portal"]:
        db.update_po(po["id"], attention="DC asked to use the reschedule portal")
    else:
        db.update_po(po["id"], attention="DC replied but the appointment couldn't be read. Enter it by hand.")


def confirm_appointment(po_id, appt_date, appt_time, conf_no, actor="Cody"):
    po = _po(po_id)
    changed = po["appt_date"] is not None and po["appt_date"] != appt_date
    db.update_po(po_id, appt_date=appt_date, appt_time=appt_time, conf_no=conf_no,
                 state="booked", attention=None, no_answer_alerted=0)
    db.log(po_id, "Appointment rescheduled" if changed else "Appointment set",
           f"{appt_date} {appt_time}" + (f", conf {conf_no}" if conf_no else ""), actor)
    write_back(po_id)


def write_back(po_id):
    po = _po(po_id)
    if not po["sheet_row_id"]:
        return
    status = db.settings().get("appointed_status") or "APPOINT"
    values = {"APT DATE": po["appt_date"], "APT TIME": po["appt_time"], "STATUS": status}
    if po["conf_no"]:
        values["CONF#"] = po["conf_no"]
    try:
        Services.sheet.update_row(po["sheet_row_id"], values)
        db.log(po_id, "Smartsheet updated", f"APT DATE, APT TIME, CONF#, STATUS = {status}")
    except Exception as e:  # keep going; show it to Cody
        db.update_po(po_id, attention=f"Couldn't update Smartsheet: {e}")


# ---------------------------------------------------------------- Safety
AUTO_ACTIONS = ("Appointment request sent", "Reschedule requested")


def is_paused():
    return db.settings().get("paused") == "1"


def pause(reason, actor="Site"):
    db.set_setting("paused", "1")
    db.meta_set("pause_reason", reason)
    db.log(None, "Automatic emails paused", reason, actor)


def resume(actor="Cody"):
    db.set_setting("paused", "0")
    db.meta_set("pause_reason", "")
    db.log(None, "Automatic emails resumed", None, actor)


def auto_sends_today():
    start = now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    marks = ",".join("?" * len(AUTO_ACTIONS))
    return db.one(f"SELECT COUNT(*) FROM activity WHERE actor = 'Site' AND ts >= ? AND action IN ({marks})",
                  (start, *AUTO_ACTIONS))[0]


def can_auto_send():
    """False if paused or the daily limit is reached (which also pauses)."""
    if is_paused():
        return False
    limit = int(db.settings()["daily_auto_limit"])
    if auto_sends_today() >= limit:
        pause(f"Hit the daily limit of {limit} automatic emails. Check Activity, then resume.")
        return False
    return True


def send_due_requests():
    if db.settings()["auto_send_requests"] != "1":
        return
    for po in db.q("SELECT * FROM pos WHERE state = 'pending_request' AND attention IS NULL "
                   "AND auto_send_at IS NOT NULL AND auto_send_at <= ?", (now().isoformat(timespec="seconds"),)):
        if not can_auto_send():
            return
        send_request(po["id"])


def _proposed_date(po, dc, gap):
    if po["reschedule_override"]:
        return po["reschedule_override"]
    return rules.reschedule_target(date.fromisoformat(po["appt_date"]), dc["days"], gap,
                                   earliest_for(po, dc)).isoformat()


def upcoming():
    """Automatic emails the site plans to send within the horizon, soonest first."""
    s, t = db.settings(), now()
    lead, gap = int(s["reschedule_lead_hours"]), int(s["reschedule_min_gap_days"])
    horizon, max_attempts = int(s["queue_horizon_hours"]), int(s["reschedule_max_attempts"])
    paused, review = s["paused"] == "1", s["review_reschedules"] == "1"
    items = []
    for po in db.q("SELECT * FROM pos WHERE state = 'booked' AND keep = 0 AND attention IS NULL"):
        dc = dc_lookup.resolve(po["dc_code"])
        appt = rules.appt_datetime(po["appt_date"], po["appt_time"])
        if dc is None or appt is None or appt <= t or po["reschedule_count"] >= max_attempts:
            continue
        send_at = appt - timedelta(hours=lead)
        if send_at > t + timedelta(hours=horizon):
            continue
        due = send_at <= t
        status = ("paused" if paused and due else "review" if review and due
                  else "due" if due else "scheduled")
        items.append({"po": po, "dc": dc, "kind": "Reschedule", "send_at": send_at,
                      "secs": max(0, int((send_at - t).total_seconds())), "status": status,
                      "new_date": _proposed_date(po, dc, gap)})
    if s["auto_send_requests"] == "1":
        for po in db.q("SELECT * FROM pos WHERE state = 'pending_request' AND attention IS NULL "
                       "AND auto_send_at IS NOT NULL"):
            send_at = datetime.fromisoformat(po["auto_send_at"])
            due = send_at <= t
            items.append({"po": po, "dc": dc_lookup.resolve(po["dc_code"]), "kind": "Request",
                          "send_at": send_at, "secs": max(0, int((send_at - t).total_seconds())),
                          "status": "paused" if paused and due else "due" if due else "scheduled",
                          "new_date": po["requested_date"]})
    items.sort(key=lambda i: i["send_at"])
    return items


# ---------------------------------------------------------------- Reschedules
def check_reschedules():
    s = db.settings()
    lead, alert_h = int(s["reschedule_lead_hours"]), int(s["no_answer_alert_hours"])
    max_attempts, gap = int(s["reschedule_max_attempts"]), int(s["reschedule_min_gap_days"])
    t = now()
    for po in db.q("SELECT * FROM pos WHERE state IN ('booked','requested','reschedule_requested')"):
        if rules.needs_reschedule(po, t, lead):
            if po["reschedule_count"] >= max_attempts:
                if not po["attention"]:
                    db.update_po(po["id"], attention=f"Rescheduled {po['reschedule_count']} times already. "
                                                     "Keep it or move it by hand.")
                continue
            if po["attention"]:
                continue  # waiting on Cody
            if s["review_reschedules"] == "1":
                continue  # shows as "Waiting for your OK" in the upcoming list
            if not can_auto_send():
                continue
            request_reschedule(po["id"])
        elif po["state"] in ("requested", "reschedule_requested") and not po["no_answer_alerted"]:
            h = rules.hours_until(po["appt_date"], po["appt_time"], t)
            if h is not None and 0 < h <= alert_h:
                db.update_po(po["id"], no_answer_alerted=1,
                             attention=f"No answer from the DC and the appointment is {int(h)} hours out")


def request_reschedule(po_id, actor="Site"):
    po = _po(po_id)
    dc = dc_lookup.resolve(po["dc_code"])
    if dc is None:
        db.update_po(po_id, attention="Can't reschedule: DC # not recognized")
        return
    s = db.settings()
    target = date.fromisoformat(_proposed_date(po, dc, int(s["reschedule_min_gap_days"])))
    reply_to = _thread_message(po)
    if not reply_to:
        db.update_po(po_id, attention="Couldn't find the email thread to reply on")
        return
    Services.graph.reply_all(reply_to, emails.reschedule_body(po, target.isoformat(), s))
    db.update_po(po_id, state="reschedule_requested", requested_date=target.isoformat(),
                 reschedule_count=po["reschedule_count"] + 1, no_answer_alerted=0, reschedule_override=None)
    db.log(po_id, "Reschedule requested", f"Asked to move {po['appt_date']} to {target.isoformat()}", actor)


def set_keep(po_id, keep, actor="Cody"):
    db.update_po(po_id, keep=1 if keep else 0)
    db.log(po_id, "Marked keep" if keep else "Keep removed", None, actor)


# ---------------------------------------------------------------- Documents
def _thread_message(po):
    """Latest message on the PO's thread, searching by PO number as a fallback."""
    g = Services.graph
    if po["conversation_id"]:
        latest = g.latest_in_conversation(po["conversation_id"])
        if latest:
            return latest
    if po["last_message_id"]:
        return po["last_message_id"]
    hits = g.search_po(emails.display_po(po["po_number"]))
    convs = {h["conversationId"] for h in hits}
    if len(convs) == 1:
        db.update_po(po["id"], conversation_id=hits[0]["conversationId"])
        return hits[0]["id"]
    return None


def send_document(po_id, filename, data, actor="Cody"):
    po = _po(po_id)
    safe = f"PO{emails.display_po(po['po_number'])}_BOL_Bioterrorism.pdf"
    path = os.path.join(Config.UPLOAD_DIR, f"{po['po_number']}_{int(now().timestamp())}.pdf")
    with open(path, "wb") as f:
        f.write(data)
    db.update_po(po_id, doc_path=path)
    if not data.startswith(b"%PDF"):
        db.update_po(po_id, doc_status="failed", doc_filename=filename,
                     doc_error="That file isn't a readable PDF. Open it on your computer to check, then upload again.")
        db.log(po_id, "Document not sent", "File isn't a valid PDF", actor)
        return False
    reply_to = _thread_message(po)
    if not reply_to:
        db.update_po(po_id, doc_status="failed", doc_filename=filename,
                     doc_error="No email thread found for this PO")
        db.log(po_id, "Document not sent", "No email thread found", actor)
        return False
    try:
        Services.graph.reply_all(reply_to, emails.document_body(po, db.settings()), (safe, data))
    except Exception as e:
        db.update_po(po_id, doc_status="failed", doc_filename=filename, doc_error=str(e)[:300])
        db.log(po_id, "Document not sent", str(e)[:300], actor)
        return False
    db.update_po(po_id, doc_status="sent", doc_filename=filename, doc_sent_at=db.stamp(), doc_error=None)
    db.log(po_id, "Document sent", f"{filename} ({len(data):,} bytes, checked against Outlook's copy) "
           "replied on the appointment thread", actor)
    return True


def mark_doc_manual(po_id, undo=False, actor="Cody"):
    if undo:
        db.update_po(po_id, doc_status="missing", doc_sent_at=None)
        db.log(po_id, "Undid sent outside site", None, actor)
    else:
        db.update_po(po_id, doc_status="sent_manual", doc_sent_at=db.stamp(), doc_error=None)
        db.log(po_id, "Marked document sent outside site", None, actor)


def process_sent():
    """Spot PDFs Cody sent on a PO thread from the scheduling mailbox."""
    since = db.meta_get("sent_check") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    db.meta_set("sent_check", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for m in Services.graph.sent_since(since):
        if not m.get("hasAttachments"):
            continue
        po = db.one("SELECT * FROM pos WHERE conversation_id = ? AND doc_status IN ('missing','failed')",
                    (m.get("conversationId"),))
        if po and any(n.lower().endswith(".pdf") for n in Services.graph.attachment_names(m["id"])):
            db.update_po(po["id"], doc_status="sent_detected", doc_sent_at=db.stamp(), doc_error=None)
            db.log(po["id"], "Document detected", "PDF sent on the thread from the mailbox")


# ---------------------------------------------------------------- Reminders
def missing_docs():
    return db.q("SELECT * FROM pos WHERE doc_status IN ('missing','failed') "
                "AND (state = 'shipped' OR act_ship IS NOT NULL) ORDER BY act_ship")


def maybe_send_reminder():
    s, t = db.settings(), now()
    if t.hour < int(s["reminder_hour"]) or db.meta_get("last_reminder") == t.date().isoformat():
        return
    docs = missing_docs()
    attention = db.q("SELECT * FROM pos WHERE attention IS NOT NULL AND state != 'closed'")
    db.meta_set("last_reminder", t.date().isoformat())
    if not docs and not attention or not Config.ALLOWED_USER_EMAIL:
        return
    Services.graph.send_new(Config.ALLOWED_USER_EMAIL, "TJ scheduling: items that need you",
                            emails.reminder_body(docs, attention, Config.PUBLIC_BASE_URL))


def run_all():
    failed = False
    for job in (sync_smartsheet, process_inbox, process_sent, send_due_requests, check_reschedules,
                maybe_send_reminder):
        try:
            job()
        except Exception as e:
            failed = True
            log.exception("Job %s failed", job.__name__)
            msg = f"{job.__name__}: {e}"[:300]
            if db.meta_get("last_error") != msg:
                db.meta_set("last_error", msg)
                db.log(None, "Background job failed", msg)
    if not failed and db.meta_get("last_error"):
        db.meta_set("last_error", "")
        db.log(None, "Background checks working again", None)
