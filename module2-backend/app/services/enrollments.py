"""Enrollment validation shared by ordinary, bulk, and admin routes."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Checkin, Course, Enrollment, Session as AttendanceSession, User, utc_now
from app.schemas import as_utc


def capture_roster(database: Session, session: AttendanceSession) -> None:
    """Capture once; status resets and withdrawals do not rewrite history."""
    if session.attendance_roster is None:
        # Never reconstruct attendance history from today's enrollment after a reset.
        resets = database.scalars(select(AuditLog).where(
            AuditLog.resource_id == session.id, AuditLog.resource_type == "session",
            AuditLog.action == "session_status_updated"))
        if (as_utc(session.checkin_closes_at) < utc_now()
            or any(isinstance(event.details, dict) and event.details.get("from") in {"active", "closed", "cancelled"}
                   for event in resets)
            or database.scalar(select(Checkin.id).where(Checkin.session_id == session.id).limit(1))):
            return
        session.attendance_roster = sorted(database.scalars(select(Enrollment.student_id)
            .join(User, User.id == Enrollment.student_id).where(Enrollment.course_id == session.course_id,
                Enrollment.is_active.is_(True), User.is_active.is_(True), User.role == "student")))


def include_in_active_rosters(database: Session, student_id: str, course_id: str) -> None:
    for session in database.scalars(select(AttendanceSession).where(
        AttendanceSession.course_id == course_id, AttendanceSession.status == "active")
        .order_by(AttendanceSession.id).with_for_update()):
        if session.attendance_roster is not None and student_id not in session.attendance_roster:
            session.attendance_roster = sorted([*session.attendance_roster, student_id])


def create_enrollment(database: Session, *, student_id: str, course_id: str,
                      allow_pending_activation: bool = False) -> Enrollment:
    student = database.scalar(select(User).where(User.id == student_id).with_for_update()
                              .execution_options(populate_existing=True))
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    if student.role != "student":
        raise HTTPException(status_code=400, detail="user is not a student")
    if not student.is_active and not (allow_pending_activation and student.activation_token_hash):
        raise HTTPException(status_code=400, detail="student account is inactive")
    course = database.scalar(select(Course).where(Course.id == course_id).with_for_update()
                             .execution_options(populate_existing=True))
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    if not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    existing = database.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == course_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if existing is not None:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="student already enrolled")
        existing.is_active = True
        if student.is_active:
            include_in_active_rosters(database, student_id, course_id)
        return existing
    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    try:
        with database.begin_nested():
            database.add(enrollment)
            database.flush()
            if student.is_active:
                include_in_active_rosters(database, student_id, course_id)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="student already enrolled") from None
    return enrollment
