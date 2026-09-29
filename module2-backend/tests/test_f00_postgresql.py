"""Real PostgreSQL tests; every write uses a distinctly named disposable database.

Set F00_POSTGRES_TEST_URL to enable. F00_BACKUP_MANIFEST enables restored-data
recovery/rollback tests as well; it must point to backup_database output.
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from key_fixtures import PUBLIC_KEY
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.migration_support import acquire_migration_lock
from app.models import AuditLog, Checkin, Course, Device, Session as AttendanceSession, User
from app.routers.devices import register_device
from app.schemas import DeviceRegister
from app.schema_contract import CANONICAL_HEAD, LEGACY_HEAD, differences, inspect_readiness, inventory
from scripts.database_evidence import (control_evidence, create_isolated_database, digest, file_digest,
                                      identity, migration_config, snapshot)
from scripts import reconcile_database as recovery

SOURCE = os.environ.get("F00_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not SOURCE, reason="Set F00_POSTGRES_TEST_URL for isolated PostgreSQL migration tests")


@pytest.fixture
def pg_database():
    name = "saiv_f00_test_" + uuid4().hex
    target = create_isolated_database(SOURCE, name)
    engine = create_engine(target)
    yield engine
    engine.dispose()
    admin = create_engine(make_url(SOURCE).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            assert name.startswith("saiv_f00_test_") and name != make_url(SOURCE).database
            connection.execute(text("DROP DATABASE " + connection.dialect.identifier_preparer.quote(name)))
    finally:
        admin.dispose()


@pytest.fixture
def canonical(pg_database):
    with pg_database.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    return pg_database


def test_fresh_postgresql_migrates_and_all_alembic_commands_work(canonical):
    assert inspect_readiness(canonical).healthy
    with canonical.begin() as connection:
        assert differences(connection) == []
        before = snapshot(connection)
        command.current(migration_config(connection), verbose=True)
        command.check(migration_config(connection))
        command.upgrade(migration_config(connection), "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == CANONICAL_HEAD
        assert snapshot(connection) == before


def test_recovered_history_reproduces_the_live_legacy_schema(pg_database):
    with pg_database.begin() as connection:
        command.upgrade(migration_config(connection, legacy=True), LEGACY_HEAD)
        assert differences(connection, LEGACY_HEAD) == []
    assert not inspect_readiness(pg_database).healthy


@pytest.mark.parametrize("ddl", [
    "ALTER TABLE checkins DROP COLUMN verified_at",
    "ALTER TABLE checkins DROP CONSTRAINT ck_checkins_status",
    "ALTER TABLE checkins DROP CONSTRAINT ck_checkins_status, ADD CONSTRAINT ck_checkins_status CHECK (status IN ('pending','approved','flagged','rejected'))",
    "ALTER TABLE users DROP CONSTRAINT ck_users_role, ADD CONSTRAINT ck_users_role CHECK (role IN ('student','ta','instructor','ADMIN'))",
    "ALTER TABLE devices ALTER COLUMN device_fingerprint TYPE varchar(255)",
    "ALTER TABLE devices ALTER COLUMN last_seen_at DROP NOT NULL",
    "ALTER TABLE devices ALTER COLUMN trust_score DROP DEFAULT",
    "DROP INDEX ix_checkins_checked_in_at",
    "ALTER TABLE checkins DROP CONSTRAINT fk_checkins_device, ADD CONSTRAINT fk_checkins_device FOREIGN KEY(device_id) REFERENCES devices(id)",
    "UPDATE alembic_version SET version_num='unknown_revision'",
    "DELETE FROM alembic_version",
    "ALTER TABLE devices ADD COLUMN undocumented_required varchar(20) NOT NULL DEFAULT 'x'",
    "ALTER TABLE checkins ADD CONSTRAINT extra_unvalidated CHECK(risk_score<1) NOT VALID",
    "ALTER TABLE course_tas DROP CONSTRAINT course_tas_pkey",
    "ALTER TABLE checkins DROP CONSTRAINT uq_checkins_student_session",
    "CREATE TYPE f00_unknown_enum AS ENUM ('x')",
    "ALTER TABLE alembic_version DROP CONSTRAINT alembic_version_pkc",
    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(20)",
])
def test_readiness_catches_structural_drift_with_working_connectivity(canonical, ddl, monkeypatch):
    with canonical.begin() as connection:
        connection.execute(text(ddl))
        assert connection.scalar(text("SELECT 1")) == 1
    readiness = inspect_readiness(canonical)
    assert readiness.connected and not readiness.healthy
    monkeypatch.setattr(main, "database_readiness", lambda: inspect_readiness(canonical))
    monkeypatch.setattr(main, "redis_is_healthy", lambda: True)
    assert TestClient(main.app).get("/health").status_code == 503


@pytest.mark.parametrize("problem", ["long", "duplicate"])
def test_device_migration_refuses_data_loss_and_rolls_back(pg_database, problem):
    with pg_database.begin() as connection:
        command.upgrade(migration_config(connection), "20260915_0005")
    # Seed through the frozen old schema, never today's ORM columns.
    with pg_database.begin() as connection:
        metadata = MetaData()
        users = Table("users", metadata, autoload_with=connection)
        devices = Table("devices", metadata, autoload_with=connection)
        for i in range(2):
            uid = str(uuid4())
            connection.execute(users.insert().values(id=uid, email=f"u{i}@test.invalid", full_name="Test", hashed_password="unused"))
            connection.execute(devices.insert().values(id=str(uuid4()), user_id=uid,
                device_fingerprint="x" * 65 if problem == "long" else "duplicate", device_name="Phone", platform="ios",
                public_key=PUBLIC_KEY, first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc)))
    with pg_database.connect() as connection:
        before, schema = snapshot(connection), inventory(connection)
    with pytest.raises(RuntimeError, match="Device migration refused"):
        with pg_database.begin() as connection:
            command.upgrade(migration_config(connection), "head")
    with pg_database.connect() as connection:
        assert snapshot(connection) == before and inventory(connection) == schema
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260915_0005"


def test_concurrent_migration_lock_refuses_second_process(canonical):
    with canonical.begin() as first:
        acquire_migration_lock(first)
        with canonical.begin() as second:
            with pytest.raises(RuntimeError, match="Another backend migration"):
                acquire_migration_lock(second)


def test_canonical_0005_upgrade_preserves_existing_device_values(pg_database):
    with pg_database.begin() as connection:
        command.upgrade(migration_config(connection), "20260915_0005")
    with pg_database.begin() as connection:
        metadata = MetaData()
        users = Table("users", metadata, autoload_with=connection)
        devices = Table("devices", metadata, autoload_with=connection)
        uid = str(uuid4())
        connection.execute(users.insert().values(id=uid, email="existing@test.invalid", full_name="Existing", hashed_password="unused"))
        connection.execute(devices.insert().values(id=str(uuid4()), user_id=uid, device_fingerprint="existing",
            device_name="Phone", platform="ios", public_key="existing-key",
            first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc)))
    with pg_database.connect() as connection:
        before = snapshot(connection)
    with pg_database.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        assert snapshot(connection, {name: evidence["columns"] for name, evidence in before.items()}) == before
        assert differences(connection) == []


def test_failed_concurrent_index_is_not_ready(canonical):
    with Session(canonical) as database:
        database.add_all([User(email=f"duplicate-role-{n}@test.invalid", full_name="Test", hashed_password="unused") for n in range(2)])
        database.commit()
    with canonical.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("CREATE UNIQUE INDEX CONCURRENTLY f00_invalid_index ON users(role)"))
    readiness = inspect_readiness(canonical)
    assert not readiness.healthy
    assert any("Invalid constraint/index" in message for message in readiness.errors)


def test_registration_race_returns_controlled_error_and_one_audit(canonical):
    with Session(canonical) as database:
        user = User(email="race@test.invalid", full_name="Race", hashed_password="unused")
        database.add(user);database.commit();user_id = user.id
    barrier = Barrier(2)
    def wait_for_competing_select(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT devices.") and "FOR UPDATE" in statement:
            barrier.wait(timeout=10)
    event.listen(canonical, "after_cursor_execute", wait_for_competing_select)
    def register():
        with Session(canonical, autoflush=False) as database:
            user = database.get(User, user_id)
            payload = DeviceRegister(device_fingerprint="racing-phone", device_name="Phone", platform="ios", public_key=PUBLIC_KEY)
            request = Request({"type":"http", "method":"POST", "path":"/", "headers":[], "client":("127.0.0.1",12345)})
            try:
                register_device(payload, request, database, user)
                return 201
            except HTTPException as exc:
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(register) for _ in range(2)]
            assert sorted(future.result(timeout=20) for future in futures) == [201,400]
    finally:
        event.remove(canonical, "after_cursor_execute", wait_for_competing_select)
    with Session(canonical) as database:
        assert len(list(database.scalars(select(Device)))) == 1
        assert len(list(database.scalars(select(AuditLog).where(AuditLog.action=="device_registered")))) == 1


def test_postgresql_orm_queries_constraints_and_device_delete(canonical):
    now = datetime.now(timezone.utc)
    with Session(canonical) as database:
        student = User(email="student@test.invalid", full_name="Student", hashed_password="unused")
        teacher = User(email="teacher@test.invalid", full_name="Teacher", hashed_password="unused", role="instructor")
        database.add_all([student, teacher]);database.flush()
        course = Course(code="F00", name="Test", semester="AY26", instructor_id=teacher.id)
        database.add(course);database.flush()
        attendance = AttendanceSession(course_id=course.id, instructor_id=teacher.id, name="Test",
            scheduled_start=now, scheduled_end=now+timedelta(hours=1), checkin_opens_at=now,
            checkin_closes_at=now+timedelta(minutes=30), venue_latitude=1.3, venue_longitude=103.8, geofence_radius_meters=100)
        device = Device(user_id=student.id, device_fingerprint="phone", public_key=None)
        database.add_all([attendance, device]);database.flush()
        checkin = Checkin(session_id=attendance.id, student_id=student.id, device_id=device.id,
            latitude=1.3, longitude=103.8, location_accuracy_meters=1, distance_from_venue_meters=0,
            status="approved", risk_score=0)
        database.add(checkin);database.commit()
        checkin_id, device_id, student_id, session_id = checkin.id, device.id, student.id, attendance.id
        assert database.scalar(select(Checkin).limit(1)).id == checkin_id
        database.delete(device);database.commit();database.expire_all()
        assert database.get(Checkin, checkin_id).device_id is None
        for statement, values in [
            ("UPDATE checkins SET status='invalid' WHERE id=:id", {"id":checkin_id}),
            ("UPDATE checkins SET student_id=:user WHERE id=:id", {"id":checkin_id,"user":str(uuid4())}),
            ("UPDATE checkins SET device_id=:device WHERE id=:id", {"id":checkin_id,"device":str(uuid4())}),
        ]:
            with pytest.raises(IntegrityError):
                database.execute(text(statement), values);database.commit()
            database.rollback()
        database.add(Checkin(session_id=session_id, student_id=student_id, latitude=1.3,longitude=103.8,
            location_accuracy_meters=1,distance_from_venue_meters=0,status="pending",risk_score=0))
        with pytest.raises(IntegrityError):database.commit()
        database.rollback()
        database.add(Device(user_id=student_id,device_fingerprint="bad-trust",trust_score="invalid"))
        with pytest.raises(IntegrityError):database.commit()
        database.rollback()


@pytest.fixture
def restored_legacy(pg_database):
    path = os.environ.get("F00_BACKUP_MANIFEST")
    if not path:
        pytest.skip("Set F00_BACKUP_MANIFEST for verified restored-data tests")
    manifest = json.loads(Path(path).read_text())
    # The operator's rehearsal may already be reconciled. Always restore the
    # immutable dump into this test's empty disposable database instead.
    source = make_url(SOURCE)
    name = pg_database.url.database
    assert name.startswith("saiv_f00_test_") and name != source.database
    assert file_digest(manifest["dump_path"]) == manifest["dump_sha256"]
    container = os.environ.get("F00_POSTGRES_CONTAINER")
    if container:
        restore = ["docker", "exec", "-i", container, "pg_restore", "-U", source.username, "-d", name]
    else:
        restore = ["pg_restore", "-h", source.host, "-p", str(source.port or 5432), "-U", source.username, "-d", name]
    env = os.environ.copy()
    env["PGPASSWORD"] = source.password or ""
    with Path(manifest["dump_path"]).open("rb") as stream:
        subprocess.run(restore + ["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl"],
                       stdin=stream, env=env, check=True, capture_output=True)
    with pg_database.connect() as connection:
        assert snapshot(connection) == manifest["snapshot"]
        assert digest(inventory(connection)) == manifest["source_schema_sha256"]
        assert control_evidence(connection) == manifest["source_control"]
        manifest["restored_identity"] = identity(connection)
    yield pg_database, manifest


def test_recovery_refuses_unexpected_revision_and_schema_without_writes(restored_legacy):
    engine, manifest = restored_legacy
    for ddl in ["UPDATE alembic_version SET version_num='unknown_revision'", "ALTER TABLE devices ADD COLUMN unexpected text"]:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(ddl))
            before, schema = snapshot(connection), inventory(connection)
            with pytest.raises(ValueError, match="Legacy preflight refused"):
                recovery.recover(connection, manifest, rehearsal=True)
            assert snapshot(connection) == before and inventory(connection) == schema
            transaction.rollback()


def test_mid_recovery_failure_rolls_back_everything(restored_legacy, monkeypatch):
    engine, manifest = restored_legacy
    with engine.connect() as connection:
        before, schema = snapshot(connection), inventory(connection)
    def fail(*args, **kwargs):raise RuntimeError("injected verification failure")
    monkeypatch.setattr(recovery.command, "check", fail)
    with pytest.raises(RuntimeError, match="injected"):
        with engine.begin() as connection:
            recovery.recover(connection, manifest, rehearsal=True)
    with engine.connect() as connection:
        assert snapshot(connection) == before and inventory(connection) == schema
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == LEGACY_HEAD


@pytest.mark.parametrize("problem", ["restore", "checksum", "control", "changed_data", "missing_rehearsal"])
def test_recovery_refuses_inadequate_backup_evidence(restored_legacy, problem):
    engine, original = restored_legacy
    manifest = dict(original)
    if problem == "restore":manifest["restore_verified"] = False
    if problem == "checksum":manifest["dump_sha256"] = "0"*64
    if problem == "control":manifest["source_control"] = None
    with engine.connect() as connection:
        transaction = connection.begin()
        if problem == "changed_data":
            connection.execute(text("UPDATE checkins SET risk_factors='[] ' WHERE id=(SELECT id FROM checkins LIMIT 1)"))
        before, schema = snapshot(connection), inventory(connection)
        with pytest.raises(ValueError):
            if problem == "missing_rehearsal":
                manifest["rehearsal_verified"] = False
                recovery.preflight(connection, manifest, rehearsal=True, require_rehearsal=True)
            else:
                recovery.recover(connection, manifest, rehearsal=True)
        assert snapshot(connection) == before and inventory(connection) == schema
        transaction.rollback()


def test_full_recovery_preserves_records_and_legacy_null_keys(restored_legacy):
    # Roll back this test too: the operator's separately verified rehearsal runs
    # after the suite and commits only when the complete safety suite has passed.
    engine, manifest = restored_legacy
    with engine.connect() as connection:
        transaction = connection.begin()
        before = snapshot(connection)
        null_keys = connection.scalar(text("SELECT count(*) FROM devices WHERE public_key IS NULL"))
        result = recovery.recover(connection, manifest, rehearsal=True)
        assert differences(connection) == []
        columns = {name:e["columns"] for name,e in before.items()}
        assert snapshot(connection, columns, result["audit_id"]) == before
        assert connection.scalar(text("SELECT count(*) FROM devices WHERE public_key IS NULL")) == null_keys
        assert connection.scalar(text("SELECT count(*) FROM checkins WHERE scheduled_deletion_at != checked_in_at + INTERVAL '30 days'")) == 0
        assert connection.scalar(text("SELECT count(*) FROM checkins WHERE (status='approved' AND verified_at IS DISTINCT FROM checked_in_at) OR (status!='approved' AND verified_at IS NOT NULL)")) == 0
        connection.execute(select(Checkin).limit(1))
        transaction.rollback()
