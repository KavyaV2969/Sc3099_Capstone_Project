"""Audit schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, UUID4


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    user_id: UUID4 | None = None
    user_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: UUID4 | None = None
    device_id: UUID4 | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] | list[Any] | str | None = None
    success: bool
    timestamp: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int
