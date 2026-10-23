"""Shared PostgreSQL transaction lock for migration and recovery operations."""

from sqlalchemy import text

MIGRATION_LOCK = 30990002


def acquire_migration_lock(connection):
    if connection.dialect.name == "postgresql":
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '120s'"))
        if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK}):
            raise RuntimeError("Another backend migration or recovery is running")
