"""Read DC replies: find PO numbers, appointment date/time, confirmation #.

Tuned without real DC replies yet. Anything it can't read confidently goes
to "Needs you" for Cody to enter by hand, so a miss is never silent.
"""
import re
from datetime import date
from html import unescape

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

PO_RE = re.compile(r"(?<!\d)0?(1\d{8})(?!\d)")
CONF_RE = re.compile(r"\b([A-Z]\d{8})\b")
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
WORD_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", re.I)
MILITARY_RE = re.compile(r"\b([01]\d|2[0-3])([0-5]\d)\s*(?:hrs|hours)\b", re.I)
PORTAL_HINTS = ("reschedule-appointment", "appointments.wcdinc.net", "use the portal",
                "vendor portal", "please use the link", "use the link")


def html_to_text(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", unescape(text)).strip()


def find_po_numbers(text):
    """Return 10-digit PO numbers (with leading zero) found in text."""
    return sorted({"0" + m for m in PO_RE.findall(text or "")})


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_reply(text):
    """Extract what we can. Returns dict with date, time, conf_no, portal, confident."""
    result = {"date": None, "time": None, "conf_no": None, "portal": False, "confident": False}
    if not text:
        return result
    low = text.lower()
    result["portal"] = any(h in low for h in PORTAL_HINTS)

    dates = []
    for m in WORD_DATE_RE.finditer(text):
        try:
            dates.append(date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
        except ValueError:
            pass
    for m in NUMERIC_DATE_RE.finditer(text):
        try:
            dates.append(date(_year(m.group(3)), int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    if dates:
        result["date"] = dates[0].isoformat()

    tm = TIME_RE.search(text)
    if tm:
        hh, mm, ampm = int(tm.group(1)), tm.group(2), (tm.group(3) or "").lower()
        if ampm.startswith("p") and hh < 12:
            hh += 12
        if ampm.startswith("a") and hh == 12:
            hh = 0
        if hh <= 23:
            result["time"] = f"{hh:02d}:{mm}"
    else:
        mt = MILITARY_RE.search(text)
        if mt:
            result["time"] = f"{mt.group(1)}:{mt.group(2)}"

    conf = CONF_RE.search(text)
    if conf:
        result["conf_no"] = conf.group(1)

    # Confident only with a single clear date plus a time or confirmation number.
    result["confident"] = bool(result["date"] and len(set(dates)) == 1
                               and (result["time"] or result["conf_no"]))
    return result
