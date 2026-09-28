"""Authentication and role-based authorization dependencies."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course, User
from app.rate_limit import enforce_user_api_limit
from app.schemas import TokenType, UserRole
from app.security import InvalidTokenError, decode_token
from app.services.access import get_course as _get_course, require_course_access as _require_course_access

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    database: Session = Depends(get_db),
) -> User:
    """Return the active database user represented by an access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        payload = decode_token(credentials.credentials, TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token") from exc

    user = database.get(User, payload.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account is unavailable")

    enforce_user_api_limit(user.id)
    return user


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Create a dependency that permits only the specified roles."""

    def role_guard(current_user: User = Depends(get_current_user)) -> User:
        if UserRole(current_user.role) not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return current_user

    return role_guard


def get_course_or_404(database: Session, course_id: str) -> Course:
    return _get_course(database, course_id)


def require_course_access(
    database: Session, course: Course, user: User, *, allow_ta: bool = False
) -> None:
    _require_course_access(database, course, user, allow_ta=allow_ta)
