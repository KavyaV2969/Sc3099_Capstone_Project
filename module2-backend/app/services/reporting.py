"""Shared attendance definitions for statistics and exports, bounded by retention."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Checkin, Enrollment, Session as AttendanceSession, User, utc_now
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
    supported_start = max(lower, cutoff)
    if supported_start > upper:
        raise HTTPException(status_code=422, detail="date range has no retained reporting coverage")
    return supported_start, upper, {"available_from": cutoff.isoformat(),
        "start": supported_start.isoformat(), "end": upper.isoformat(),
        "limited_by_retention": lower < cutoff, "denominator_available": True}


def session_filters(start=None, end=None, *, scheduled_dates=True):
    lower, upper, coverage = window(start, end)
    filters = [AttendanceSession.status != "cancelled", AttendanceSession.checkin_opens_at <= utc_now(),
               AttendanceSession.checkin_opens_at >= utc_now() - timedelta(days=30)]
    if scheduled_dates:
        filters += [AttendanceSession.scheduled_start >= lower, AttendanceSession.scheduled_start <= upper]
    return filters, coverage


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


def current_rosters(database, course_ids) -> dict[str, set[str]]:
    """Currently eligible students per course (active student, active enrollment)."""
    rows = database.execute(select(Enrollment.course_id, Enrollment.student_id)
        .join(User, User.id == Enrollment.student_id)
        .where(Enrollment.course_id.in_(list(course_ids)), Enrollment.is_active.is_(True),
               User.is_active.is_(True), User.role == "student"))
    rosters: dict[str, set[str]] = {}
    for course_id, student_id in rows:
        rosters.setdefault(course_id, set()).add(student_id)
    return rosters


def roster_known(session, *, now=None) -> bool:
    """A retained snapshot exists for an opened, uncancelled session."""
    now = now or utc_now()
    return (session.attendance_roster is not None and session.status != "cancelled"
            and as_utc(session.checkin_opens_at) <= now
            and as_utc(session.checkin_opens_at) >= now - timedelta(days=30))


def effective_roster(session, fallback=None, *, now=None) -> set[str]:
    """The snapshot when known; otherwise the course's current eligible enrollment.

    Sessions never activated, not yet open, cancelled or with legacy unknown
    history still report numeric attendance instead of null.
    """
    return set(session.attendance_roster) if roster_known(session, now=now) else set(fallback or ())


def attendance(session, checkins, *, fallback=None, now=None):
    now = now or utc_now()
    known = roster_known(session, now=now)
    roster = effective_roster(session, fallback, now=now)
    approved = {c.student_id for c in checkins if c.status == "approved" and c.student_id in roster
                and as_utc(c.scheduled_deletion_at) > now}
    return {"total_enrolled": len(roster),
            "approved_attendance": len(approved),
            "attendance_rate": rate(len(approved), len(roster)),
            "denominator_available": known,
            "denominator_source": "roster_snapshot" if known else "current_enrollment"}
