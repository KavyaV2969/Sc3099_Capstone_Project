"""Database-independent password and JWT security helpers."""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas import TokenPayload, TokenType, UserRole

class InvalidTokenError(ValueError):
    """Raised when a JWT is invalid or has the wrong token type."""


def hash_password(password: str) -> str:
    """Hash a password using the configured bcrypt work factor."""
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("password must not exceed 72 UTF-8 bytes")
    context = CryptContext(
        schemes=["bcrypt"],
        deprecated="auto",
        bcrypt__rounds=get_settings().bcrypt_rounds,
    )
    return context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Safely compare a plaintext password with a bcrypt hash."""
    try:
        if len(password.encode("utf-8")) > 72:
            return False
        return CryptContext(schemes=["bcrypt"], deprecated="auto").verify(password, password_hash)
    except (TypeError, ValueError):
        return False


def _create_token(
    *,
    subject: str,
    email: str,
    role: UserRole,
    token_type: TokenType,
    expires_in: timedelta,
    settings: Settings,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "email": email,
        "role": role.value,
        "token_type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(
    subject: str,
    email: str,
    role: UserRole,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    return _create_token(
        subject=subject,
        email=email,
        role=role,
        token_type=TokenType.ACCESS,
        expires_in=timedelta(seconds=active_settings.access_token_expire_seconds),
        settings=active_settings,
    )


def create_refresh_token(
    subject: str,
    email: str,
    role: UserRole,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    return _create_token(
        subject=subject,
        email=email,
        role=role,
        token_type=TokenType.REFRESH,
        expires_in=timedelta(seconds=active_settings.refresh_token_expire_seconds),
        settings=active_settings,
    )


def decode_token(
    token: str,
    expected_type: TokenType,
    settings: Settings | None = None,
) -> TokenPayload:
    """Verify signature, expiry, claims, and intended token type."""
    active_settings = settings or get_settings()
    try:
        raw_payload = jwt.decode(
            token,
            active_settings.secret_key.get_secret_value(),
            algorithms=[active_settings.jwt_algorithm],
        )
        payload = TokenPayload.model_validate(raw_payload)
    except (JWTError, ValidationError) as exc:
        raise InvalidTokenError("invalid or expired token") from exc

    if payload.token_type is not expected_type:
        raise InvalidTokenError(f"expected a {expected_type.value} token")
    return payload

