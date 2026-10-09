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
    d["po_display"] = po["po_number"]  # site shows the full PO with its leading 0
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
        paused = jobs.is_paused()
        reason = db.meta_get("pause_reason") or ""
        attention += sum(1 for i in jobs.upcoming() if i["status"] == "review")
    except Exception:
        attention = missing = 0
        paused, reason = False, ""
    return {"nav": {"attention": attention, "missing": missing, "paused": paused, "pause_reason": reason}}


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
    for p in pending:
        p["earliest"] = jobs.earliest_for(p, p["dc"]).isoformat() if p["dc"] else None
    waiting = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE state IN ('requested','reschedule_requested') AND attention IS NULL "
        "ORDER BY request_sent_at")]
    booked = [view(p) for p in db.q(
        "SELECT * FROM pos WHERE state = 'booked' AND attention IS NULL ORDER BY appt_date, appt_time")]
    time_options = [f"{h:02d}:{m:02d}" for h in range(4, 24) for m in (0, 30)]
    queue = jobs.upcoming()
    for item in queue:
        item["view"] = view(item["po"])
    return render_template("appointments.html", attention=attention, unmatched=unmatched, pending=pending,
                           waiting=waiting, booked=booked, lead=lead, settings=s, queue=queue,
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
        flash(f"Request sent for PO {db.one('SELECT po_number FROM pos WHERE id=?', (po_id,))[0]}.", "ok")
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


@bp.post("/pause")
def pause_toggle():
    if request.form.get("action") == "resume":
        jobs.resume(ACTOR)
        flash("Automatic emails resumed.", "ok")
    else:
        jobs.pause("Paused by Cody", ACTOR)
        flash("Automatic emails paused. Nothing goes to a DC unless you click Send.", "ok")
    return _back()


@bp.post("/po/<int:po_id>/override")
def po_override(po_id):
    d = request.form.get("new_date")
    if d:
        db.update_po(po_id, reschedule_override=d)
        db.log(po_id, "Reschedule date changed", f"Will ask for {d}", ACTOR)
        flash("New date saved for this reschedule.", "ok")
    return _back()


@bp.post("/po/<int:po_id>/cancel-auto")
def po_cancel_auto(po_id):
    db.update_po(po_id, auto_send_at=None)
    db.log(po_id, "Automatic request cancelled", "Waiting for you to click Send", ACTOR)
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
    from datetime import timedelta
    today = now().date()
    window = int(db.settings().get("docs_window_days", "2"))
    soon, later, done = [], [], []
    for p in db.q("SELECT * FROM pos WHERE (conversation_id IS NOT NULL OR state = 'shipped') AND state != 'closed'"):
        r = view(p)
        shipped = bool(p["act_ship"]) or p["state"] == "shipped"
        if p["act_ship"]:
            ship_on, source = p["act_ship"], "Shipped"
        elif p["appt_date"] and r["dc"]:
            # Appointed: the truck has to leave transit days before the appointment.
            ship_on = (date.fromisoformat(p["appt_date"]) - timedelta(days=r["dc"]["transit"])).isoformat()
            source = f"Appt minus {r['dc']['transit']}-day transit"
        elif p["ship_date"]:
            ship_on, source = p["ship_date"], "Smartsheet ship date"
        else:
            ship_on, source = None, ""
        r.update(ship_on=ship_on, ship_source=source, shipped=shipped)
        if p["doc_status"] not in ("missing", "failed"):
            done.append(r)
        elif shipped or (ship_on and date.fromisoformat(ship_on[:10]) <= today + timedelta(days=window)):
            soon.append(r)
        else:
            later.append(r)
    key = lambda r: (r["ship_on"] or "9999", r["appt_date"] or "9999")
    soon.sort(key=key)
    later.sort(key=key)
    done.sort(key=lambda r: r["doc_sent_at"] or "", reverse=True)
    # Everything else, grouped by product: not-sent first (soonest ship), then sent (newest first).
    groups = {}
    for r in later + done:
        groups.setdefault(r["product"] or "No product", []).append(r)
    by_product = [{"product": k, "rows": v,
                   "not_sent": sum(1 for r in v if r["doc_status"] in ("missing", "failed")),
                   "sent": sum(1 for r in v if r["doc_status"] not in ("missing", "failed"))}
                  for k, v in sorted(groups.items(), key=lambda kv: (kv[0] == "No product", kv[0]))]
    return render_template("documents.html", soon=soon, later=later, done=done, by_product=by_product,
                           window=window, today=today.isoformat())


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


@bp.route("/documents/<int:po_id>/file")
def doc_file(po_id):
    import os
    from flask import abort, send_file
    po = db.one("SELECT doc_path, po_number FROM pos WHERE id = ?", (po_id,))
    if not po or not po["doc_path"] or not os.path.exists(po["doc_path"]):
        abort(404)
    return send_file(po["doc_path"], mimetype="application/pdf",
                     download_name=f"PO{display_po(po['po_number'])}_BOL_Bioterrorism.pdf")


@bp.post("/documents/<int:po_id>/check")
def doc_check(po_id):
    import hashlib
    import os
    po = db.one("SELECT * FROM pos WHERE id = ?", (po_id,))
    name = f"PO{display_po(po['po_number'])}_BOL_Bioterrorism.pdf"
    if not po["doc_path"] or not os.path.exists(po["doc_path"]):
        flash("The original upload isn't on file for this PO, so there's nothing to compare against.", "error")
        return _back("main.documents")
    original = open(po["doc_path"], "rb").read()
    try:
        sent = jobs.Services.graph.sent_attachment(po["conversation_id"], name)
    except Exception as e:
        flash(f"Couldn't read Sent Items: {e}", "error")
        return _back("main.documents")
    if sent is None:
        flash(f"Couldn't find {name} in Sent Items for this PO's thread.", "error")
    elif hashlib.sha256(sent).digest() == hashlib.sha256(original).digest():
        flash(f"The copy in Sent Items is identical to your upload ({len(sent):,} bytes). "
              "The file is fine; the download error is coming from Outlook on the web.", "ok")
    else:
        flash(f"The copy in Sent Items is different from your upload ({len(sent):,} vs {len(original):,} bytes). "
              "The attachment was damaged. Use Send again.", "error")
    db.log(po_id, "Checked sent attachment", None, ACTOR)
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
    codes = dc_lookup.all_codes()
    locs = []
    for key in dc_lookup.LOCATIONS:
        loc = dc_lookup.location(key)
        edited = db.one("SELECT 1 FROM location_overrides WHERE key = ?", (key,)) is not None
        locs.append({**loc, "key": key, "edited": edited,
                     "codes": [(c, codes[c][1], codes[c][2]) for c in dc_lookup.codes_for_location(key)]})
    locs.sort(key=lambda l: (l["name"].endswith("Mixing Center"), l["name"]))
    return render_template("locations.html", locations=locs, day_names=dc_lookup.DAY_NAMES,
                           edit=request.args.get("edit"))


def _recheck_unknown_dcs():
    """After a code is added, retry POs that were stuck on an unknown DC #."""
    for p in db.q("SELECT id, dc_code FROM pos WHERE state = 'pending_request' AND attention LIKE '%DC #%'"):
        if dc_lookup.resolve(p["dc_code"]):
            db.update_po(p["id"], attention=None)
            jobs.prepare_request(p["id"])


@bp.post("/locations/<key>")
def location_save(key):
    if key not in dc_lookup.LOCATIONS:
        return redirect(url_for("main.locations"))
    days = sorted(int(d) for d in request.form.getlist("days") if d.isdigit() and int(d) < 7)
    email = request.form.get("email", "").strip()
    transit = request.form.get("transit", "").strip()
    if not transit.isdigit() or not 0 <= int(transit) <= 14:
        flash("Transit days must be a number from 0 to 14.", "error")
        return redirect(url_for("main.locations", edit=key))
    transit = int(transit)
    if not days:
        flash("Pick at least one delivery day.", "error")
        return redirect(url_for("main.locations", edit=key))
    if "@" not in email or " " in email:
        flash("That email address doesn't look right.", "error")
        return redirect(url_for("main.locations", edit=key))
    before = dc_lookup.location(key)
    db.run("INSERT INTO location_overrides(key, days, email, transit) VALUES (?,?,?,?) "
           "ON CONFLICT(key) DO UPDATE SET days = excluded.days, email = excluded.email, transit = excluded.transit",
           (key, ",".join(map(str, days)), email, transit))
    names = dc_lookup.DAY_NAMES
    changes = []
    if before["days"] != days:
        changes.append("days " + "/".join(names[d] for d in before["days"]) + " to " + "/".join(names[d] for d in days))
    if before["transit"] != transit or before["transit_estimated"]:
        changes.append(f"transit {before['transit']} to {transit} days")
    if before["email"].lower() != email.lower():
        changes.append(f"email {before['email']} to {email}")
    if changes:
        db.log(None, f"Location edited: {before['name']}", "; ".join(changes), ACTOR)
    flash(f"{before['name']} saved.", "ok")
    return redirect(url_for("main.locations"))


@bp.post("/locations/<key>/reset")
def location_reset(key):
    if key in dc_lookup.LOCATIONS:
        db.run("DELETE FROM location_overrides WHERE key = ?", (key,))
        db.log(None, f"Location reset: {dc_lookup.LOCATIONS[key]['name']}", "Back to TJ's 2026 list", ACTOR)
        flash(f"{dc_lookup.LOCATIONS[key]['name']} reset to TJ's 2026 list.", "ok")
    return redirect(url_for("main.locations"))


@bp.post("/codes")
def code_add():
    code = dc_lookup.normalize_code(request.form.get("code"))
    key = request.form.get("location_key")
    name = request.form.get("bc_name", "").strip() or f"DC {code}"
    load_type = request.form.get("load_type") if request.form.get("load_type") in ("DRY", "COOLER") else "DRY"
    if not code or not code.isdigit() or key not in dc_lookup.LOCATIONS:
        flash("Enter the DC # (numbers only) and pick a location.", "error")
        return redirect(url_for("main.locations"))
    db.run("INSERT INTO code_overrides(code, location_key, bc_name, load_type, removed) VALUES (?,?,?,?,0) "
           "ON CONFLICT(code) DO UPDATE SET location_key = excluded.location_key, bc_name = excluded.bc_name, "
           "load_type = excluded.load_type, removed = 0", (code, key, name, load_type))
    db.log(None, f"DC # {code} assigned", f"{dc_lookup.LOCATIONS[key]['name']}, {name}, {load_type}", ACTOR)
    _recheck_unknown_dcs()
    flash(f"DC # {code} now goes to {dc_lookup.LOCATIONS[key]['name']}.", "ok")
    return redirect(url_for("main.locations"))


@bp.post("/codes/<code>/remove")
def code_remove(code):
    codes = dc_lookup.all_codes()
    if code in codes:
        key, name, load_type = codes[code]
        db.run("INSERT INTO code_overrides(code, location_key, bc_name, load_type, removed) VALUES (?,?,?,?,1) "
               "ON CONFLICT(code) DO UPDATE SET removed = 1", (code, key, name, load_type))
        db.log(None, f"DC # {code} removed", f"Was {dc_lookup.LOCATIONS[key]['name']}", ACTOR)
        flash(f"DC # {code} removed.", "ok")
    return redirect(url_for("main.locations"))


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            if key == "paused":
                continue  # controlled by the Pause button
            if key in ("auto_send_requests", "review_reschedules"):
                db.set_setting(key, "1" if request.form.get(key) else "0")
            elif key in request.form:
                db.set_setting(key, request.form[key].strip())
        db.log(None, "Settings changed", None, ACTOR)
        flash("Settings saved.", "ok")
        return redirect(url_for("main.settings"))
    from .config import Config
    status = {"mail": bool(Config.MAILBOX and Config.MS_CLIENT_SECRET), "mailbox": Config.MAILBOX,
              "sheet": bool(Config.SMARTSHEET_TOKEN), "demo": Config.DEMO_MODE,
              "last_sync": db.meta_get("last_sync"), "last_error": db.meta_get("last_error"),
              "sent_today": jobs.auto_sends_today()}
    return render_template("settings.html", s=db.settings(), status=status)


@bp.route("/activity")
def activity():
    rows = db.q("SELECT a.*, p.po_number FROM activity a LEFT JOIN pos p ON p.id = a.po_id "
                "ORDER BY a.id DESC LIMIT 300")
    return render_template("activity.html", rows=rows, display_po=lambda n: n or "")
