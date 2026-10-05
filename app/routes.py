from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from . import db, dc_lookup, jobs, rules
from .config import DEFAULT_SETTINGS, now
from .emails import display_po

bp = Blueprint("main", __name__)
ACTOR = "Cody"


def view(po):
    """Row -> dict with display helpers."""
    d = dict(po)
    d["dc"] = dc_lookup.resolve(po["dc_code"])
    d["po_display"] = display_po(po["po_number"])
    d["hours"] = rules.hours_until(po["appt_date"], po["appt_time"], now())
    return d


def _back(default="main.appointments"):
    return redirect(request.form.get("next") or url_for(default))


@bp.app_template_filter("day")
def fmt_day(iso):
    if not iso:
        return ""
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.strftime('%a %b')} {d.day}"


@bp.app_template_filter("stamp")
def fmt_stamp(iso):
    if not iso:
        return ""
    s = str(iso)
    d = date.fromisoformat(s[:10])
    t = s[11:16]
    if t:
        hh, mm = int(t[:2]), t[3:]
        t = f"{(hh % 12) or 12}:{mm} {'pm' if hh >= 12 else 'am'}"
    return f"{d.strftime('%b')} {d.day} {t}".strip()


@bp.app_template_filter("countdown")
def fmt_countdown(hours):
    if hours is None:
        return ""
    if hours < 0:
        return "Passed"
    if hours < 48:
        return f"{int(hours)} hrs"
    return f"{hours / 24:.1f} days"


@bp.app_context_processor
def nav_counts():
    try:
        attention = db.one("SELECT COUNT(*) FROM pos WHERE attention IS NOT NULL AND state != 'closed'")[0]
        attention += db.one("SELECT COUNT(*) FROM unmatched_emails WHERE dismissed = 0")[0]
        missing = len(jobs.missing_docs())
    except Exception:
        attention = missing = 0
    return {"nav": {"attention": attention, "missing": missing}}


@bp.route("/healthz")
def healthz():
    return "ok"


@bp.route("/")
def appointments():
    s = db.settings()
    lead = int(s["reschedule_lead_hours"])
    attention = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE attention IS NOT NULL AND state NOT IN ('closed') ORDER BY updated_at DESC")]
    unmatched = db.q("SELECT * FROM unmatched_emails WHERE dismissed = 0 ORDER BY received DESC")
    pending = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE state = 'pending_request' AND attention IS NULL ORDER BY ship_date")]
    waiting = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE state IN ('requested','reschedule_requested') AND attention IS NULL "
        "ORDER BY request_sent_at")]
    booked = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE state = 'booked' AND attention IS NULL ORDER BY appt_date, appt_time")]
    time_options = [f"{h:02d}:{m:02d}" for h in range(4, 24) for m in (0, 30)]
    return render_template("appointments.html", attention=attention, unmatched=unmatched, pending=pending,
                           waiting=waiting, booked=booked, lead=lead, settings=s,
                           time_options=time_options, last_sync=db.meta_get("last_sync"))


@bp.route("/po/<int:po_id>")
def po_detail(po_id):
    po = db.one("SELECT * FROM pos WHERE id = ?", (po_id,))
    if po is None:
        return redirect(url_for("main.appointments"))
    activity = db.q("SELECT * FROM activity WHERE po_id = ? ORDER BY id DESC", (po_id,))
    time_options = [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
    return render_template("po.html", po=view(po), activity=activity, time_options=time_options,
                           settings=db.settings())


@bp.post("/po/<int:po_id>/keep")
def po_keep(po_id):
    jobs.set_keep(po_id, request.form.get("keep") == "1", ACTOR)
    return _back()


@bp.post("/po/<int:po_id>/confirm")
def po_confirm(po_id):
    f = request.form
    if not f.get("appt_date") or not f.get("appt_time"):
        flash("Enter the appointment date and time.", "error")
    else:
        jobs.confirm_appointment(po_id, f["appt_date"], f["appt_time"], f.get("conf_no") or None, ACTOR)
        flash("Appointment saved and Smartsheet updated.", "ok")
    return _back()


@bp.post("/po/<int:po_id>/request")
def po_request(po_id):
    f = request.form
    if f.get("requested_date"):
        db.update_po(po_id, requested_date=f["requested_date"],
                     requested_time=f.get("requested_time") or db.settings()["request_default_time"])
    try:
        jobs.send_request(po_id, ACTOR)
        flash(f"Request sent for PO {display_po(db.one('SELECT po_number FROM pos WHERE id=?', (po_id,))[0])}.", "ok")
    except Exception as e:
        flash(f"Request not sent: {e}", "error")
    return _back()


@bp.post("/po/<int:po_id>/reschedule")
def po_reschedule(po_id):
    jobs.request_reschedule(po_id, ACTOR)
    flash("Reschedule request sent.", "ok")
    return _back()


@bp.post("/po/<int:po_id>/dismiss")
def po_dismiss(po_id):
    db.update_po(po_id, attention=None)
    db.log(po_id, "Cleared alert", None, ACTOR)
    return _back()


@bp.post("/po/<int:po_id>/close")
def po_close(po_id):
    db.update_po(po_id, state="closed", attention=None)
    db.log(po_id, "Stopped tracking", None, ACTOR)
    return _back()


@bp.post("/unmatched/<int:uid>/dismiss")
def unmatched_dismiss(uid):
    db.run("UPDATE unmatched_emails SET dismissed = 1 WHERE id = ?", (uid,))
    return _back()


@bp.post("/sync")
def sync_now():
    jobs.run_all()
    flash("Checked Smartsheet and the mailbox.", "ok")
    return _back()


# ------------------------------------------------------------ Documents
@bp.route("/documents")
def documents():
    show = request.args.get("show", "missing")
    rows = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE conversation_id IS NOT NULL OR state = 'shipped' "
        "ORDER BY CASE WHEN doc_status IN ('missing','failed') THEN 0 ELSE 1 END, "
        "act_ship IS NULL, act_ship, appt_date")]
    counts = {"missing": sum(r["doc_status"] in ("missing", "failed") for r in rows), "all": len(rows)}
    counts["done"] = counts["all"] - counts["missing"]
    if show == "missing":
        rows = [r for r in rows if r["doc_status"] in ("missing", "failed")]
    elif show == "done":
        rows = [r for r in rows if r["doc_status"] not in ("missing", "failed")]
    return render_template("documents.html", rows=rows, show=show, counts=counts)


@bp.post("/documents/<int:po_id>/upload")
def doc_upload(po_id):
    f = request.files.get("pdf")
    if not f or not f.filename.lower().endswith(".pdf"):
        flash("Choose a PDF file.", "error")
        return _back("main.documents")
    ok = jobs.send_document(po_id, f.filename, f.read(), ACTOR)
    flash("Document sent on the appointment thread." if ok else "Document not sent. See the row for details.",
          "ok" if ok else "error")
    return _back("main.documents")


@bp.post("/documents/bulk")
def doc_bulk():
    from .parser import find_po_numbers
    sent, skipped = 0, []
    for f in request.files.getlist("pdfs"):
        pos = find_po_numbers(f.filename)
        po = db.one("SELECT id FROM pos WHERE po_number = ?", (pos[0],)) if len(pos) == 1 else None
        if not f.filename.lower().endswith(".pdf") or po is None:
            skipped.append(f.filename)
            continue
        sent += jobs.send_document(po["id"], f.filename, f.read(), ACTOR)
    msg = f"Sent {sent} document{'s' if sent != 1 else ''}."
    if skipped:
        msg += " No PO match for: " + ", ".join(skipped)
    flash(msg, "error" if skipped else "ok")
    return _back("main.documents")


@bp.post("/documents/<int:po_id>/manual")
def doc_manual(po_id):
    jobs.mark_doc_manual(po_id, undo=request.form.get("undo") == "1", actor=ACTOR)
    return _back("main.documents")


# ------------------------------------------------------------ Reference
@bp.route("/locations")
def locations():
    locs = []
    for key, loc in dc_lookup.LOCATIONS.items():
        locs.append({**loc, "key": key, "codes": [(c, dc_lookup.BC_CODES[c][1])
                                                 for c in dc_lookup.codes_for_location(key)]})
    locs.sort(key=lambda l: (l["name"].endswith("Mixing Center"), l["name"]))
    return render_template("locations.html", locations=locs, day_names=dc_lookup.DAY_NAMES)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            if key == "auto_send_requests":
                db.set_setting(key, "1" if request.form.get(key) else "0")
            elif key in request.form:
                db.set_setting(key, request.form[key].strip())
        db.log(None, "Settings changed", None, ACTOR)
        flash("Settings saved.", "ok")
        return redirect(url_for("main.settings"))
    from .config import Config
    status = {"mail": bool(Config.MAILBOX and Config.MS_CLIENT_SECRET), "mailbox": Config.MAILBOX,
              "sheet": bool(Config.SMARTSHEET_TOKEN), "demo": Config.DEMO_MODE,
              "last_sync": db.meta_get("last_sync"), "last_error": db.meta_get("last_error")}
    return render_template("settings.html", s=db.settings(), status=status)


@bp.route("/activity")
def activity():
    rows = db.q("SELECT a.*, p.po_number FROM activity a LEFT JOIN pos p ON p.id = a.po_id "
                "ORDER BY a.id DESC LIMIT 300")
    return render_template("activity.html", rows=rows, display_po=display_po)
