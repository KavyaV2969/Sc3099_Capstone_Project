"""Audit-log helper shared by authentication and profile routes."""

import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit_log(
    database: Session,
    request: Request,
    *,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, str] | None = None,
    success: bool = True,
) -> AuditLog:
    """Stage an immutable audit event in the current transaction."""
    event = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        details=json.dumps(details) if details else None,
        success=success,
    )
    database.add(event)
    return event
