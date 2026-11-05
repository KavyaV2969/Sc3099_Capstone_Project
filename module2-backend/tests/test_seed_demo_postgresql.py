"""Exercise the seed command against canonical migrations and immutable auditing."""
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DatabaseSession

from app.models import AuditLog, Checkin, Course, Enrollment, Session, User
from app.security import verify_password
from scripts import seed_demo
from test_f00_postgresql import canonical, pg_database

pytestmark = pytest.mark.skipif(not os.environ.get("F00_POSTGRES_TEST_URL"),
                                reason="Set F00_POSTGRES_TEST_URL for PostgreSQL seed verification")


def test_seed_command_commits_and_reuses_canonical_data(canonical, monkeypatch, capsys):
    monkeypatch.setattr(seed_demo, "get_settings", lambda: SimpleNamespace(database_url=canonical.url))
    monkeypatch.setenv("SAIV_DEMO_PASSWORD", "DemoPassword123!")
    seed_demo.main()
    assert "Initial password for newly created accounts" in capsys.readouterr().out
    with DatabaseSession(canonical) as db:
        assert db.scalar(select(Course.code)) == "SC3099"
        assert db.scalar(select(func.count(User.id))) == 3
        assert db.scalar(select(func.count(Enrollment.id))) == 1
        assert db.scalar(select(func.count(Session.id))) == 2
        assert db.scalar(select(func.count(AuditLog.id))) == 7
        assert db.scalar(select(func.count(Checkin.id))) == 0
    monkeypatch.setenv("SAIV_DEMO_PASSWORD", "DifferentPassword123!")
    seed_demo.main()
    assert "SC3099 already present" in capsys.readouterr().out
    with DatabaseSession(canonical) as db:
        student = db.scalar(select(User).where(User.role == "student"))
        assert verify_password("DemoPassword123!", student.hashed_password)
        assert db.scalar(select(func.count(Session.id))) == 2
        assert db.scalar(select(func.count(AuditLog.id))) == 7


def test_startup_preserves_an_existing_sc3099_course(canonical, monkeypatch, capsys):
    with DatabaseSession(canonical) as db, db.begin():
        db.add(Course(code="SC3099", name="Existing Capstone", semester="AY26", is_active=False))
    monkeypatch.setattr(seed_demo, "get_settings", lambda: SimpleNamespace(database_url=canonical.url))
    seed_demo.main()
    assert "SC3099 already present" in capsys.readouterr().out
    with DatabaseSession(canonical) as db:
        assert db.scalar(select(Course.name)) == "Existing Capstone"
        assert db.scalar(select(Course.is_active)) is False
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(Session.id))) == 0
