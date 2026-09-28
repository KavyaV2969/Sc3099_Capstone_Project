"""Authentication and user administration schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, UUID4, field_validator, model_validator

from .common import TokenType, UserRole, validate_name


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
        return validate_name(value)


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
        return validate_name(value) if value is not None else None

    @model_validator(mode="after")
    def validate_update(self) -> "UserProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one profile field must be provided")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("profile fields cannot be null")
        return self


class UserAdminUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        return validate_name(value) if value is not None else None

    @model_validator(mode="after")
    def validate_update(self) -> "UserAdminUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("fields cannot be null")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
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


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class LoginResponse(TokenPairResponse):
    user: UserResponse


class AdminActionResponse(BaseModel):
    message: str
    id: UUID4 | None = None
    email: EmailStr | None = None
    is_active: bool | None = None


class TokenPayload(BaseModel):
    sub: str
    email: EmailStr
    role: UserRole
    token_type: TokenType
    iat: int
    exp: int



class FaceEnrollmentCreate(BaseModel):
    image: str = Field(min_length=1, max_length=14_000_000)


class FaceEnrollmentResponse(BaseModel):
    success: bool
    message: str
    face_enrolled: bool
    quality_score: float = Field(ge=0, le=1)


class BulkUserCreate(BaseModel):
    users: list[UserRegister] = Field(min_length=1, max_length=1000)


class BulkUserItem(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: UserRole


class BulkUserError(BaseModel):
    index: int
    email: EmailStr
    error: str


class BulkUserResponse(BaseModel):
    created: int
    failed: int
    users: list[BulkUserItem]
    errors: list[BulkUserError]
