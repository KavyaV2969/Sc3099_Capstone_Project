"""Central resource lookup and ownership policy."""

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Checkin, Course, CourseTA, Enrollment, Session as AttendanceSession, User


def get_course(database: Session, course_id: str, *, lock: bool = False) -> Course:
    statement = select(Course).where(Course.id == course_id)
    if lock:
        statement = statement.with_for_update()
    course = database.scalar(statement)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    return course


def get_session(database: Session, session_id: str, *, lock: bool = False) -> AttendanceSession:
    statement = select(AttendanceSession).where(AttendanceSession.id == session_id)
    if lock:
        statement = statement.with_for_update()
    session = database.scalar(statement)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def get_checkin(database: Session, checkin_id: str, *, lock: bool = False) -> Checkin:
    statement = select(Checkin).where(Checkin.id == checkin_id)
    if lock:
        statement = statement.with_for_update()
    checkin = database.scalar(statement)
    if checkin is None:
        raise HTTPException(status_code=404, detail="check-in not found")
    return checkin


def can_manage_course(database: Session, course: Course, user: User, *, allow_ta: bool = True) -> bool:
    if user.role == "admin":
        return True
    if user.role == "instructor" and (
        course.instructor_id == user.id
        or database.scalar(
            select(exists().where(
                AttendanceSession.course_id == course.id,
                AttendanceSession.instructor_id == user.id,
            ))
        )
    ):
        return True
    return bool(allow_ta and user.role == "ta" and database.get(CourseTA, (course.id, user.id)))


def require_course_access(database: Session, course: Course, user: User, *, allow_ta: bool = True) -> None:
    if not can_manage_course(database, course, user, allow_ta=allow_ta):
        raise HTTPException(status_code=403, detail="insufficient course permissions")


def require_session_access(database: Session, session: AttendanceSession, user: User, *, allow_ta: bool = True) -> Course:
    course = get_course(database, session.course_id)
    require_course_access(database, course, user, allow_ta=allow_ta)
    return course


def require_checkin_access(database: Session, checkin: Checkin, user: User) -> AttendanceSession:
    session = get_session(database, checkin.session_id)
    if user.role == "student" and checkin.student_id == user.id:
        return session
    require_session_access(database, session, user)
    return session


def instructor_has_student_relationship(database: Session, instructor: User, student_id: str) -> bool:
    if instructor.role == "admin":
        return True
    if instructor.role not in {"instructor", "ta"}:
        return False
    statement = (
        select(Enrollment.id)
        .join(Course, Course.id == Enrollment.course_id)
        .outerjoin(CourseTA, CourseTA.course_id == Course.id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.is_active.is_(True),
            (Course.instructor_id == instructor.id) | (CourseTA.ta_id == instructor.id),
        )
        .limit(1)
    )
    return database.scalar(statement) is not None
