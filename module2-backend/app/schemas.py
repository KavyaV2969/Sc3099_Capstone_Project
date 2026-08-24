"""Pydantic models for the agreed Week 2 API contract."""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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
