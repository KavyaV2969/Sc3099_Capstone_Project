"""Pydantic models for authentication and the core attendance API contract."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator


class UserRole(str, Enum):
    STUDENT = "student"
    TA = "ta"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def _validate_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("full_name must not be empty")
    if "<" in normalized or ">" in normalized:
        raise ValueError("full_name must not contain HTML markup")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("full_name must not contain control characters")
    return normalized


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.STUDENT

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 UTF-8 bytes")
        return value

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return _validate_name(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    camera_consent: bool | None = None
    geolocation_consent: bool | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        return _validate_name(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> "UserProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one profile field must be provided")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    camera_consent: bool = False
    geolocation_consent: bool = False
    face_enrolled: bool = False
    created_at: datetime
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
    scheduled_deletion_at: datetime | None = None


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class LoginResponse(TokenPairResponse):
    user: UserResponse


class AdminActionResponse(BaseModel):
    message: str


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    action: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    details: str | None = None
    success: bool
    timestamp: datetime


class TokenPayload(BaseModel):
    sub: str
    email: EmailStr
    role: UserRole
    token_type: TokenType
    iat: int
    exp: int


# Week 3 request/response models.
CourseCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Radius = Annotated[float, Field(gt=0, allow_inf_nan=False)]
RiskScore = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


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


class CourseCreate(BaseModel):
    code: CourseCode
    name: ShortName
    semester: CourseCode
    instructor_id: UUID | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius = 100.0
    risk_threshold: RiskScore = 0.5


class CourseUpdate(BaseModel):
    code: CourseCode | None = None
    name: ShortName | None = None
    semester: CourseCode | None = None
    instructor_id: UUID | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius | None = None
    risk_threshold: RiskScore | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def reject_required_nulls(self) -> "CourseUpdate":
        nullable = {"instructor_id", "venue_name", "venue_latitude", "venue_longitude"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CourseResponse(CourseCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    instructor_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    items: list[CourseResponse]
    total: int
    limit: int
    offset: int


class EnrollmentCreate(BaseModel):
    student_id: UUID
    course_id: UUID


class EnrollmentResponse(EnrollmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrolled_at: datetime
    is_active: bool


class MyEnrollmentResponse(EnrollmentResponse):
    course_code: str
    course_name: str
    semester: str


class EnrolledStudentResponse(BaseModel):
    id: UUID
    student_id: UUID
    student_email: EmailStr
    student_name: str
    enrolled_at: datetime
    is_active: bool
    face_enrolled: bool


class CourseEnrollmentsResponse(BaseModel):
    course_id: UUID
    course_code: str
    total_enrolled: int
    students: list[EnrolledStudentResponse]


def as_utc(value: datetime) -> datetime:
    """Treat naive API/SQLite timestamps as UTC, as used by the contract."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class SessionCreate(BaseModel):
    course_id: UUID
    name: ShortName
    session_type: SessionType = SessionType.LECTURE
    scheduled_start: datetime
    scheduled_end: datetime
    checkin_opens_at: datetime | None = None
    checkin_closes_at: datetime | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius | None = None
    require_liveness_check: bool = True
    require_face_match: bool = False
    risk_threshold: RiskScore | None = None

    @field_validator("scheduled_start", "scheduled_end", "checkin_opens_at", "checkin_closes_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


class SessionUpdate(BaseModel):
    name: ShortName | None = None
    session_type: SessionType | None = None
    status: SessionStatus | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    checkin_opens_at: datetime | None = None
    checkin_closes_at: datetime | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius | None = None
    require_liveness_check: bool | None = None
    require_face_match: bool | None = None
    risk_threshold: RiskScore | None = None

    @field_validator("scheduled_start", "scheduled_end", "checkin_opens_at", "checkin_closes_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None

    @model_validator(mode="after")
    def reject_required_nulls(self) -> "SessionUpdate":
        for field in self.model_fields_set - {"venue_name"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SessionResponse(SessionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    instructor_id: UUID
    status: SessionStatus
    checkin_opens_at: datetime
    checkin_closes_at: datetime
    venue_latitude: Latitude
    venue_longitude: Longitude
    geofence_radius_meters: Radius
    risk_threshold: RiskScore
    created_at: datetime
    course_code: str | None = None
    course_name: str | None = None
    total_enrolled: int = 0
    checked_in_count: int = 0
    qr_code_enabled: bool = False


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    limit: int
    offset: int


class CheckinCreate(BaseModel):
    session_id: UUID
    latitude: Latitude
    longitude: Longitude
    location_accuracy_meters: float = Field(ge=0, allow_inf_nan=False)
    device_fingerprint: str = Field(min_length=1, max_length=255)


class CheckinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    student_id: UUID
    checked_in_at: datetime
    latitude: float
    longitude: float
    location_accuracy_meters: float
    distance_from_venue_meters: float
    status: CheckinStatus
    risk_score: float
    # These checks are not performed in the Week 3 skeleton.
    liveness_passed: bool | None = None
    liveness_score: float | None = None
    risk_factors: list[dict] = Field(default_factory=list)
