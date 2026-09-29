"""SQL-backed instructor dashboard statistics."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import UUID4
from sqlalchemy import case, cast, Date, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.models import Checkin, Course, Enrollment, Session as AttendanceSession, User, utc_now
from app.services.reporting import attendance, business_day, load_report, rate, session_filters, MAX_CHECKINS
from app.schemas import (CourseStatistics, OverviewStatistics, SessionStatistics,
                         StudentStatistics, UserRole, as_utc)
from app.services.access import accessible_course_ids, get_course, get_session, require_course_access, require_session_access

router = APIRouter(prefix="/stats", tags=["statistics"])


def _group(sessions, checkins):
    grouped = {session.id: [] for session in sessions}
    for checkin in checkins:
        grouped[checkin.session_id].append(checkin)
    return grouped


@router.get("/overview", response_model=OverviewStatistics)
def overview(course_id: UUID4 | None = None, days: int = Query(default=7, ge=1, le=365),
             database: Session = Depends(get_db),
             user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    ids = accessible_course_ids(user, read_only=True)
    if course_id:
        course = get_course(database, str(course_id))
        require_course_access(database, course, user, allow_ta=False, read_only=True)
        ids = [course.id]
    sessions, checkins, coverage = load_report(database, ids)
    grouped = _group(sessions, checkins)
    summaries = {s.id: attendance(s, grouped[s.id]) for s in sessions}
    today = business_day(utc_now())
    daily = {}
    for session in sessions:
        day = business_day(session.scheduled_start)
        if day < today - timedelta(days=min(days, 30) - 1):
            continue
        item = daily.setdefault(day, {"count": 0, "approved": 0, "slots": 0, "known": True})
        summary = summaries[session.id]
        item["count"] += len(grouped[session.id])
        item["approved"] += summary["approved_attendance"] or 0
        item["slots"] += summary["total_enrolled"] or 0
        item["known"] &= summary["denominator_available"]
    total = len(checkins)
    approved = sum(c.status == "approved" for c in checkins)
    slots = sum(item["total_enrolled"] or 0 for item in summaries.values())
    trusted_approved = sum(item["approved_attendance"] or 0 for item in summaries.values())
    session_days = {s.id: business_day(s.scheduled_start) for s in sessions}
    visible_courses = select(Course.id).where(Course.is_active.is_(True), Course.id.in_(ids))
    total_courses = database.scalar(select(func.count()).select_from(visible_courses.subquery())) or 0
    total_students = database.scalar(select(func.count(func.distinct(Enrollment.student_id)))
        .join(User, User.id == Enrollment.student_id).where(Enrollment.course_id.in_(visible_courses),
            Enrollment.is_active.is_(True), User.is_active.is_(True), User.role == "student")) or 0
    return {"total_sessions": len(sessions), "active_sessions": sum(s.status == "active" for s in sessions),
        "total_courses": total_courses, "total_students": total_students,
        "total_checkins_today": sum(session_days[c.session_id] == today for c in checkins),
        "total_checkins_week": sum(session_days[c.session_id] >= today - timedelta(days=6) for c in checkins),
        "average_attendance_rate": rate(trusted_approved, slots) if coverage["denominator_available"] else None,
        "flagged_pending_review": sum(c.status in {"flagged", "appealed"} for c in checkins),
        "approval_rate": rate(approved, total),
        "average_risk_score": round(sum(c.risk_score for c in checkins) / total, 4) if total else 0,
        "high_risk_checkins_today": sum(session_days[c.session_id] == today and c.risk_score >= .5 for c in checkins),
        "coverage": coverage,
        "trends": {"checkins_by_day": [{"date": day, "count": v["count"]} for day, v in sorted(daily.items())],
                   "attendance_rate_by_day": [{"date": day, "rate": rate(v["approved"], v["slots"]) if v["known"] else None}
                                              for day, v in sorted(daily.items())]}}


@router.get("/sessions/{session_id}", response_model=SessionStatistics)
def session_statistics(
    session_id: UUID4, database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN)),
):
    session = get_session(database, str(session_id))
    course = require_session_access(database, session, user, read_only=True)
    records = list(database.scalars(select(Checkin).where(Checkin.session_id == session.id,
        Checkin.scheduled_deletion_at > utc_now()).limit(MAX_CHECKINS + 1)))
    if len(records) > MAX_CHECKINS:
        raise HTTPException(status_code=422, detail="report exceeds 10000 check-ins")
    summary = attendance(session, records)
    enrolled = summary["total_enrolled"]
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
    ).where(Checkin.session_id == session.id, Checkin.scheduled_deletion_at > utc_now())).one()
    by_status = dict(database.execute(select(Checkin.status, func.count()).where(
        Checkin.session_id == session.id, Checkin.scheduled_deletion_at > utc_now()).group_by(Checkin.status)).all())
    risk = database.execute(select(
        func.sum(case((Checkin.risk_score < .3, 1), else_=0)),
        func.sum(case(((Checkin.risk_score >= .3) & (Checkin.risk_score < .5), 1), else_=0)),
        func.sum(case((Checkin.risk_score >= .5, 1), else_=0)),
    ).where(Checkin.session_id == session.id, Checkin.scheduled_deletion_at > utc_now())).one()
    timeline = database.execute(select(bucket.label("minute"), func.count())
                                .where(Checkin.session_id == session.id, Checkin.scheduled_deletion_at > utc_now())
                                .group_by(bucket).order_by(bucket)).all()
    checked_in, average_risk, average_distance, average_minutes = aggregate
    return {
        "session_id": session.id, "session_name": session.name, "course_code": course.code,
        "scheduled_start": session.scheduled_start, "status": session.status,
        "total_enrolled": enrolled, "checked_in": checked_in,
        "attendance_rate": summary["attendance_rate"],
        "approved_attendance": summary["approved_attendance"],
        "coverage": {"available_from": (utc_now() - timedelta(days=30)).isoformat(),
                     "denominator_available": summary["denominator_available"]},
        "by_status": {name: int(by_status.get(name, 0)) for name in ("approved", "flagged", "rejected", "pending", "appealed")},
        "average_risk_score": round(float(average_risk or 0), 4),
        "average_distance_meters": round(float(average_distance or 0), 2),
        "average_checkin_time_minutes": round(float(average_minutes or 0), 2),
        "risk_distribution": {"low": risk[0] or 0, "medium": risk[1] or 0, "high": risk[2] or 0},
        "checkin_timeline": [{"minute": int(minute), "count": count} for minute, count in timeline],
    }


def _course_report(database, course, start_date=None, end_date=None):
    sessions, checkins, coverage = load_report(database, [course.id], start_date, end_date)
    grouped = _group(sessions, checkins)
    summaries = {s.id: attendance(s, grouped[s.id]) for s in sessions}
    current_ids = set(database.scalars(select(Enrollment.student_id).where(
        Enrollment.course_id == course.id, Enrollment.is_active.is_(True))))
    historical_ids = {sid for session in sessions for sid in session.attendance_roster or []}
    ids = current_ids | historical_ids
    if len(ids) > 10000:
        raise HTTPException(status_code=422, detail="report exceeds 10000 students")
    students = list(database.scalars(select(User).where(User.id.in_(ids)).order_by(User.full_name, User.id)))
    eligible_counts, attended_counts, risk_values = {}, {}, {}
    for session in sessions:
        for sid in set(session.attendance_roster or []):
            eligible_counts[sid] = eligible_counts.get(sid, 0) + 1
        for sid in ({c.student_id for c in grouped[session.id] if c.status == "approved"}
                    & set(session.attendance_roster or [])):
            attended_counts[sid] = attended_counts.get(sid, 0) + 1
    for checkin in checkins:
        risk_values.setdefault(checkin.student_id, []).append(checkin.risk_score)
    student_items = []
    for student in students:
        eligible = eligible_counts.get(student.id, 0)
        attended = attended_counts.get(student.id, 0)
        risks = risk_values.get(student.id, [])
        student_items.append({"student_id": student.id, "student_name": student.full_name,
            "sessions_attended": attended, "total_sessions": eligible,
            "attendance_rate": rate(attended, eligible) if coverage["denominator_available"] else None,
            "average_risk_score": round(sum(risks) / len(risks), 4) if risks else 0})
    known = coverage["denominator_available"]
    return {"course_id": course.id, "course_code": course.code, "course_name": course.name,
        "flagged_checkins": sum(c.status == "flagged" for c in checkins),
        "total_sessions": len(sessions), "total_enrolled": len(current_ids), "coverage": coverage,
        "overall_attendance_rate": rate(sum(v["approved_attendance"] or 0 for v in summaries.values()),
            sum(v["total_enrolled"] or 0 for v in summaries.values())) if known else None,
        "sessions": [{"session_id": s.id, "name": s.name, "date": business_day(s.scheduled_start),
            "attendance_rate": summaries[s.id]["attendance_rate"], "checked_in": len(grouped[s.id])} for s in sessions],
        "student_attendance": student_items,
        "low_attendance_alerts": [{"student_id": item["student_id"], "student_name": item["student_name"],
            "attendance_rate": item["attendance_rate"], "sessions_missed": item["total_sessions"] - item["sessions_attended"]}
            for item in student_items if item["attendance_rate"] is not None and item["attendance_rate"] < .75]}


@router.get("/courses/{course_id}", response_model=CourseStatistics)
def course_statistics(course_id: UUID4, start_date: datetime | None = None, end_date: datetime | None = None,
                      database: Session = Depends(get_db),
                      user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    course = get_course(database, str(course_id))
    require_course_access(database, course, user, allow_ta=False, read_only=True)
    return _course_report(database, course, start_date, end_date)


@router.get("/students/{student_id}", response_model=StudentStatistics)
def student_statistics(student_id: UUID4, database: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    student = database.get(User, str(student_id))
    if student is None or student.role != "student":
        raise HTTPException(status_code=404, detail="student not found")
    sessions, checkins, coverage = load_report(database, accessible_course_ids(user, read_only=True), student_id=student.id)
    current_ids = set(database.scalars(select(Enrollment.course_id).where(
        Enrollment.student_id == student.id, Enrollment.is_active.is_(True),
        Enrollment.course_id.in_(accessible_course_ids(user, read_only=True)))))
    by_id = {s.id: s for s in sessions}
    historical_ids = {s.course_id for s in sessions if student.id in (s.attendance_roster or [])}
    historical_ids.update(by_id[c.session_id].course_id for c in checkins)
    courses = list(database.scalars(select(Course).where(Course.id.in_(current_ids | historical_ids))
        .order_by(Course.code).limit(101)))
    if len(courses) > 100:
        raise HTTPException(status_code=422, detail="student report exceeds 100 courses")
    reports = []
    for course in courses:
        relevant = [s for s in sessions if s.course_id == course.id]
        eligible = {s.id for s in relevant if student.id in (s.attendance_roster or [])}
        records = [c for c in checkins if c.session_id in {s.id for s in relevant}]
        attended = len({c.session_id for c in records if c.status == "approved" and c.session_id in eligible})
        known = all(s.attendance_roster is not None for s in relevant)
        reports.append({"course_id":course.id,"course_code":course.code,"student_id":student.id,
            "student_name":student.full_name,"sessions_attended":attended,"total_sessions":len(eligible),
            "attendance_rate":rate(attended,len(eligible)) if known else None,
            "average_risk_score":round(sum(c.risk_score for c in records)/len(records),4) if records else 0})
    codes = {course.id:course.code for course in courses}
    recent = sorted(checkins,key=lambda c:as_utc(c.checked_in_at),reverse=True)[:20]
    coverage["denominator_available"] = all(item["attendance_rate"] is not None for item in reports)
    coverage["current_enrolled_courses"] = len(current_ids)
    return {"student_id": student.id, "student_name": student.full_name, "student_email": student.email,
        "courses": reports, "coverage": coverage,
        "recent_checkins": [{"session_name":by_id[c.session_id].name,
            "course_code":codes[by_id[c.session_id].course_id],"checked_in_at":c.checked_in_at,"status":c.status}
            for c in recent]}
