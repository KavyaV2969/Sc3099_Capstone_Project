"""Shared enums, constrained values, and pagination types."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class UserRole(str, Enum):
    STUDENT = "student"
    TA = "ta"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class SessionStatus(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SessionType(str, Enum):
    LECTURE = "lecture"
    TUTORIAL = "tutorial"
    LAB = "lab"
    EXAM = "exam"


class CheckinStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    APPEALED = "appealed"


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"


CourseCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Radius = Annotated[float, Field(gt=0, allow_inf_nan=False)]
RiskScore = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Pagination(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_name(value: str) -> str:
    normalized = value.strip()
    if not normalized or "<" in normalized or ">" in normalized:
        raise ValueError("name must be non-empty and must not contain HTML markup")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("name must not contain control characters")
    return normalized
