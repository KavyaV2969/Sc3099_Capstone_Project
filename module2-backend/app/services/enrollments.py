"""Enrollment validation shared by ordinary, bulk, and admin routes."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Enrollment, User


def create_enrollment(database: Session, *, student_id: str, course_id: str) -> Enrollment:
    student = database.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    if student.role != "student":
        raise HTTPException(status_code=400, detail="user is not a student")
    if not student.is_active:
        raise HTTPException(status_code=400, detail="student account is inactive")
    course = database.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    existing = database.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == course_id,
        ).with_for_update()
    )
    if existing is not None:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="student already enrolled")
        existing.is_active = True
        return existing
    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    database.add(enrollment)
    database.flush()
    return enrollment
