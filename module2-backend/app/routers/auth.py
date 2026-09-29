"""Database-backed registration, login, and refresh endpoints."""

from datetime import datetime, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.models import User, Enrollment, Device
from app.services.enrollments import include_in_active_rosters
from app.rate_limit import enforce_login_limit, enforce_registration_limit, enforce_user_api_limit
from app.schemas import LoginRequest, LoginResponse, RefreshTokenRequest, TokenPairResponse, TokenType, UserRegister, UserResponse, UserRole
from app.security import InvalidTokenError, create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.schemas.auth import ActivationRequest
from app.schemas import as_utc

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
    try:
        database.flush()
        write_audit_log(
            database, request, action="user_created", user_id=user.id,
            resource_type="user", resource_id=user.id,
        )
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
    # Serialize attempts for this account, including attempts from different IPs.
    user = database.scalar(select(User).where(User.email == payload.email).with_for_update())
    if user is not None and user.failed_login_attempts >= 10:
        write_audit_log(database, request, action="login_failed", user_id=user.id,
                        details={"email": payload.email, "reason": "account_blocked"}, success=False)
        database.commit()
        raise HTTPException(status_code=429, detail="account is blocked; contact an administrator")
    if user is None or not verify_password(payload.password, user.hashed_password):
        if user is not None:
            user.failed_login_attempts += 1
        blocked = user is not None and user.failed_login_attempts >= 10
        write_audit_log(
            database,
            request,
            action="login_failed",
            user_id=user.id if user else None,
            details={"email": payload.email, "reason": "account_blocked" if blocked else "invalid_credentials"},
            success=False,
        )
        database.commit()
        if blocked:
            raise HTTPException(status_code=429, detail="account is blocked; contact an administrator")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if not user.is_active:
        write_audit_log(
            database,
            request,
            action="login_failed",
            user_id=user.id,
            details={"email": payload.email, "reason": "account_inactive"},
            success=False,
        )
        database.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled")

    user.failed_login_attempts = 0
    user.last_login_at = datetime.now(timezone.utc)
    device_id = database.scalar(select(Device.id).where(Device.user_id == user.id,
        Device.device_fingerprint == payload.device_fingerprint, Device.is_active.is_(True))) if payload.device_fingerprint else None
    write_audit_log(database, request, action="login_success", user_id=user.id,
                    device_id=device_id, details={"device_id": device_id})
    database.commit()
    database.refresh(user)
    tokens = _token_pair(user)
    return LoginResponse(**tokens.model_dump(), user=user)


@router.post("/activate", response_model=UserResponse)
def activate(payload: ActivationRequest, request: Request, response: Response,
             database: Session = Depends(get_db)):
    enforce_registration_limit(request)
    user = database.scalar(select(User).where(
        User.activation_token_hash == sha256(payload.token.encode()).hexdigest()
    ).with_for_update())
    if (user is None or user.activation_expires_at is None
        or as_utc(user.activation_expires_at) <= datetime.now(timezone.utc)
        or user.scheduled_deletion_at is not None or user.role != "student"):
        raise HTTPException(status_code=400, detail="activation link is invalid or expired")
    user.hashed_password = hash_password(payload.password)
    if payload.full_name is not None:
        user.full_name = payload.full_name
    user.is_active, user.failed_login_attempts = True, 0
    user.activation_token_hash = user.activation_expires_at = None
    for course_id in database.scalars(select(Enrollment.course_id).where(
        Enrollment.student_id == user.id, Enrollment.is_active.is_(True)).order_by(Enrollment.course_id)):
        include_in_active_rosters(database, user.id, course_id)
    write_audit_log(database, request, action="user_activated", user_id=user.id,
                    resource_type="user", resource_id=user.id, details={"method": "activation_link"})
    database.commit()
    database.refresh(user)
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/refresh", response_model=TokenPairResponse)
def refresh(
    payload: RefreshTokenRequest,
    request: Request,
    database: Session = Depends(get_db),
) -> TokenPairResponse:
    """Validate a refresh token and issue a new pair; the old token is not revoked."""
    try:
        token = decode_token(payload.refresh_token, TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from exc

    user = database.get(User, token.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account is unavailable")
    enforce_user_api_limit(user.id)
    return _token_pair(user)
