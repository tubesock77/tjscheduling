"""Demo data for screenshots and local testing. Run: DEMO_MODE=1 python -m app.demo

PO numbers, DC codes and appointments come from open rows on the TRADER JOES
sheet; the site states (waiting, kept, alerts) are made up to show each screen.
"""
from . import create_app, db, jobs

POS = [
    # po_number, order_no, dc, cases, pallets, ship, act_ship, state, appt_date, appt_time, conf, extra
    ("0158257711", "S-ORD00975", "5623", 1200, 24, "2026-09-14", None, "pending_request", None, None, None, {}),
    ("0158355255", "S-ORD01087", "5621", 1200, 24, "2026-09-18", None, "pending_request", None, None, None, {}),
    ("0156374993", "S-ORD00227", None, 1200, 24, "2026-11-12", None, "pending_request", None, None, None,
     {"attention": "No DC # on the Smartsheet row"}),
    ("0158538110", "S-ORD01292", "5958", 1200, 24, "2026-10-05", None, "booked", "2026-10-07", "08:00", "L18249120",
     {"attention": "DC asked to use the reschedule portal", "reschedule_count": 1}),
    ("0156374901", "S-ORD00231", "6870", 1200, 24, "2026-10-10", None, "requested", None, None, None,
     {"requested_date": "2026-10-12", "requested_time": "08:00", "request_sent_at": "2026-10-02T09:14:00"}),
    ("0157565212", "S-ORD00620", "6879", 2520, 30, "2026-08-10", None, "reschedule_requested", "2026-10-06", "09:00",
     "N18401233", {"requested_date": "2026-10-08", "reschedule_count": 1, "request_sent_at": "2026-10-04T09:05:00"}),
    ("0158502808", "S-ORD01250", "6826", 1500, 30, "2026-09-21", None, "booked", "2026-10-06", "11:00", "K23299166",
     {"keep": 1}),
    ("0158142510", "S-ORD00801", "6245", 1200, 24, "2026-09-28", None, "booked", "2026-10-06", "14:00", "I18300456", {}),
    ("0158142471", "S-ORD00789", "6599", 1200, 24, "2026-09-04", "2026-10-05", "booked", "2026-10-08", "10:00",
     "H18304223", {}),
    ("0156374844", "S-ORD00232", "5625", 1200, 24, "2026-10-11", None, "booked", "2026-10-09", "10:00", "N18402157", {}),
    ("0156374846", "S-ORD00230", "6599", 1200, 24, "2026-10-01", None, "booked", "2026-10-12", "10:00", "H18304110",
     {"reschedule_count": 1}),
    ("0156374930", "S-ORD00219", "5958", 1200, 24, "2026-10-11", None, "booked", "2026-10-12", "08:00", "L18248850", {}),
    ("0156374983", "S-ORD00225", "6229", 1200, 24, "2026-10-10", None, "booked", "2026-10-15", "09:00", "M18361581", {}),
    ("0157582527", "S-ORD00181", "5629", 2520, 30, "2026-08-10", "2026-09-22", "shipped", "2026-09-24", "09:00",
     "L18248288", {}),
    ("0156827454", "S-ORD00221", "6879", 2016, 24, "2026-07-02", "2026-09-21", "shipped", "2026-09-24", "10:00",
     "N18401234", {"doc_status": "sent_manual", "doc_sent_at": "2026-09-22T14:30:00"}),
    ("0158142470", "S-ORD00787", "5625", 1200, 24, "2026-09-07", "2026-09-30", "shipped", "2026-10-02", "09:00",
     "N18402262", {"doc_status": "sent", "doc_sent_at": "2026-09-30T16:02:00",
                   "doc_filename": "158142470.pdf"}),
]


def seed():
    create_app()
    for t in ("pos", "activity", "unmatched_emails", "processed_messages", "meta"):
        db.run(f"DELETE FROM {t}")
    for i, (po, order, dc, cs, plts, ship, act, state, ad, at, conf, extra) in enumerate(POS):
        pid = db.run("INSERT INTO pos(po_number, state, created_at, updated_at) VALUES (?,?,?,?)",
                     (po, state, db.stamp(), db.stamp()))
        fields = dict(order_no=order, dc_code=dc, sheet_row_id=str(1000 + i), cases=cs, pallets=plts,
                      ship_date=ship, act_ship=act, sheet_status="APT. REQ." if state == "pending_request" else "BOOKED",
                      appt_date=ad, appt_time=at, conf_no=conf)
        if state != "pending_request":
            fields["conversation_id"] = f"demo-conv-{i}"
        fields.update(extra)
        db.update_po(pid, **fields)
        if state == "pending_request" and dc:
            jobs.prepare_request(pid)
        db.log(pid, "Picked up from Smartsheet", "STATUS is APT. REQ.")
        if state in ("requested", "booked", "reschedule_requested", "shipped"):
            db.log(pid, "Appointment request sent", "To the DC appointment inbox")
        if ad and state != "requested":
            db.log(pid, "Appointment booked", f"{ad} {at}, conf {conf}")
        if state == "reschedule_requested":
            db.log(pid, "Reschedule requested", f"Asked to move {ad} to {extra['requested_date']}")
        if extra.get("keep"):
            db.log(pid, "Marked keep", None, "Cody")
        if extra.get("doc_status") == "sent_manual":
            db.log(pid, "Marked document sent outside site", None, "Cody")
        if extra.get("doc_status") == "sent":
            db.log(pid, "Document sent", "158142470.pdf replied on the appointment thread", "Cody")
    db.run("UPDATE activity SET ts = '2026-10-02T09:00:00'")  # seed history happened earlier
    db.run("INSERT INTO unmatched_emails(message_id, sender, subject, received) VALUES (?,?,?,?)",
           ("demo-x", "Irving_Vendor_Appointments@wcdinc.net", "RE: Vendor appointment update", "2026-10-05T07:41:00"))
    db.meta_set("last_sync", "2026-10-05T09:50:00")
    print("Seeded", len(POS), "POs")


if __name__ == "__main__":
    seed()
