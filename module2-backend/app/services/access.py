"""Central resource lookup and ownership policy."""

from fastapi import HTTPException
from sqlalchemy import exists, select, or_
from sqlalchemy.orm import Session

from app.models import Checkin, Course, CourseTA, Enrollment, Session as AttendanceSession, User


def get_course(database: Session, course_id: str, *, lock: bool = False) -> Course:
    statement = select(Course).where(Course.id == course_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    course = database.scalar(statement)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    return course


def get_session(database: Session, session_id: str, *, lock: bool = False) -> AttendanceSession:
    statement = select(AttendanceSession).where(AttendanceSession.id == session_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    session = database.scalar(statement)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def get_session_for_mutation(database: Session, session_id: str) -> AttendanceSession:
    """Serialize roster activation with enrollment; course precedes session locks."""
    session = get_session(database, session_id)
    get_course(database, session.course_id, lock=True)
    return get_session(database, session_id, lock=True)


def get_checkin(database: Session, checkin_id: str, *, lock: bool = False) -> Checkin:
    statement = select(Checkin).where(Checkin.id == checkin_id)
    if lock:
        statement = statement.with_for_update()
    checkin = database.scalar(statement)
    if checkin is None:
        raise HTTPException(status_code=404, detail="check-in not found")
    return checkin


def can_manage_course(database: Session, course: Course, user: User, *, allow_ta: bool = True, read_only: bool = False) -> bool:
    if user.role == "admin" or (read_only and user.role == "instructor"):
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


def accessible_course_ids(user: User, *, read_only: bool = False):
    """Read scope may include all instructor data; mutation scope stays taught courses."""
    query = select(Course.id)
    if user.role == "admin" or (read_only and user.role == "instructor"):
        return query
    if user.role == "instructor":
        return query.where(or_(Course.instructor_id == user.id, exists().where(
            AttendanceSession.course_id == Course.id,
            AttendanceSession.instructor_id == user.id,
        )))
    return query.where(Course.id.in_(select(CourseTA.course_id).where(CourseTA.ta_id == user.id)))


def require_course_access(database: Session, course: Course, user: User, *, allow_ta: bool = True, read_only: bool = False) -> None:
    if not can_manage_course(database, course, user, allow_ta=allow_ta, read_only=read_only):
        raise HTTPException(status_code=403, detail="insufficient course permissions")


def require_session_access(database: Session, session: AttendanceSession, user: User, *, allow_ta: bool = True, read_only: bool = False) -> Course:
    course = get_course(database, session.course_id)
    require_course_access(database, course, user, allow_ta=allow_ta, read_only=read_only)
    return course


def require_checkin_access(database: Session, checkin: Checkin, user: User, *, read_only: bool = False) -> AttendanceSession:
    session = get_session(database, checkin.session_id)
    if user.role == "student" and checkin.student_id == user.id:
        return session
    require_session_access(database, session, user, read_only=read_only)
    return session


def instructor_has_student_relationship(database: Session, instructor: User, student_id: str, *, read_only: bool = False) -> bool:
    if instructor.role == "admin":
        return True
    if read_only and instructor.role == "instructor":
        return database.scalar(select(User.id).where(User.id == student_id, User.role == "student")) is not None
    if instructor.role not in {"instructor", "ta"}:
        return False
    statement = (
        select(Enrollment.id)
        .join(Course, Course.id == Enrollment.course_id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.is_active.is_(True),
            Enrollment.course_id.in_(accessible_course_ids(instructor)),
        )
        .limit(1)
    )
    return database.scalar(statement) is not None
