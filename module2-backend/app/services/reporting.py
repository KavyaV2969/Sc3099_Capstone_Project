"""Shared attendance definitions for statistics and exports, bounded by retention."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Checkin, Session as AttendanceSession, utc_now
from app.schemas import as_utc

SINGAPORE = timezone(timedelta(hours=8))
MAX_SESSIONS = 1000
MAX_CHECKINS = 10000


def business_day(value):
    return as_utc(value).astimezone(SINGAPORE).date()


def rate(approved, eligible):
    return round(approved / eligible, 4) if eligible else 0.0


def window(start=None, end=None):
    now = utc_now()
    cutoff = now - timedelta(days=30)
    upper = as_utc(end) if end else datetime.combine(business_day(now) + timedelta(days=1),
        datetime.min.time(), SINGAPORE).astimezone(timezone.utc) - timedelta(microseconds=1)
    lower = as_utc(start) if start else cutoff
    if lower > upper:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    return max(lower, cutoff), upper, {"available_from": cutoff.isoformat(),
        "start": max(lower, cutoff).isoformat(), "end": upper.isoformat(),
        "limited_by_retention": lower < cutoff, "denominator_available": True}


def session_filters(start=None, end=None):
    lower, upper, coverage = window(start, end)
    return [AttendanceSession.status != "cancelled", AttendanceSession.checkin_opens_at <= utc_now(),
            AttendanceSession.checkin_opens_at >= utc_now() - timedelta(days=30),
            AttendanceSession.scheduled_start >= lower, AttendanceSession.scheduled_start <= upper], coverage


def load_report(database, course_ids, start=None, end=None, *, student_id=None):
    filters, coverage = session_filters(start, end)
    sessions = list(database.scalars(select(AttendanceSession).where(
        AttendanceSession.course_id.in_(course_ids), *filters)
        .order_by(AttendanceSession.scheduled_start, AttendanceSession.id).limit(MAX_SESSIONS + 1)))
    if len(sessions) > MAX_SESSIONS:
        raise HTTPException(status_code=422, detail="report exceeds 1000 sessions; narrow the date range")
    query = select(Checkin).where(Checkin.session_id.in_([s.id for s in sessions]),
                                  Checkin.scheduled_deletion_at > utc_now())
    if student_id is not None:
        query = query.where(Checkin.student_id == student_id)
    checkins = list(database.scalars(query
        .order_by(Checkin.checked_in_at, Checkin.id).limit(MAX_CHECKINS + 1)))
    if len(checkins) > MAX_CHECKINS:
        raise HTTPException(status_code=422, detail="report exceeds 10000 check-ins; narrow the date range")
    coverage["denominator_available"] = all(s.attendance_roster is not None for s in sessions)
    return sessions, checkins, coverage


def attendance(session, checkins, *, now=None):
    now = now or utc_now()
    known = (session.attendance_roster is not None and session.status != "cancelled"
             and as_utc(session.checkin_opens_at) <= now
             and as_utc(session.checkin_opens_at) >= now - timedelta(days=30))
    roster = set(session.attendance_roster or [])
    approved = {c.student_id for c in checkins if c.status == "approved" and c.student_id in roster
                and as_utc(c.scheduled_deletion_at) > now}
    return {"total_enrolled": len(roster) if known else None,
            "approved_attendance": len(approved) if known else None,
            "attendance_rate": rate(len(approved), len(roster)) if known else None,
            "denominator_available": known}
