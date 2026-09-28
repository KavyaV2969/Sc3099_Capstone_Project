"""Student enrollments and course rosters."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import UUID4
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_course_or_404, require_course_access, require_roles
from app.models import Course, Enrollment, User
from app.schemas import (BulkEnrollmentCreate, BulkEnrollmentResponse, CourseEnrollmentsResponse,
                         EnrollmentCreate, EnrollmentResponse, MyEnrollmentResponse, UserRole)
from app.services.enrollments import create_enrollment as create_enrollment_record

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("/my-enrollments", response_model=list[MyEnrollmentResponse])
def my_enrollments(current_user: User = Depends(require_roles(UserRole.STUDENT)),
                   database: Session = Depends(get_db)):
    rows = database.execute(
        select(Enrollment, Course).join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True),
               Course.is_active.is_(True)).order_by(Course.code)
    ).all()
    return [{**EnrollmentResponse.model_validate(enrollment).model_dump(),
             "course_code": course.code, "course_name": course.name,
             "semester": course.semester}
            for enrollment, course in rows]


@router.get("/course/{course_id}", response_model=CourseEnrollmentsResponse)
def course_enrollments(course_id: UUID4, is_active: bool = True, search: str | None = None,
                       current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN)),
                       database: Session = Depends(get_db)):
    course = get_course_or_404(database, str(course_id))
    require_course_access(database, course, current_user, allow_ta=True)
    query = select(Enrollment, User).join(User, Enrollment.student_id == User.id).where(
        Enrollment.course_id == course.id, Enrollment.is_active == is_active)
    if search:
        query = query.where(or_(User.full_name.icontains(search, autoescape=True),
                                User.email.icontains(search, autoescape=True)))
    rows = database.execute(query.order_by(User.full_name, User.id)).all()
    return {"course_id": course.id, "course_code": course.code, "total_enrolled": len(rows),
            "students": [{"id": enrollment.id, "student_id": student.id,
                          "student_email": student.email, "student_name": student.full_name,
                          "enrolled_at": enrollment.enrolled_at, "is_active": enrollment.is_active,
                          "face_enrolled": student.face_enrolled} for enrollment, student in rows]}


@router.post("/", response_model=EnrollmentResponse, status_code=201)
def create_enrollment(payload: EnrollmentCreate, request: Request,
                      current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
                      database: Session = Depends(get_db)):
    course = get_course_or_404(database, str(payload.course_id))
    require_course_access(database, course, current_user)
    if not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    enrollment = create_enrollment_record(
        database, student_id=str(payload.student_id), course_id=course.id
    )
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="student already enrolled") from None
    write_audit_log(database, request, action="enrollment_added", user_id=current_user.id,
                    resource_type="enrollment", resource_id=enrollment.id)
    database.commit()
    database.refresh(enrollment)
    return enrollment


@router.post("/bulk", response_model=BulkEnrollmentResponse)
def bulk_enroll(
    payload: BulkEnrollmentCreate,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
    database: Session = Depends(get_db),
):
    if payload.create_accounts:
        raise HTTPException(
            status_code=422,
            detail="create_accounts is unsupported because no secure credential recovery contract exists",
        )
    course = get_course_or_404(database, str(payload.course_id))
    require_course_access(database, course, current_user, allow_ta=False)
    users = {
        user.email: user for user in database.scalars(
            select(User).where(User.email.in_(payload.student_emails))
        )
    }
    details = []
    counters = {"enrolled": 0, "already_enrolled": 0, "not_found": 0}
    processed: set[str] = set()
    for email in payload.student_emails:
        if email in processed:
            outcome = "already_enrolled"
        else:
            processed.add(email)
            student = users.get(email)
            if student is None or student.role != "student":
                outcome = "not_found"
            else:
                try:
                    with database.begin_nested():
                        create_enrollment_record(database, student_id=student.id, course_id=course.id)
                    outcome = "enrolled"
                except HTTPException as exc:
                    outcome = "already_enrolled" if exc.status_code == 400 and "already" in str(exc.detail) else "not_found"
        counters[outcome] += 1
        details.append({"email": email, "status": outcome})
    write_audit_log(
        database, request, action="enrollment_bulk_added", user_id=current_user.id,
        resource_type="course", resource_id=course.id, details=counters,
    )
    database.commit()
    return {**counters, "created": 0, "details": details}


@router.delete("/{enrollment_id}", status_code=204)
def delete_enrollment(enrollment_id: UUID4, request: Request,
                      current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
                      database: Session = Depends(get_db)):
    enrollment = database.get(Enrollment, str(enrollment_id))
    if enrollment is None:
        raise HTTPException(status_code=404, detail="enrollment not found")
    course = get_course_or_404(database, enrollment.course_id)
    require_course_access(database, course, current_user)
    write_audit_log(database, request, action="enrollment_removed", user_id=current_user.id,
                    resource_type="enrollment", resource_id=enrollment.id)
    database.delete(enrollment)
    database.commit()
    return Response(status_code=204)
