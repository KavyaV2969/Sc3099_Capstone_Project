"""Environment-backed application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration required by the Week 2 backend foundation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "SAIV Backend API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql://saiv:saiv_password@localhost:5434/saiv"
    secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_seconds: int = Field(default=3600, gt=0)
    refresh_token_expire_seconds: int = Field(default=604800, gt=0)
    access_token_expire_minutes: int | None = Field(default=None, gt=0)
    refresh_token_expire_days: int | None = Field(default=None, gt=0)
    bcrypt_rounds: int = Field(default=10, ge=10, le=31)
    risk_score_threshold: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    redis_url: str = "redis://localhost:6380/0"
    face_service_url: str = "http://localhost:8001"
    face_service_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    retention_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    retention_cleanup_enabled: bool = True
    cors_origins_value: str = Field(
        default="http://localhost:3000,http://localhost:8501",
        validation_alias="CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        """Return normalized CORS origins from a comma-separated value."""
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_origins_value.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def documented_token_units(self):
        if self.access_token_expire_minutes is not None:
            self.access_token_expire_seconds = self.access_token_expire_minutes * 60
        if self.refresh_token_expire_days is not None:
            self.refresh_token_expire_seconds = self.refresh_token_expire_days * 86400
        return self


@lru_cache
def get_settings() -> Settings:
    """Create settings once per process."""
    return Settings()
