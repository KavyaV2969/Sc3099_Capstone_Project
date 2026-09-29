"""User profile, directory, and face-enrollment routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import UUID4
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.face_service import enroll_face
from app.models import User, Device, utc_now
from datetime import timedelta
from app.schemas import (
    FaceEnrollmentCreate, FaceEnrollmentResponse, UserAdminUpdate, UserListResponse,
    UserProfileUpdate, UserResponse, UserRole, as_utc,
)
from app.services.access import instructor_has_student_relationship

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/me/face/enroll", response_model=FaceEnrollmentResponse)
async def enroll_my_face(
    payload: FaceEnrollmentCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> FaceEnrollmentResponse:
    def prepare():
        if not current_user.camera_consent:
            raise HTTPException(status_code=400, detail="camera consent is required")
        user_id = current_user.id
        database.commit()
        return user_id
    user_id = await run_in_threadpool(prepare)
    result = await enroll_face(user_id, payload.image)
    if not result.enrollment_successful or not result.face_template_hash:
        raise HTTPException(status_code=400, detail="face enrollment failed")
    return await run_in_threadpool(_finish_face_enrollment, database, request, user_id, result)


def _finish_face_enrollment(database, request, user_id, result):
    current_user = database.scalar(select(User).where(User.id == user_id).with_for_update()
                                   .execution_options(populate_existing=True))
    if current_user is None or not current_user.is_active:
        raise HTTPException(status_code=401, detail="account is unavailable")
    if not current_user.camera_consent:
        raise HTTPException(status_code=400, detail="camera consent is required")
    current_user.face_enrolled = True
    current_user.face_embedding_hash = result.face_template_hash.lower()
    write_audit_log(
        database, request, action="face_enrolled", user_id=current_user.id,
        resource_type="user", resource_id=current_user.id,
    )
    database.commit()
    return FaceEnrollmentResponse(
        success=True, message="Face enrolled successfully", face_enrolled=True,
        quality_score=result.quality_score,
    )


@router.get("/", response_model=UserListResponse)
def list_users(
    role: UserRole | None = None,
    is_active: bool | None = None,
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    database: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserListResponse:
    filters = []
    if role is not None:
        filters.append(User.role == role.value)
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
    total = database.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    items = database.scalars(
        select(User).where(*filters).order_by(User.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return UserListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID4,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    user = database.get(User, str(user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    allowed = current_user.id == user.id or current_user.role == "admin"
    if current_user.role == "instructor" and current_user.id != user.id:
        allowed = instructor_has_student_relationship(database, current_user, user.id)
    if not allowed:
        raise HTTPException(status_code=403, detail="insufficient permissions")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID4,
    payload: UserAdminUpdate,
    request: Request,
    database: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    user = database.scalar(select(User).where(User.id == str(user_id)).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_active") is True and (user.activation_token_hash or user.scheduled_deletion_at):
        raise HTTPException(status_code=400, detail="pending activation or deletion cannot be overridden")
    for field, value in changes.items():
        setattr(user, field, value.value if isinstance(value, UserRole) else value)
    if changes.get("is_active") is True:
        user.failed_login_attempts = 0
    write_audit_log(
        database, request, action="user_updated", user_id=admin.id,
        resource_type="user", resource_id=user.id,
        details={"fields": sorted(changes)},
    )
    database.commit()
    database.refresh(user)
    return user


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> User:
    current_user = database.scalar(select(User).where(User.id == current_user.id).with_for_update()
                                   .execution_options(populate_existing=True))
    changed_fields = payload.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(current_user, field, value)
    if changed_fields.get("camera_consent") is False:
        current_user.face_enrolled, current_user.face_embedding_hash = False, None
    write_audit_log(
        database,
        request,
        action="user_updated",
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        details={"fields": ",".join(sorted(changed_fields))},
    )
    database.commit()
    database.refresh(current_user)
    return current_user


@router.delete("/me")
def schedule_deletion(request: Request, current_user: User = Depends(get_current_user),
                      database: Session = Depends(get_db)):
    user = database.scalar(select(User).where(User.id == current_user.id).with_for_update()
                           .execution_options(populate_existing=True))
    if user.scheduled_deletion_at is None:
        user.scheduled_deletion_at = utc_now() + timedelta(days=30)
        user.is_active, user.camera_consent, user.geolocation_consent = False, False, False
        user.face_enrolled, user.face_embedding_hash = False, None
        user.activation_token_hash = user.activation_expires_at = None
        database.execute(update(Device).where(Device.user_id == user.id).values(
            is_active=False, is_trusted=False, trust_score="low", revoked_at=utc_now()))
        write_audit_log(database, request, action="user_deletion_requested", user_id=user.id,
                        resource_type="user", resource_id=user.id)
        database.commit()
    return {"scheduled_deletion_at": as_utc(user.scheduled_deletion_at), "is_active": False}
