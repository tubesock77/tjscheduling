"""HTML bodies for outgoing emails. The request table matches Cody's format."""
from datetime import date
from html import escape


def display_po(po_number):
    """0158142470 -> 158142470 (TJ format without the leading zero)."""
    return (po_number or "").lstrip("0")


def long_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def short_time(hhmm):
    hh, mm = hhmm.split(":")[:2]
    return f"{int(hh)}:{mm}"


def _signature(settings):
    return "<br>".join(escape(line) for line in settings["signature"].splitlines())


_TH = 'style="border:1px solid #000;padding:2px 8px;font-weight:normal;text-align:center"'
_TD = 'style="border:1px solid #000;padding:2px 8px;text-align:center"'


def request_subject(po, settings):
    return f"Delivery Appointment Request - PO {display_po(po['po_number'])}"


def request_body(po, dc, settings):
    headers = ["DRY/COOLER", "REQUESTED DATE", "REQUESTED TIME", "PO NUMBER", "VENDOR DESCRIPTION",
               "CARRIER", "POINT OF ORIGIN", "CONTACT", "PALLETS", "CASES", "SKUS"]
    values = [dc["load_type"], long_date(po["requested_date"]), short_time(po["requested_time"]),
              display_po(po["po_number"]), settings["vendor"], settings["carrier"], settings["origin"],
              settings["contact"], po["pallets"] or "", po["cases"] or "", "1"]
    head = "".join(f"<th {_TH}>{escape(h)}</th>" for h in headers)
    row = "".join(f"<td {_TD}>{escape(str(v))}</td>" for v in values)
    return (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
        "<p>May I please schedule a delivery appointment for the following:</p>"
        f'<table style="border-collapse:collapse"><tr>{head}</tr><tr>{row}</tr></table>'
        f"<p>{_signature(settings)}</p></div>"
    )


def reschedule_body(po, new_date, settings):
    conf = f" (confirmation {escape(po['conf_no'])})" if po["conf_no"] else ""
    return (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
        "<p>Hello,</p>"
        f"<p>We need to reschedule the delivery appointment for PO {display_po(po['po_number'])}{conf}, "
        f"currently scheduled for {long_date(po['appt_date'])} at {short_time(po['appt_time'])}.</p>"
        f"<p>Could we please move it to {long_date(new_date)} at {short_time(po['appt_time'])}? "
        "If that time isn't available, any time that day works for us.</p>"
        f"<p>{_signature(settings)}</p></div>"
    )


def document_body(po, settings):
    return (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
        "<p>Hello,</p>"
        f"<p>Attached is the BOL and Bioterrorism form for PO {display_po(po['po_number'])}.</p>"
        f"<p>{_signature(settings)}</p></div>"
    )


def reminder_body(missing_docs, attention, base_url):
    parts = ['<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">']
    if missing_docs:
        parts.append("<p><b>Shipped POs still missing the BOL / Bioterrorism form:</b></p><ul>")
        for p in missing_docs:
            shipped = ""
            if p["act_ship"]:
                d = date.fromisoformat(p["act_ship"][:10])
                shipped = f", shipped {d.strftime('%b')} {d.day}"
            parts.append(f"<li>PO {display_po(p['po_number'])} ({escape(p['order_no'] or '')}){shipped}</li>")
        parts.append("</ul>")
    if attention:
        parts.append("<p><b>Appointments that need you:</b></p><ul>")
        for p in attention:
            parts.append(f"<li>PO {display_po(p['po_number'])}: {escape(p['attention'])}</li>")
        parts.append("</ul>")
    parts.append(f'<p><a href="{base_url}">Open the scheduling site</a></p></div>')
    return "".join(parts)
