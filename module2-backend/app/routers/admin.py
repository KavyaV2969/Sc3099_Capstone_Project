"""Administrative user, session, and enrollment operations."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import require_roles
from app.models import Session as AttendanceSession
from app.models import User
from app.schemas import (
    AdminActionResponse, AdminSessionStatusResponse, AdminSessionStatusUpdate,
    BulkUserCreate, BulkUserError, BulkUserItem, BulkUserResponse, EnrollmentCreate,
    EnrollmentResponse, UserRole,
)
from app.security import hash_password
from app.services.enrollments import create_enrollment

router = APIRouter(prefix="/admin", tags=["administration"])
admin_only = require_roles(UserRole.ADMIN)


def _set_account_status(
    user_id: UUID4,
    active: bool,
    request: Request,
    database: Session,
    actor: User,
) -> AdminActionResponse:
    user = database.scalar(select(User).where(User.id == str(user_id)).with_for_update())
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    user.is_active = active
    if active:
        user.failed_login_attempts = 0
    write_audit_log(
        database,
        request,
        action="user_activated" if active else "user_deactivated",
        user_id=actor.id,
        resource_type="user",
        resource_id=user.id,
    )
    database.commit()
    return AdminActionResponse(
        id=user.id, email=user.email, is_active=user.is_active,
        message=f"User {'activated' if active else 'deactivated'} successfully",
    )


@router.patch("/users/{user_id}/deactivate", response_model=AdminActionResponse)
def deactivate_user(
    user_id: UUID4,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> AdminActionResponse:
    return _set_account_status(user_id, False, request, database, admin)


@router.patch("/users/{user_id}/activate", response_model=AdminActionResponse)
def activate_user(
    user_id: UUID4,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> AdminActionResponse:
    return _set_account_status(user_id, True, request, database, admin)


@router.post("/users/bulk", response_model=BulkUserResponse, status_code=status.HTTP_201_CREATED)
def bulk_create_users(
    payload: BulkUserCreate,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> BulkUserResponse:
    existing = set(database.scalars(select(User.email).where(User.email.in_([str(u.email) for u in payload.users]))))
    seen: set[str] = set()
    created: list[BulkUserItem] = []
    errors: list[BulkUserError] = []
    for index, item in enumerate(payload.users):
        email = str(item.email)
        if email in existing or email in seen:
            errors.append(BulkUserError(index=index, email=email, error="email already registered"))
            continue
        user = User(
            email=email, full_name=item.full_name, hashed_password=hash_password(item.password),
            role=item.role.value,
        )
        try:
            with database.begin_nested():
                database.add(user)
                database.flush()
            created.append(BulkUserItem.model_validate(user, from_attributes=True))
            seen.add(email)
        except IntegrityError:
            errors.append(BulkUserError(index=index, email=email, error="email already registered"))
    write_audit_log(
        database, request, action="users_bulk_created", user_id=admin.id,
        resource_type="user", details={"created": len(created), "failed": len(errors)},
    )
    database.commit()
    return BulkUserResponse(created=len(created), failed=len(errors), users=created, errors=errors)


@router.patch("/sessions/{session_id}/status", response_model=AdminSessionStatusResponse)
def set_session_status(
    session_id: UUID4,
    payload: AdminSessionStatusUpdate,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> AdminSessionStatusResponse:
    session = database.scalar(select(AttendanceSession).where(AttendanceSession.id == str(session_id)).with_for_update())
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    previous = session.status
    session.status = payload.status.value
    write_audit_log(
        database, request, action="session_status_updated", user_id=admin.id,
        resource_type="session", resource_id=session.id,
        details={"from": previous, "to": session.status},
    )
    database.commit()
    return AdminSessionStatusResponse(
        id=session.id, name=session.name, status=session.status,
        message=f"Session status changed from '{previous}' to '{session.status}'",
    )


@router.post("/enrollments/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def admin_create_enrollment(
    payload: EnrollmentCreate,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    enrollment = create_enrollment(
        database, student_id=str(payload.student_id), course_id=str(payload.course_id)
    )
    write_audit_log(
        database, request, action="student_enrolled", user_id=admin.id,
        resource_type="enrollment", resource_id=enrollment.id,
    )
    database.commit()
    database.refresh(enrollment)
    return enrollment
