"""Current-user profile and consent routes."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import UserProfileUpdate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> User:
    changed_fields = payload.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(current_user, field, value)
    write_audit_log(
        database,
        request,
        action="profile_updated",
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        details={"fields": ",".join(sorted(changed_fields))},
    )
    database.commit()
    database.refresh(current_user)
    return current_user
