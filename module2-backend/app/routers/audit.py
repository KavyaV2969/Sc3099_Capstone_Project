"""Read-only audit-log route for administrators."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_roles
from app.models import AuditLog, User
from app.schemas import AuditLogResponse, UserRole

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    database: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    return list(database.scalars(statement))
