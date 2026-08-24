"""Database-backed registration, login, and refresh endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.models import User
from app.rate_limit import enforce_login_limit, enforce_registration_limit, enforce_user_api_limit
from app.schemas import LoginRequest, LoginResponse, RefreshTokenRequest, TokenPairResponse, TokenType, UserRegister, UserResponse, UserRole
from app.security import InvalidTokenError, create_access_token, create_refresh_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


def _token_pair(user: User) -> TokenPairResponse:
    role = UserRole(user.role)
    return TokenPairResponse(
        access_token=create_access_token(user.id, user.email, role),
        refresh_token=create_refresh_token(user.id, user.email, role),
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegister,
    request: Request,
    database: Session = Depends(get_db),
) -> User:
    """Create a user account. Role selection follows the supplied course contract."""
    enforce_registration_limit(request)
    existing = database.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role.value,
    )
    database.add(user)
    database.flush()
    write_audit_log(
        database,
        request,
        action="user_created",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email already registered") from exc
    database.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    database: Session = Depends(get_db),
) -> LoginResponse:
    """Verify credentials and issue a one-hour access and seven-day refresh token."""
    enforce_login_limit(request)
    user = database.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        write_audit_log(
            database,
            request,
            action="login_failed",
            details={"email": payload.email, "reason": "invalid_credentials"},
            success=False,
        )
        database.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if not user.is_active:
        write_audit_log(
            database,
            request,
            action="login_failed",
            user_id=user.id,
            details={"reason": "account_inactive"},
            success=False,
        )
        database.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled")

    user.last_login_at = datetime.now(timezone.utc)
    write_audit_log(database, request, action="login_success", user_id=user.id)
    database.commit()
    database.refresh(user)
    tokens = _token_pair(user)
    return LoginResponse(**tokens.model_dump(), user=user)


@router.post("/refresh", response_model=TokenPairResponse)
def refresh(
    payload: RefreshTokenRequest,
    request: Request,
    database: Session = Depends(get_db),
) -> TokenPairResponse:
    """Validate a refresh token and rotate both JWTs."""
    try:
        token = decode_token(payload.refresh_token, TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from exc

    user = database.get(User, token.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account is unavailable")
    enforce_user_api_limit(user.id)
    return _token_pair(user)
