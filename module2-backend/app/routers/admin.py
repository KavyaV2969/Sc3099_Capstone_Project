"""Minimum administration endpoints required for Week 2 account management."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import require_roles
from app.models import User
from app.schemas import AdminActionResponse, UserRole

router = APIRouter(prefix="/admin", tags=["administration"])
admin_only = require_roles(UserRole.ADMIN)


def _set_account_status(
    user_id: str,
    active: bool,
    request: Request,
    database: Session,
) -> AdminActionResponse:
    user = database.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    user.is_active = active
    write_audit_log(
        database,
        request,
        action="user_activated" if active else "user_deactivated",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    database.commit()
    return AdminActionResponse(message=f"User {'activated' if active else 'deactivated'} successfully")


@router.patch("/users/{user_id}/deactivate", response_model=AdminActionResponse)
def deactivate_user(
    user_id: str,
    request: Request,
    database: Session = Depends(get_db),
    _: User = Depends(admin_only),
) -> AdminActionResponse:
    return _set_account_status(user_id, False, request, database)


@router.patch("/users/{user_id}/activate", response_model=AdminActionResponse)
def activate_user(
    user_id: str,
    request: Request,
    database: Session = Depends(get_db),
    _: User = Depends(admin_only),
) -> AdminActionResponse:
    return _set_account_status(user_id, True, request, database)
