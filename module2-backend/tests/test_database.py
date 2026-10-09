"""PostgreSQL metadata and connection tests."""

from app import db
from app.models import Base
from app.schema_contract import DatabaseReadiness


def test_metadata_contains_auth_and_attendance_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users", "audit_logs", "courses", "course_tas", "enrollments", "sessions", "checkins", "devices"
    }


def test_reachable_but_incompatible_database_is_not_healthy(monkeypatch) -> None:
    monkeypatch.setattr(db, "database_readiness", lambda: DatabaseReadiness(True, "incompatible"))
    assert not db.database_is_healthy()
