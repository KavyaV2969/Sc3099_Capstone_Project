"""Course administration using the existing auth and audit dependencies."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, get_course_or_404, require_roles
from app.models import Course, User
from app.schemas import CourseCreate, CourseListResponse, CourseResponse, CourseUpdate, UserRole

router = APIRouter(prefix="/courses", tags=["courses"])


def course_response(database: Session, course: Course) -> CourseResponse:
    result = CourseResponse.model_validate(course)
    if course.instructor_id:
        result.instructor_name = database.get(User, course.instructor_id).full_name
    return result


def validate_instructor(database: Session, instructor_id: str) -> None:
    instructor = database.get(User, instructor_id)
    if instructor is None:
        raise HTTPException(status_code=404, detail="instructor not found")
    if instructor.role != "instructor" or not instructor.is_active:
        raise HTTPException(status_code=400, detail="an active instructor is required")


@router.get("/", response_model=CourseListResponse)
def list_courses(
    is_active: bool = True, semester: str | None = None, instructor_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user), database: Session = Depends(get_db),
):
    query = select(Course).where(Course.is_active == is_active)
    if semester is not None:
        query = query.where(Course.semester == semester)
    if instructor_id is not None:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="instructor filter requires admin")
        query = query.where(Course.instructor_id == str(instructor_id))
    total = database.scalar(select(func.count()).select_from(query.subquery()))
    courses = database.scalars(query.order_by(Course.code).offset(offset).limit(limit)).all()
    return {"items": [course_response(database, course) for course in courses],
            "total": total, "limit": limit, "offset": offset}


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(course_id: UUID, current_user: User = Depends(get_current_user),
               database: Session = Depends(get_db)):
    return course_response(database, get_course_or_404(database, str(course_id)))


@router.post("/", response_model=CourseResponse, status_code=201)
def create_course(payload: CourseCreate, request: Request,
                  current_user: User = Depends(require_roles(UserRole.ADMIN)),
                  database: Session = Depends(get_db)):
    if payload.instructor_id is not None:
        validate_instructor(database, str(payload.instructor_id))
    course = Course(**payload.model_dump(mode="json"))
    database.add(course)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="course code already exists") from None
    write_audit_log(database, request, action="course_created", user_id=current_user.id,
                    resource_type="course", resource_id=course.id)
    database.commit()
    database.refresh(course)
    return course_response(database, course)


@router.put("/{course_id}", response_model=CourseResponse)
def update_course(course_id: UUID, payload: CourseUpdate, request: Request,
                  current_user: User = Depends(require_roles(UserRole.ADMIN)),
                  database: Session = Depends(get_db)):
    course = get_course_or_404(database, str(course_id))
    changes = payload.model_dump(mode="json", exclude_unset=True)
    if changes.get("instructor_id") is not None:
        validate_instructor(database, changes["instructor_id"])
    for field, value in changes.items():
        setattr(course, field, value)
    write_audit_log(database, request, action="course_updated", user_id=current_user.id,
                    resource_type="course", resource_id=course.id)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="course code already exists") from None
    database.refresh(course)
    return course_response(database, course)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: UUID, request: Request,
                  current_user: User = Depends(require_roles(UserRole.ADMIN)),
                  database: Session = Depends(get_db)):
    course = get_course_or_404(database, str(course_id))
    course.is_active = False
    write_audit_log(database, request, action="course_deleted", user_id=current_user.id,
                    resource_type="course", resource_id=course.id)
    database.commit()
    return Response(status_code=204)
