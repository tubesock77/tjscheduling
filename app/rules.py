"""Date rules for requesting and rescheduling appointments."""
from datetime import date, datetime, timedelta


def next_allowed_day(on_or_after, allowed_weekdays):
    d = on_or_after
    for _ in range(14):
        if d.weekday() in allowed_weekdays:
            return d
        d += timedelta(days=1)
    raise ValueError("No allowed delivery days configured")


def default_request_date(today, allowed_weekdays, lead_days):
    """First allowed delivery day at least `lead_days` from today.

    Placeholder until Cody decides how requested dates should be chosen.
    """
    return next_allowed_day(today + timedelta(days=lead_days), allowed_weekdays)


def reschedule_target(current_appt, allowed_weekdays, min_gap_days):
    """Next allowed day at least `min_gap_days` after the current appointment."""
    return next_allowed_day(current_appt + timedelta(days=min_gap_days), allowed_weekdays)


def appt_datetime(appt_date, appt_time):
    if not appt_date:
        return None
    d = date.fromisoformat(appt_date)
    hh, mm = (appt_time or "00:00").split(":")[:2]
    return datetime(d.year, d.month, d.day, int(hh), int(mm))


def hours_until(appt_date, appt_time, now):
    dt = appt_datetime(appt_date, appt_time)
    if dt is None:
        return None
    return (dt - now).total_seconds() / 3600.0


def needs_reschedule(po, now, lead_hours):
    """Booked, not kept, and inside the reschedule window (but not past)."""
    if po["state"] != "booked" or po["keep"]:
        return False
    h = hours_until(po["appt_date"], po["appt_time"], now)
    return h is not None and 0 < h <= lead_hours
