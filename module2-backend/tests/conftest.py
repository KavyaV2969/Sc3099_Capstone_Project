"""Test environment for the database-independent backend foundation."""

import os

os.environ.setdefault(
    "SECRET_KEY",
    "unit-test-secret-key-that-is-longer-than-32-characters",
)
os.environ.setdefault("RETENTION_CLEANUP_ENABLED", "false")

