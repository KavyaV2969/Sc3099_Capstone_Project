"""Read-only audit-log route for administrators."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import UUID4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.models import AuditLog, User
from app.schemas import AuditLogListResponse, AuditLogResponse, UserRole, as_utc

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/", response_model=AuditLogListResponse)
def list_audit_logs(
    user_id: UUID4 | None = None,
    action: str | None = Query(default=None, max_length=100),
    resource_type: str | None = Query(default=None, max_length=50),
    resource_id: UUID4 | None = None,
    success: bool | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    database: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    filters = []
    if user_id: filters.append(AuditLog.user_id == str(user_id))
    if action: filters.append(AuditLog.action == action)
    if resource_type: filters.append(AuditLog.resource_type == resource_type)
    if resource_id: filters.append(AuditLog.resource_id == str(resource_id))
    if success is not None: filters.append(AuditLog.success.is_(success))
    if start_date: filters.append(AuditLog.timestamp >= as_utc(start_date))
    if end_date: filters.append(AuditLog.timestamp <= as_utc(end_date))
    total = database.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = database.execute(
        select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
        .where(*filters).order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        {**AuditLogResponse.model_validate(log).model_dump(), "user_email": email}
        for log, email in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
