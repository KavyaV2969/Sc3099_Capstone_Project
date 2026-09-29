"""Student enrollments and course rosters."""
from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import UUID4
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.config import get_settings
from app.db import get_db
from app.dependencies import get_course_or_404, require_course_access, require_roles
from app.models import Course, Enrollment, User, utc_now
from app.security import hash_password
from app.schemas import (BulkEnrollmentCreate, BulkEnrollmentResponse, CourseEnrollmentsResponse,
                         EnrollmentCreate, EnrollmentResponse, MyEnrollmentResponse, UserRole)
from app.services.enrollments import create_enrollment as create_enrollment_record
from app.services.access import get_course

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("/my-enrollments", response_model=list[MyEnrollmentResponse])
def my_enrollments(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                   current_user: User = Depends(require_roles(UserRole.STUDENT)),
                   database: Session = Depends(get_db)):
    rows = database.execute(
        select(Enrollment, Course).join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True),
               Course.is_active.is_(True)).order_by(Course.code).limit(limit).offset(offset)
    ).all()
    return [{**EnrollmentResponse.model_validate(enrollment).model_dump(),
             "course_code": course.code, "course_name": course.name,
             "semester": course.semester}
            for enrollment, course in rows]


@router.get("/course/{course_id}", response_model=CourseEnrollmentsResponse)
def course_enrollments(course_id: UUID4, is_active: bool = True, search: str | None = None,
                       limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                       current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN)),
                       database: Session = Depends(get_db)):
    course = get_course_or_404(database, str(course_id))
    require_course_access(database, course, current_user, allow_ta=True, read_only=True)
    query = select(Enrollment, User).join(User, Enrollment.student_id == User.id).where(
        Enrollment.course_id == course.id, Enrollment.is_active == is_active)
    if search:
        query = query.where(or_(User.full_name.icontains(search, autoescape=True),
                                User.email.icontains(search, autoescape=True)))
    total = database.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = database.execute(query.order_by(User.full_name, User.id).limit(limit).offset(offset)).all()
    return {"course_id": course.id, "course_code": course.code, "total_enrolled": total,
            "limit": limit, "offset": offset,
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
    require_course_access(database, course, current_user)
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
    response: Response,
    current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
    database: Session = Depends(get_db),
):
    course = get_course_or_404(database, str(payload.course_id))
    require_course_access(database, course, current_user, allow_ta=False)
    if not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    # Two creating batches in opposite email order must not deadlock on unique emails.
    if payload.create_accounts and database.get_bind().dialect.name == "postgresql":
        database.execute(text("SELECT pg_advisory_xact_lock(309931)"))
    users = {
        user.email: user for user in database.scalars(
            select(User).where(User.email.in_(payload.student_emails))
            .order_by(User.id).with_for_update()
        )
    }
    course = get_course(database, course.id, lock=True)
    require_course_access(database, course, current_user, allow_ta=False)
    if not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    details = []
    counters = {"enrolled": 0, "already_enrolled": 0, "not_found": 0, "created": 0}
    processed: dict[str, str] = {}
    for email in payload.student_emails:
        activation = {}
        if email in processed:
            outcome = "already_enrolled" if processed[email] == "enrolled" else processed[email]
        else:
            student = users.get(email)
            if student is None and not payload.create_accounts:
                outcome = "not_found"
            else:
                try:
                    with database.begin_nested():
                        created = student is None
                        if created:
                            token = token_urlsafe(32)
                            expiry = utc_now() + timedelta(hours=24)
                            student = User(email=email, full_name=email.split("@", 1)[0], role="student",
                                           hashed_password=hash_password(token_urlsafe(32)), is_active=False,
                                           activation_token_hash=sha256(token.encode()).hexdigest(),
                                           activation_expires_at=expiry)
                            database.add(student)
                            database.flush()
                        create_enrollment_record(database, student_id=student.id, course_id=course.id,
                                                 allow_pending_activation=created)
                        if created:
                            write_audit_log(database, request, action="user_created", user_id=current_user.id,
                                            resource_type="user", resource_id=student.id,
                                            details={"method": "bulk_activation"})
                    if created:
                        counters["created"] += 1
                        users[email] = student
                        activation = {"activation_url": get_settings().public_frontend_url.rstrip("/")
                                      + "/activate?" + urlencode({"token": token}),
                                      "activation_expires_at": expiry}
                    outcome = "enrolled"
                except IntegrityError:
                    # A concurrent creator/enroller won. The savepoint rolled back this row.
                    existing = database.scalar(select(Enrollment.id).join(User, User.id == Enrollment.student_id)
                                               .where(User.email == email, Enrollment.course_id == course.id,
                                                      Enrollment.is_active.is_(True)))
                    outcome = "already_enrolled" if existing else "not_found"
                except HTTPException as exc:
                    outcome = "already_enrolled" if exc.status_code == 400 and "already" in str(exc.detail) else "not_found"
            processed[email] = outcome
        counters[outcome] += 1
        details.append({"email": email, "status": outcome, **activation})
    write_audit_log(
        database, request, action="enrollment_bulk_added", user_id=current_user.id,
        resource_type="course", resource_id=course.id, details=counters,
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return {**counters, "details": details}


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
