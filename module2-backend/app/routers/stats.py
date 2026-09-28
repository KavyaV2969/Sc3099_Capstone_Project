"""SQL-backed instructor dashboard statistics."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import UUID4
from sqlalchemy import case, cast, Date, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.models import Checkin, Course, Enrollment, Session as AttendanceSession, User
from app.schemas import (CourseStatistics, OverviewStatistics, SessionStatistics,
                         StudentStatistics, UserRole, as_utc)
from app.services.access import get_course, get_session, instructor_has_student_relationship, require_course_access, require_session_access

router = APIRouter(prefix="/stats", tags=["statistics"])


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


@router.get("/overview", response_model=OverviewStatistics)
def overview(
    course_id: UUID4 | None = None, days: int = Query(default=7, ge=1, le=365),
    database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=6)
    session_filters, checkin_filters = [], []
    if course_id:
        course = get_course(database, str(course_id))
        require_course_access(database, course, user, allow_ta=False)
        session_filters.append(AttendanceSession.course_id == course.id)
        checkin_filters.append(AttendanceSession.course_id == course.id)
    elif user.role == "instructor":
        session_filters.append((AttendanceSession.instructor_id == user.id) | (Course.instructor_id == user.id))
        checkin_filters.append((AttendanceSession.instructor_id == user.id) | (Course.instructor_id == user.id))
    session_base = select(AttendanceSession).join(Course, Course.id == AttendanceSession.course_id).where(*session_filters).subquery()
    checkin_base = (select(Checkin).join(AttendanceSession, AttendanceSession.id == Checkin.session_id)
                    .join(Course, Course.id == AttendanceSession.course_id).where(*checkin_filters).subquery())
    total_sessions = database.scalar(select(func.count()).select_from(session_base)) or 0
    active_sessions = database.scalar(select(func.count()).select_from(session_base).where(session_base.c.status == "active")) or 0
    total_today = database.scalar(select(func.count()).select_from(checkin_base).where(checkin_base.c.checked_in_at >= today)) or 0
    total_week = database.scalar(select(func.count()).select_from(checkin_base).where(checkin_base.c.checked_in_at >= week)) or 0
    aggregates = database.execute(select(
        func.count(checkin_base.c.id),
        func.sum(case((checkin_base.c.status == "approved", 1), else_=0)),
        func.sum(case((checkin_base.c.status.in_(("flagged", "appealed")), 1), else_=0)),
        func.avg(checkin_base.c.risk_score),
    )).one()
    sqlite = database.get_bind().dialect.name == "sqlite"
    checkin_day = func.date(checkin_base.c.checked_in_at) if sqlite else cast(checkin_base.c.checked_in_at, Date)
    session_day = func.date(AttendanceSession.scheduled_start) if sqlite else cast(AttendanceSession.scheduled_start, Date)
    daily_rows = database.execute(
        select(checkin_day, func.count())
        .where(checkin_base.c.checked_in_at >= today - timedelta(days=days - 1))
        .group_by(checkin_day)
        .order_by(checkin_day)
    ).all()
    daily_slots = dict(database.execute(
        select(session_day, func.count(Enrollment.id))
        .join(Enrollment, (Enrollment.course_id == AttendanceSession.course_id)
              & Enrollment.is_active.is_(True))
        .join(Course, Course.id == AttendanceSession.course_id)
        .where(AttendanceSession.scheduled_start >= today - timedelta(days=days - 1), *session_filters)
        .group_by(session_day)
    ).all())
    enrolled_slots = database.scalar(
        select(func.count()).select_from(Enrollment)
        .join(AttendanceSession, AttendanceSession.course_id == Enrollment.course_id)
        .join(Course, Course.id == AttendanceSession.course_id)
        .where(Enrollment.is_active.is_(True), *session_filters)
    ) or 0
    high_today = database.scalar(select(func.count()).select_from(checkin_base).where(
        checkin_base.c.checked_in_at >= today, checkin_base.c.risk_score >= .5)) or 0
    total, approved, flagged, average_risk = aggregates
    checkins_by_day = [{"date": str(day), "count": count} for day, count in daily_rows]
    return {
        "total_sessions": total_sessions, "active_sessions": active_sessions,
        "total_checkins_today": total_today, "total_checkins_week": total_week,
        "average_attendance_rate": _rate(total, enrolled_slots),
        "flagged_pending_review": flagged or 0, "approval_rate": _rate(approved or 0, total or 0),
        "average_risk_score": round(float(average_risk or 0), 4),
        "high_risk_checkins_today": high_today,
        "trends": {"checkins_by_day": checkins_by_day,
                   "attendance_rate_by_day": [
                       {"date": str(day), "rate": _rate(count, daily_slots.get(day, 0))}
                       for day, count in daily_rows
                   ]},
    }


@router.get("/sessions/{session_id}", response_model=SessionStatistics)
def session_statistics(
    session_id: UUID4, database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN)),
):
    session = get_session(database, str(session_id))
    course = require_session_access(database, session, user)
    enrolled = database.scalar(select(func.count()).select_from(Enrollment).where(
        Enrollment.course_id == session.course_id, Enrollment.is_active.is_(True))) or 0
    if database.get_bind().dialect.name == "sqlite":
        elapsed_minutes = (
            func.strftime("%s", Checkin.checked_in_at)
            - func.strftime("%s", session.scheduled_start)
        ) / 60.0
        bucket = func.floor(elapsed_minutes / 5) * 5
    else:
        elapsed_minutes = (
            func.extract("epoch", Checkin.checked_in_at)
            - func.extract("epoch", session.scheduled_start)
        ) / 60.0
        bucket = func.floor(elapsed_minutes / 5) * 5
    aggregate = database.execute(select(
        func.count(Checkin.id), func.avg(Checkin.risk_score),
        func.avg(Checkin.distance_from_venue_meters), func.avg(elapsed_minutes),
    ).where(Checkin.session_id == session.id)).one()
    by_status = dict(database.execute(select(Checkin.status, func.count()).where(
        Checkin.session_id == session.id).group_by(Checkin.status)).all())
    risk = database.execute(select(
        func.sum(case((Checkin.risk_score < .3, 1), else_=0)),
        func.sum(case(((Checkin.risk_score >= .3) & (Checkin.risk_score < .5), 1), else_=0)),
        func.sum(case((Checkin.risk_score >= .5, 1), else_=0)),
    ).where(Checkin.session_id == session.id)).one()
    timeline = database.execute(select(bucket.label("minute"), func.count())
                                .where(Checkin.session_id == session.id)
                                .group_by(bucket).order_by(bucket)).all()
    checked_in, average_risk, average_distance, average_minutes = aggregate
    return {
        "session_id": session.id, "session_name": session.name, "course_code": course.code,
        "scheduled_start": session.scheduled_start, "status": session.status,
        "total_enrolled": enrolled, "checked_in": checked_in,
        "attendance_rate": _rate(checked_in, enrolled),
        "by_status": {name: int(by_status.get(name, 0)) for name in ("approved", "flagged", "rejected", "pending", "appealed")},
        "average_risk_score": round(float(average_risk or 0), 4),
        "average_distance_meters": round(float(average_distance or 0), 2),
        "average_checkin_time_minutes": round(float(average_minutes or 0), 2),
        "risk_distribution": {"low": risk[0] or 0, "medium": risk[1] or 0, "high": risk[2] or 0},
        "checkin_timeline": [{"minute": int(minute), "count": count} for minute, count in timeline],
    }


@router.get("/courses/{course_id}", response_model=CourseStatistics)
def course_statistics(
    course_id: UUID4, start_date: datetime | None = None, end_date: datetime | None = None,
    database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
):
    course = get_course(database, str(course_id))
    require_course_access(database, course, user, allow_ta=False)
    filters = [AttendanceSession.course_id == course.id]
    if start_date: filters.append(AttendanceSession.scheduled_start >= as_utc(start_date))
    if end_date: filters.append(AttendanceSession.scheduled_start <= as_utc(end_date))
    sessions = database.execute(select(
        AttendanceSession.id, AttendanceSession.name, AttendanceSession.scheduled_start,
        func.count(Checkin.id),
    ).outerjoin(Checkin, Checkin.session_id == AttendanceSession.id).where(*filters)
      .group_by(AttendanceSession.id).order_by(AttendanceSession.scheduled_start)).all()
    enrolled = database.scalar(select(func.count()).select_from(Enrollment).where(
        Enrollment.course_id == course.id, Enrollment.is_active.is_(True))) or 0
    attendance_filters = [AttendanceSession.course_id == course.id]
    if start_date: attendance_filters.append(AttendanceSession.scheduled_start >= as_utc(start_date))
    if end_date: attendance_filters.append(AttendanceSession.scheduled_start <= as_utc(end_date))
    attendance = (select(Checkin.student_id.label("student_id"),
                         func.count(Checkin.id).label("attended"),
                         func.avg(Checkin.risk_score).label("average_risk"))
                  .join(AttendanceSession, AttendanceSession.id == Checkin.session_id)
                  .where(*attendance_filters).group_by(Checkin.student_id).subquery())
    students = database.execute(select(
        User.id, User.full_name, func.coalesce(attendance.c.attended, 0),
        func.coalesce(attendance.c.average_risk, 0)
    ).join(Enrollment, Enrollment.student_id == User.id)
      .outerjoin(attendance, attendance.c.student_id == User.id)
      .where(Enrollment.course_id == course.id, Enrollment.is_active.is_(True))
      .order_by(User.full_name)).all()
    total_sessions = len(sessions)
    session_items = [{"session_id": sid, "name": name, "date": when.date(),
                      "attendance_rate": _rate(count, enrolled), "checked_in": count}
                     for sid, name, when, count in sessions]
    student_items = [{"student_id": sid, "student_name": name, "sessions_attended": count,
                      "attendance_rate": _rate(count, total_sessions),
                      "average_risk_score": round(float(avg or 0), 4)}
                     for sid, name, count, avg in students]
    alerts = [{"student_id": item["student_id"], "student_name": item["student_name"],
               "attendance_rate": item["attendance_rate"],
               "sessions_missed": max(0, total_sessions - item["sessions_attended"])}
              for item in student_items if item["attendance_rate"] < .75]
    return {"course_id": course.id, "course_code": course.code, "course_name": course.name,
            "total_sessions": total_sessions, "total_enrolled": enrolled,
            "overall_attendance_rate": _rate(sum(row[3] for row in sessions), enrolled * total_sessions),
            "sessions": session_items, "student_attendance": student_items,
            "low_attendance_alerts": alerts}


@router.get("/students/{student_id}", response_model=StudentStatistics)
def student_statistics(
    student_id: UUID4, database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
):
    student = database.get(User, str(student_id))
    if student is None or student.role != "student":
        raise HTTPException(status_code=404, detail="student not found")
    if not instructor_has_student_relationship(database, user, student.id):
        raise HTTPException(status_code=403, detail="insufficient permissions")
    rows = database.execute(select(
        Course.id, Course.code, func.count(func.distinct(AttendanceSession.id)),
        func.count(func.distinct(Checkin.id)), func.avg(Checkin.risk_score)
    ).join(Enrollment, Enrollment.course_id == Course.id)
      .outerjoin(AttendanceSession, AttendanceSession.course_id == Course.id)
      .outerjoin(Checkin, (Checkin.session_id == AttendanceSession.id) & (Checkin.student_id == student.id))
      .where(Enrollment.student_id == student.id, Enrollment.is_active.is_(True))
      .group_by(Course.id).order_by(Course.code)).all()
    recent = database.execute(select(AttendanceSession.name, Course.code, Checkin.checked_in_at, Checkin.status)
                              .join(Checkin, Checkin.session_id == AttendanceSession.id)
                              .join(Course, Course.id == AttendanceSession.course_id)
                              .where(Checkin.student_id == student.id)
                              .order_by(Checkin.checked_in_at.desc()).limit(20)).all()
    return {"student_id": student.id, "student_name": student.full_name, "student_email": student.email,
            "courses": [{"course_id": cid, "course_code": code, "attendance_rate": _rate(attended, total),
                         "sessions_attended": attended, "total_sessions": total,
                         "average_risk_score": round(float(avg or 0), 4)}
                        for cid, code, total, attended, avg in rows],
            "recent_checkins": [{"session_name": name, "course_code": code,
                                 "checked_in_at": checked, "status": status}
                                for name, code, checked, status in recent]}
