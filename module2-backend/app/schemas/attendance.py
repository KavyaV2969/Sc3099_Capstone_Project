"""Session, check-in, and device schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator, model_validator

from .common import MutationModel, bounded_image, CheckinStatus, Latitude, Longitude, Radius, RiskScore, SessionStatus, SessionType, ShortName, as_utc


class SessionCreate(MutationModel):
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


class SessionUpdate(MutationModel):
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


class CheckinCreate(MutationModel):
    session_id: UUID4
    latitude: Latitude
    longitude: Longitude
    location_accuracy_meters: float = Field(ge=0, allow_inf_nan=False)
    device_fingerprint: str = Field(min_length=1, max_length=64)
    liveness_challenge_response: str | None = Field(default=None, max_length=14_000_000)
    qr_code: str | None = Field(default=None, max_length=2000)
    device_challenge_id: UUID4 | None = None
    device_signature: str | None = Field(default=None, min_length=1, max_length=20_000)

    @field_validator("liveness_challenge_response")
    @classmethod
    def image_size(cls, value):
        return bounded_image(value)

    @field_validator("qr_code")
    @classmethod
    def unsupported_qr(cls, value):
        if value and value.strip():
            raise ValueError("QR verification is unsupported")
        return value

    @model_validator(mode="after")
    def proof_pair(self):
        if (self.device_challenge_id is None) != (self.device_signature is None):
            raise ValueError("device_challenge_id and device_signature must be supplied together")
        return self


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


class CheckinAppeal(MutationModel):
    appeal_reason: str = Field(min_length=10, max_length=2000)


class CheckinReview(MutationModel):
    status: Literal["approved", "rejected"]
    review_notes: str = Field(min_length=1, max_length=2000)


class DeviceRegister(MutationModel):
    device_fingerprint: str = Field(min_length=1, max_length=64)
    device_name: str = Field(min_length=1, max_length=255)
    platform: Literal["ios", "android", "web", "desktop"]
    public_key: str = Field(min_length=1, max_length=20_000)

    @field_validator("public_key")
    @classmethod
    def require_nonblank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("public_key must not be blank")
        return value


class DeviceUpdate(MutationModel):
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
    device_name: str | None
    platform: str | None
    is_trusted: bool
    trust_score: str
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime | None = None
    total_checkins: int
    revoked_at: datetime | None = None


class AdminSessionStatusUpdate(MutationModel):
    status: SessionStatus


class AdminSessionStatusResponse(BaseModel):
    id: UUID4
    name: str
    status: SessionStatus
    message: str
