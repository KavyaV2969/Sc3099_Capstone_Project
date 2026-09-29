"""Audit-role enforcement and conflict regression tests on disposable PostgreSQL."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models import AuditLog, Enrollment, User, Course, utc_now
from app.routers import auth
from app.schemas import CheckinCreate, UserRegister
from app.schemas.auth import ActivationRequest
from app.schema_contract import inspect_readiness
from app.services.enrollments import create_enrollment
from app.services.devices import issue_challenge, consume_proof
from scripts.configure_database_roles import configure
from test_f00_postgresql import pg_database, canonical
from key_fixtures import PUBLIC_KEY


@pytest.mark.parametrize("changed",["course","student"])
def test_enrollment_refreshes_locked_eligibility_after_concurrent_deactivation(canonical,changed):
    with Session(canonical) as db:
        student=User(email="eligibility@example.com",full_name="Eligibility",hashed_password="unused")
        course=Course(code="ELIGIBLE",name="Eligible",semester="AY26")
        db.add_all([student,course]); db.flush(); uid,cid=student.id,course.id; db.commit()
    with Session(canonical) as db:
        cached_student=db.get(User,uid); cached_course=db.get(Course,cid)
        with Session(canonical) as writer:
            item=writer.get(Course,cid) if changed=="course" else writer.get(User,uid)
            item.is_active=False; writer.commit()
        with pytest.raises(HTTPException) as error: create_enrollment(db,student_id=uid,course_id=cid)
        assert error.value.status_code==400
        assert db.scalar(select(func.count()).select_from(Enrollment))==0


def test_activation_and_enrollment_race_preserves_eligible_roster(canonical):
    from app.models import Session as AttendanceSession
    from app.services.access import get_session_for_mutation
    from app.services.enrollments import capture_roster
    now=utc_now()
    with Session(canonical) as db:
        student=User(email="roster@example.com",full_name="Roster",hashed_password="unused")
        teacher=User(email="teacher@example.com",full_name="Teacher",role="instructor",hashed_password="unused")
        db.add_all([student,teacher]); db.flush()
        course=Course(code="ROSTER",name="Roster",semester="AY26"); db.add(course); db.flush()
        session=AttendanceSession(course_id=course.id,instructor_id=teacher.id,name="Roster",
            scheduled_start=now,scheduled_end=now+timedelta(hours=1),checkin_opens_at=now,
            checkin_closes_at=now+timedelta(hours=1),venue_latitude=1.3483,venue_longitude=103.6831,geofence_radius_meters=100)
        db.add(session); db.flush(); uid,cid,sid=student.id,course.id,session.id; db.commit()
    barrier=Barrier(2)
    def change(operation):
        with Session(canonical) as db:
            barrier.wait(timeout=10)
            if operation=="activate":
                session=get_session_for_mutation(db,sid); capture_roster(db,session); session.status="active"
            else: create_enrollment(db,student_id=uid,course_id=cid)
            db.commit()
    with ThreadPoolExecutor(2) as pool: list(pool.map(change,["activate","enroll"]))
    with Session(canonical) as db: assert db.get(AttendanceSession,sid).attendance_roster==[uid]


def test_concurrent_bulk_creation_in_opposite_order_is_controlled(canonical):
    from app.routers.enrollments import bulk_enroll
    from app.schemas import BulkEnrollmentCreate
    with Session(canonical) as db:
        admin=User(email="admin@example.com",full_name="Admin",role="admin",hashed_password="unused")
        course=Course(code="BULK",name="Bulk",semester="AY26")
        db.add_all([admin,course]); db.flush(); uid,cid=admin.id,course.id; db.commit()
    barrier=Barrier(2)
    def create(emails):
        with Session(canonical) as db:
            actor=db.get(User,uid); barrier.wait(timeout=10)
            return bulk_enroll(BulkEnrollmentCreate(course_id=cid,student_emails=emails,create_accounts=True),request(),Response(),actor,db)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(create,[["first@example.com","second@example.com"],["second@example.com","first@example.com"]]))
    assert sum(r["created"] for r in results)==2
    assert sum(r["enrolled"] for r in results)==2
    # The losing batch sees inactive pending accounts; it cannot enroll/activate them.
    assert sum(r["not_found"] for r in results)==2
    assert sum(r["already_enrolled"] for r in results)==0
    with Session(canonical) as db: assert db.scalar(select(func.count()).select_from(Enrollment))==2


def test_retention_advisory_lock_prevents_overlap(canonical):
    from app.services.retention import cleanup_expired_records
    with Session(canonical) as owner, Session(canonical) as second:
        owner.execute(text("SELECT pg_advisory_xact_lock(309930)"))
        result = cleanup_expired_records(second)
        assert result == {"checkins_deleted":0,"users_anonymised":0}
        assert second.info["retention_overlap_skipped"]
        owner.rollback()
        assert cleanup_expired_records(second) == result


def test_concurrent_bad_passwords_preserve_tenth_attempt_lockout(canonical, monkeypatch):
    from app.schemas.auth import LoginRequest
    from app.security import hash_password
    monkeypatch.setattr(auth,"enforce_login_limit",lambda _:None)
    with Session(canonical) as db:
        user = User(email="blocked@example.com",full_name="Blocked",hashed_password=hash_password("securepass123"))
        db.add(user); db.commit()
    barrier = Barrier(12)
    def attempt(_):
        with Session(canonical) as db:
            barrier.wait(timeout=10)
            try:
                auth.login(LoginRequest(email="blocked@example.com",password="wrongpass123"),request(),db)
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(12) as pool:
        outcomes = list(pool.map(attempt, range(12)))
    assert outcomes.count(401)==9 and outcomes.count(429)==3
    with Session(canonical) as db:
        assert db.scalar(select(User.failed_login_attempts))==10


@pytest.mark.parametrize("operation,expected", [("review",409),("appeal",400)])
def test_concurrent_review_and_appeal_only_one_wins(canonical, operation, expected):
    from app.models import Checkin, Session as AttendanceSession
    from app.routers.checkins import review_checkin, appeal_checkin
    from app.schemas import CheckinReview, CheckinAppeal
    now = utc_now()
    with Session(canonical) as db:
        teacher = User(email="teacher@example.com",full_name="Teacher",role="instructor",hashed_password="unused")
        student = User(email="student@example.com",full_name="Student",hashed_password="unused")
        db.add_all([teacher,student]); db.flush()
        course = Course(code="RACE",name="Race",semester="AY26",instructor_id=teacher.id)
        db.add(course); db.flush()
        session = AttendanceSession(course_id=course.id,instructor_id=teacher.id,name="Race",
            scheduled_start=now,scheduled_end=now+timedelta(hours=1),checkin_opens_at=now,
            checkin_closes_at=now+timedelta(hours=1),venue_latitude=1.3483,venue_longitude=103.6831,
            geofence_radius_meters=100)
        db.add(session); db.flush()
        checkin = Checkin(student_id=student.id,session_id=session.id,checked_in_at=now,
            scheduled_deletion_at=now+timedelta(days=30),latitude=1.3483,longitude=103.6831,
            location_accuracy_meters=10,distance_from_venue_meters=0,status="flagged",risk_score=.5,risk_factors=[])
        db.add(checkin); db.flush()
        cid,uid = checkin.id, teacher.id if operation=="review" else student.id
        db.commit()
    barrier = Barrier(2)
    def change(_):
        with Session(canonical) as db:
            actor = db.get(User,uid)
            barrier.wait(timeout=10)
            try:
                if operation=="review":
                    review_checkin(cid,CheckinReview(status="approved",review_notes="Verified"),request(),db,actor)
                else:
                    appeal_checkin(cid,CheckinAppeal(appeal_reason="Please review this attendance"),request(),db,actor)
                return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(change,range(2))) == [200,expected]

pytestmark = pytest.mark.skipif(not os.environ.get("F00_POSTGRES_TEST_URL"), reason="Requires isolated PostgreSQL")


def request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1)})


@pytest.mark.parametrize("statement", ["UPDATE audit_logs SET action='changed'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"])
def test_audit_trigger_blocks_even_table_owner(canonical, statement):
    with canonical.begin() as connection:
        connection.execute(text("INSERT INTO audit_logs(id,action) VALUES(:id,'test')"), {"id": str(uuid4())})
    with pytest.raises(DBAPIError):
        with canonical.begin() as connection:
            connection.execute(text(statement))
    with canonical.connect() as connection:
        assert connection.scalar(text("SELECT action FROM audit_logs")) == "test"


def test_restricted_application_and_reader_roles(canonical):
    suffix = uuid4().hex
    app_url = canonical.url.set(username="completion_app_" + suffix, password=token_urlsafe(32))
    reader_url = canonical.url.set(username="completion_reader_" + suffix, password=token_urlsafe(32))
    with canonical.begin() as connection:
        configure(connection, canonical.url, app_url, reader_url)
    application, reader = create_engine(app_url), create_engine(reader_url)
    try:
        assert inspect_readiness(application).healthy
        with application.begin() as connection:
            connection.execute(text("INSERT INTO audit_logs(id,action) VALUES(:id,'test')"), {"id": str(uuid4())})
        for statement in ["UPDATE audit_logs SET action='changed'", "DELETE FROM audit_logs", "TRUNCATE audit_logs",
                          "CREATE TABLE forbidden(id int)", "UPDATE alembic_version SET version_num='wrong'"]:
            with pytest.raises(DBAPIError):
                with application.begin() as connection:
                    connection.execute(text(statement))
        with reader.connect() as connection:
            connection.execute(text("SELECT id,email FROM users"))
        for statement in ["SELECT hashed_password FROM users", "UPDATE courses SET name='changed'", "DELETE FROM audit_logs"]:
            with pytest.raises(DBAPIError):
                with reader.begin() as connection:
                    connection.execute(text(statement))
    finally:
        application.dispose()
        reader.dispose()
        with canonical.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            for url in [app_url, reader_url]:
                connection.execute(text("DROP OWNED BY " + quote(url.username)))
                connection.execute(text("DROP ROLE " + quote(url.username)))


def test_audit_trigger_disabled_or_replaced_is_not_ready(canonical):
    with canonical.begin() as connection:
        connection.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_append_only"))
    assert not inspect_readiness(canonical).healthy
    with canonical.begin() as connection:
        connection.execute(text("ALTER TABLE audit_logs ENABLE ALWAYS TRIGGER audit_logs_append_only"))
        connection.execute(text("CREATE OR REPLACE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END; $$"))
    assert not inspect_readiness(canonical).healthy


def test_concurrent_registration_conflict_is_controlled(canonical, monkeypatch):
    monkeypatch.setattr(auth, "enforce_registration_limit", lambda _: None)
    barrier = Barrier(2)
    def synchronize(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT users.") and "WHERE users.email =" in statement:
            barrier.wait(timeout=10)
    event.listen(canonical, "after_cursor_execute", synchronize)
    payload = UserRegister(email="race@example.com", password="securepass123", full_name="Race")
    def register():
        with Session(canonical) as database:
            try:
                auth.register(payload, request(), database)
                return 201
            except HTTPException as exc:
                return exc.status_code
    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(lambda _: register(), range(2))) == [201, 400]
    finally:
        event.remove(canonical, "after_cursor_execute", synchronize)
    with Session(canonical) as database:
        assert database.scalar(select(func.count()).select_from(User)) == 1
        assert database.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "user_created")) == 1


def test_concurrent_enrollment_preserves_single_row(canonical):
    with Session(canonical) as database:
        user = User(email="student@example.com", full_name="Student", hashed_password="unused")
        course = Course(code="TEST", name="Test", semester="AY26")
        database.add_all([user, course])
        database.commit()
        uid, cid = user.id, course.id
    barrier = Barrier(2)
    def enroll():
        with Session(canonical) as database:
            barrier.wait(timeout=10)
            try:
                create_enrollment(database, student_id=uid, course_id=cid)
                database.commit()
                return 201
            except HTTPException as exc:
                database.rollback()
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: enroll(), range(2))) == [201, 400]
    with Session(canonical) as database:
        assert database.scalar(select(func.count()).select_from(Enrollment)) == 1


def test_activation_row_lock_consumes_token_once(canonical, monkeypatch):
    monkeypatch.setattr(auth, "enforce_registration_limit", lambda _: None)
    token = token_urlsafe(32)
    with Session(canonical) as database:
        database.add(User(email="invite@example.com", full_name="Invite", hashed_password="unused", is_active=False,
                          activation_token_hash=sha256(token.encode()).hexdigest(), activation_expires_at=utc_now() + timedelta(hours=24)))
        database.commit()
    barrier = Barrier(2)
    def activate():
        with Session(canonical) as database:
            barrier.wait(timeout=10)
            try:
                auth.activate(ActivationRequest(token=token, password="securepass123"), request(), Response(), database)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: activate(), range(2))) == [200, 400]


def test_real_redis_challenge_consumption_is_atomic():
    payload = CheckinCreate(session_id=uuid4(), latitude=1.3483, longitude=103.6831,
                            location_accuracy_meters=10, device_fingerprint="test")
    device = SimpleNamespace(id=str(uuid4()), public_key=PUBLIC_KEY)
    issued = issue_challenge(device, payload, str(uuid4()))
    from app.rate_limit import get_redis_client
    key = "device-proof:" + issued["challenge_id"]
    client = get_redis_client()
    assert 0 < client.ttl(key) <= 120
    expected = client.get(key)
    payload.device_challenge_id = issued["challenge_id"]
    barrier = Barrier(2)
    def consume():
        barrier.wait(timeout=10)
        try:
            consume_proof(payload, expected)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: consume(), range(2))) == [200, 403]
