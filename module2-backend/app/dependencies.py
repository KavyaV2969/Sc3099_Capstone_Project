"""Authentication and role-based authorization dependencies."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course, CourseTA, User
from app.models import Session as AttendanceSession
from app.rate_limit import enforce_user_api_limit
from app.schemas import TokenType, UserRole
from app.security import InvalidTokenError, decode_token

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
    course = database.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    return course


def require_course_access(
    database: Session, course: Course, user: User, *, allow_ta: bool = False
) -> None:
    if user.role == "admin" or (user.role == "instructor" and course.instructor_id == user.id):
        return
    if user.role == "instructor" and database.scalar(select(AttendanceSession.id).where(
        AttendanceSession.course_id == course.id, AttendanceSession.instructor_id == user.id
    ).limit(1)):
        return
    if allow_ta and user.role == "ta" and database.get(CourseTA, (course.id, user.id)):
        return
    raise HTTPException(status_code=403, detail="insufficient course permissions")
