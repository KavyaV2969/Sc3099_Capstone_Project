"""Environment-backed application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    redis_url: str = "redis://localhost:6380/0"
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


@lru_cache
def get_settings() -> Settings:
    """Create settings once per process."""
    return Settings()
