"""Reusable joined check-in query and response projection."""

from sqlalchemy import select

from app.models import Checkin, Course, Device, Session as AttendanceSession, User
from app.schemas import CheckinResponse


def checkin_query():
    return (
        select(
            Checkin, AttendanceSession.name, User.full_name, User.email,
            Course.code, Device.is_trusted,
        )
        .join(AttendanceSession, AttendanceSession.id == Checkin.session_id)
        .join(Course, Course.id == AttendanceSession.course_id)
        .join(User, User.id == Checkin.student_id)
        .outerjoin(Device, Device.id == Checkin.device_id)
    )


def serialize_checkin(row) -> dict:
    checkin, session_name, student_name, student_email, course_code, device_trusted = row
    data = CheckinResponse.model_validate(checkin).model_dump()
    data.update(
        session_name=session_name,
        student_name=student_name,
        student_email=student_email,
        course_code=course_code,
        device_trusted=device_trusted,
    )
    return data
