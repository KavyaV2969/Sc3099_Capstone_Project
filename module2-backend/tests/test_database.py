"""PostgreSQL metadata and connection tests for the two-table Week 2 scope."""

from app.db import database_is_healthy
from app.models import Base


def test_week_two_metadata_contains_only_auth_tables() -> None:
    assert set(Base.metadata.tables) == {"users", "audit_logs"}


def test_postgresql_connection_is_healthy() -> None:
    assert database_is_healthy()
