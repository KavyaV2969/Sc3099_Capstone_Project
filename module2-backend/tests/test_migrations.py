"""Exercise the frozen Alembic migration independently of ORM create_all."""
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, create_engine, inspect, select

from app import config as app_config
from app.models import Base

BACKEND = Path(__file__).resolve().parents[1]


def migration_config(output=None):
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_migration_upgrade_matches_models_and_downgrades(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(database_url=url))
    config = migration_config()
    command.upgrade(config, "20260908_0002")
    engine = create_engine(url)
    # Existing accounts receive zero failures when the lockout migration is applied.
    with engine.begin() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        connection.execute(users.insert().values(id="existing-user", email="existing@example.com",
                                                 full_name="Existing", hashed_password="unused"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        assert connection.scalar(select(users.c.failed_login_attempts)) == 0
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    command.downgrade(config, "20260825_0001")
    assert set(inspect(engine).get_table_names()) == {"users", "audit_logs", "alembic_version"}
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_migration_generates_postgresql_sql(monkeypatch):
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(database_url="postgresql://localhost/test"))
    output = StringIO()
    command.upgrade(migration_config(output), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE checkins" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "uq_checkins_student_session" in sql
    assert "REFERENCES users (id)" in sql


def test_retention_backfill_preserves_existing_checkins(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}"
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(database_url=url))
    config = migration_config()
    command.upgrade(config, "20260911_0004")
    engine = create_engine(url)
    checked_at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    with engine.begin() as connection:
        metadata = MetaData()
        users = Table("users", metadata, autoload_with=connection)
        courses = Table("courses", metadata, autoload_with=connection)
        sessions = Table("sessions", metadata, autoload_with=connection)
        checkins = Table("checkins", metadata, autoload_with=connection)
        for user_id, email, role in (("teacher", "teacher@example.com", "instructor"),
                                     ("student", "student@example.com", "student")):
            connection.execute(users.insert().values(
                id=user_id, email=email, full_name=role.title(), hashed_password="unused",
                role=role, is_active=True, camera_consent=False, geolocation_consent=False,
                face_enrolled=False, created_at=checked_at, updated_at=checked_at,
            ))
        connection.execute(courses.insert().values(
            id="course", code="TEST", name="Test", semester="AY26", instructor_id="teacher",
            venue_latitude=1.3, venue_longitude=103.8, geofence_radius_meters=100,
            risk_threshold=.5, is_active=True, created_at=checked_at, updated_at=checked_at,
        ))
        connection.execute(sessions.insert().values(
            id="session", course_id="course", instructor_id="teacher", name="Session",
            session_type="lecture", status="closed", scheduled_start=checked_at,
            scheduled_end=checked_at + timedelta(hours=1), checkin_opens_at=checked_at,
            checkin_closes_at=checked_at + timedelta(minutes=30), venue_latitude=1.3,
            venue_longitude=103.8, geofence_radius_meters=100, require_liveness_check=False,
            require_face_match=False, risk_threshold=.5, created_at=checked_at,
        ))
        connection.execute(checkins.insert().values(
            id="checkin", session_id="session", student_id="student", checked_in_at=checked_at,
            latitude=1.3, longitude=103.8, location_accuracy_meters=1,
            distance_from_venue_meters=0, status="approved", risk_score=0,
        ))
    command.upgrade(config, "head")
    with engine.begin() as connection:
        checkins = Table("checkins", MetaData(), autoload_with=connection)
        row = connection.execute(select(checkins).where(checkins.c.id == "checkin")).one()
        assert row.scheduled_deletion_at - row.checked_in_at == timedelta(days=30)
        assert row.verified_at == row.checked_in_at
        connection.execute(checkins.update().where(checkins.c.id == "checkin").values(status="appealed"))
    engine.dispose()
