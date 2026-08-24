"""Password and JWT utility tests."""

from datetime import datetime, timezone

import pytest
from jose import jwt

from app.config import Settings
from app.schemas import TokenType, UserRole
from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        secret_key="test-secret-key-that-is-at-least-32-characters",
    )


def test_password_hash_uses_bcrypt_cost_12() -> None:
    password_hash = hash_password("securepass123")

    assert password_hash != "securepass123"
    assert password_hash.startswith(("$2a$12$", "$2b$12$"))
    assert verify_password("securepass123", password_hash)
    assert not verify_password("wrong-password", password_hash)
    assert not verify_password("securepass123", "not-a-bcrypt-hash")


def test_access_token_contains_required_claims_and_one_hour_ttl(settings: Settings) -> None:
    token = create_access_token(
        subject="user-id",
        email="student@example.com",
        role=UserRole.STUDENT,
        settings=settings,
    )
    payload = decode_token(token, TokenType.ACCESS, settings=settings)

    assert payload.sub == "user-id"
    assert payload.email == "student@example.com"
    assert payload.role is UserRole.STUDENT
    assert payload.token_type is TokenType.ACCESS
    assert 3599 <= payload.exp - payload.iat <= 3600
    assert payload.iat <= int(datetime.now(timezone.utc).timestamp())


def test_refresh_token_contains_seven_day_ttl(settings: Settings) -> None:
    token = create_refresh_token(
        subject="user-id",
        email="student@example.com",
        role=UserRole.STUDENT,
        settings=settings,
    )
    payload = decode_token(token, TokenType.REFRESH, settings=settings)

    assert payload.token_type is TokenType.REFRESH
    assert 604799 <= payload.exp - payload.iat <= 604800


def test_token_types_cannot_be_interchanged(settings: Settings) -> None:
    access_token = create_access_token(
        subject="user-id",
        email="student@example.com",
        role=UserRole.STUDENT,
        settings=settings,
    )

    with pytest.raises(InvalidTokenError, match="expected a refresh token"):
        decode_token(access_token, TokenType.REFRESH, settings=settings)


def test_malformed_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(InvalidTokenError, match="invalid or expired token"):
        decode_token("not-a-jwt", TokenType.ACCESS, settings=settings)


def test_expired_token_is_rejected(settings: Settings) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "user-id",
            "email": "student@example.com",
            "role": "student",
            "token_type": "access",
            "iat": now - 3601,
            "exp": now - 1,
        },
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError, match="invalid or expired token"):
        decode_token(token, TokenType.ACCESS, settings=settings)
