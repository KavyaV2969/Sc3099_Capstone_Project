"""Session, check-in, and device schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator, model_validator

from .common import CheckinStatus, Latitude, Longitude, Radius, RiskScore, SessionStatus, SessionType, ShortName, as_utc


class SessionCreate(BaseModel):
    course_id: UUID4
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
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in self.model_fields_set - {"venue_name"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SessionResponse(SessionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    instructor_id: UUID4
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
    session_id: UUID4
    latitude: Latitude
    longitude: Longitude
    location_accuracy_meters: float = Field(ge=0, allow_inf_nan=False)
    device_fingerprint: str = Field(min_length=1, max_length=255)
    liveness_challenge_response: str | None = Field(default=None, max_length=14_000_000)
    qr_code: str | None = Field(default=None, max_length=2000)


class CheckinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    session_id: UUID4
    student_id: UUID4
    checked_in_at: datetime
    verified_at: datetime | None = None
    latitude: float
    longitude: float
    location_accuracy_meters: float
    distance_from_venue_meters: float
    status: CheckinStatus
    risk_score: float
    liveness_passed: bool | None = None
    liveness_score: float | None = None
    face_match_passed: bool | None = None
    face_match_score: float | None = None
    risk_factors: list[dict] = Field(default_factory=list)
    reviewed_by_id: UUID4 | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    appeal_reason: str | None = None
    appealed_at: datetime | None = None
    scheduled_deletion_at: datetime | None = None
    session_name: str | None = None
    student_name: str | None = None
    student_email: str | None = None
    course_code: str | None = None
    device_trusted: bool | None = None

    @field_validator("risk_factors", mode="before")
    @classmethod
    def normalize_risk_factors(cls, value):
        return value or []


class CheckinListResponse(BaseModel):
    items: list[CheckinResponse]
    total: int
    limit: int
    offset: int


class CheckinAppeal(BaseModel):
    appeal_reason: str = Field(min_length=10, max_length=2000)


class CheckinReview(BaseModel):
    status: Literal["approved", "rejected"]
    review_notes: str = Field(min_length=1, max_length=2000)


class DeviceRegister(BaseModel):
    device_fingerprint: str = Field(min_length=1, max_length=255)
    device_name: str = Field(min_length=1, max_length=255)
    platform: Literal["ios", "android", "web", "desktop"]
    public_key: str | None = Field(default=None, max_length=20_000)


class DeviceUpdate(BaseModel):
    device_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_trusted: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "DeviceUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("device fields cannot be null")
        return self


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    device_fingerprint: str
    device_name: str
    platform: str
    is_trusted: bool
    trust_score: str
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime | None = None
    total_checkins: int


class AdminSessionStatusUpdate(BaseModel):
    status: SessionStatus


class AdminSessionStatusResponse(BaseModel):
    id: UUID4
    name: str
    status: SessionStatus
    message: str
