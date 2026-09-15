"""PostgreSQL metadata and connection tests."""

from app.db import database_is_healthy
from app.models import Base


def test_metadata_contains_auth_and_attendance_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users", "audit_logs", "courses", "course_tas", "enrollments", "sessions", "checkins", "devices"
    }


def test_postgresql_connection_is_healthy() -> None:
    assert database_is_healthy()
