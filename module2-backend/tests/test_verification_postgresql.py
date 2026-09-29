"""Real PostgreSQL finalization races, using separately committed connections."""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as DatabaseSession, sessionmaker
from starlette.requests import Request

from app.face_service import EnrollmentResult, LivenessResult, VerificationResult
from app.models import AuditLog, Checkin, Course, Device, Enrollment, Session, User, utc_now
from app.routers import checkins, users
from app.schemas import CheckinCreate, FaceEnrollmentCreate
from scripts.database_evidence import create_isolated_database, migration_config

SOURCE = os.environ.get("F00_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not SOURCE, reason="Set F00_POSTGRES_TEST_URL for real PostgreSQL races")


@pytest.fixture(scope="module")
def pg_engine():
    name = "saiv_f00_test_verification_" + uuid4().hex
    target = create_isolated_database(SOURCE, name)
    engine = create_engine(target, connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=5000"})
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine
    finally:
        engine.dispose()
        assert name.startswith("saiv_f00_test_verification_") and name != make_url(SOURCE).database
        admin = create_engine(make_url(SOURCE).set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text("DROP DATABASE " + connection.dialect.identifier_preparer.quote(name)))
        admin.dispose()


@pytest.fixture
def records(pg_engine, monkeypatch):
    monkeypatch.setattr(checkins, "enforce_checkin_limit", lambda _: None)
    ids = {key: str(uuid4()) for key in ["user", "teacher", "course", "session", "enrollment", "device"]}
    now = utc_now()
    factory = sessionmaker(pg_engine, autoflush=False, expire_on_commit=True)
    with factory() as db:
        db.add_all([User(id=ids["user"], email=ids["user"] + "@example.com", full_name="Student", hashed_password="unused",
                         role="student", camera_consent=True, geolocation_consent=True,
                         face_enrolled=True, face_embedding_hash="a" * 64),
                    User(id=ids["teacher"], email=ids["teacher"] + "@example.com", full_name="Teacher", hashed_password="unused", role="instructor")])
        db.flush()
        db.add(Course(id=ids["course"], code=uuid4().hex[:15], name="Race", semester="AY26", instructor_id=ids["teacher"],
                      venue_latitude=1.3483, venue_longitude=103.6831))
        db.flush()
        db.add_all([Session(id=ids["session"], course_id=ids["course"], instructor_id=ids["teacher"], name="Race", status="active",
                            scheduled_start=now, scheduled_end=now + timedelta(hours=1),
                            checkin_opens_at=now - timedelta(minutes=1), checkin_closes_at=now + timedelta(hours=1),
                            venue_latitude=1.3483, venue_longitude=103.6831, geofence_radius_meters=100,
                            require_liveness_check=True, require_face_match=True, risk_threshold=.5),
                    Enrollment(id=ids["enrollment"], course_id=ids["course"], student_id=ids["user"]),
                    Device(id=ids["device"], user_id=ids["user"], device_fingerprint=ids["device"], public_key=None,
                           last_seen_at=now - timedelta(days=1), total_checkins=3)])
        db.commit()
    payload = CheckinCreate(session_id=ids["session"], latitude=1.3483, longitude=103.6831,
                            location_accuracy_meters=10, device_fingerprint=ids["device"], liveness_challenge_response="private-image")
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    return factory, ids, payload, request


@pytest.mark.parametrize("model,key,field,value,expected", [
    (Session, "session", "require_liveness_check", False, 409),
    (Session, "session", "require_face_match", False, 409),
    (User, "user", "face_embedding_hash", "b" * 64, 409),
    (User, "user", "is_active", False, 401),
    (User, "user", "role", "instructor", 403),
    (User, "user", "camera_consent", False, 403),
    (User, "user", "geolocation_consent", False, 403),
    (User, "user", "face_enrolled", False, 400),
    (Course, "course", "is_active", False, 400),
    (Enrollment, "enrollment", "is_active", False, 403),
    (Session, "session", "status", "closed", 400),
    (Session, "session", "checkin_closes_at", "past", 400),
])
def test_changes_during_verification_block_finalization(records, monkeypatch, model, key, field, value, expected):
    factory, ids, payload, request = records
    with factory() as db:
        original_seen = db.get(Device, ids["device"]).last_seen_at
        current = db.get(User, ids["user"])

        async def live(image):
            assert image == "private-image" and not db.in_transaction()
            with factory() as writer:
                row = writer.get(model, ids[key])
                setattr(row, field, utc_now() - timedelta(minutes=1) if value == "past" else value)
                writer.commit()
            return LivenessResult(liveness_passed=True, liveness_score=.8, liveness_threshold=.6)

        async def face(reference, image):
            assert reference == "a" * 64 and not db.in_transaction()
            return VerificationResult(match_passed=True, match_score=.9, match_threshold=.7, face_detected=True)

        monkeypatch.setattr(checkins, "check_liveness", live)
        monkeypatch.setattr(checkins, "verify_face", face)
        with pytest.raises(HTTPException) as failure:
            asyncio.run(checkins.create_checkin(payload, request, current, db))
        assert failure.value.status_code == expected
    with factory() as db:
        assert db.scalar(select(func.count(Checkin.id)).where(Checkin.session_id == ids["session"])) == 0
        device = db.get(Device, ids["device"])
        assert device.total_checkins == 3 and device.last_seen_at == original_seen
        events = db.scalars(select(AuditLog).where(AuditLog.resource_id == ids["session"])).all()
        assert [e.action for e in events] == ["checkin_attempted", "checkin_rejected"]
        assert "private-image" not in str([e.details for e in events])


def test_enabling_face_during_liveness_requires_retry(records, monkeypatch):
    factory, ids, payload, request = records
    with factory() as writer:
        writer.get(Session, ids["session"]).require_face_match = False
        writer.commit()
    async def live(image):
        with factory() as writer:
            writer.get(Session, ids["session"]).require_face_match = True
            writer.commit()
        return LivenessResult(liveness_passed=True, liveness_score=.8, liveness_threshold=.6)
    monkeypatch.setattr(checkins, "check_liveness", live)
    with factory() as db:
        with pytest.raises(HTTPException) as failure:
            asyncio.run(checkins.create_checkin(payload, request, db.get(User, ids["user"]), db))
        assert failure.value.status_code == 409


@pytest.mark.parametrize("changes,status,score", [({"risk_threshold": 0}, "flagged", .275),
                                                 ({"venue_latitude": 1.351}, "rejected", .425),
                                                 ({"geofence_radius_meters": .1}, "approved", .3125)])
def test_finalization_uses_current_scoring_settings(records, monkeypatch, changes, status, score):
    factory, ids, payload, request = records
    async def live(image):
        with factory() as writer:
            row = writer.get(Session, ids["session"])
            for field, value in changes.items():
                setattr(row, field, value)
            writer.commit()
        return LivenessResult(liveness_passed=True, liveness_score=.8, liveness_threshold=.6)
    async def face(reference, image):
        return VerificationResult(match_passed=True, match_score=.9, match_threshold=.7, face_detected=True)
    monkeypatch.setattr(checkins, "check_liveness", live)
    monkeypatch.setattr(checkins, "verify_face", face)
    with factory() as db:
        result = asyncio.run(checkins.create_checkin(payload, request, db.get(User, ids["user"]), db))
        assert result.status == status and result.risk_score == pytest.approx(score)


def test_simultaneous_checkins_have_one_row_and_one_counter_increment(records, monkeypatch):
    factory, ids, payload, request = records
    barrier = Barrier(2, timeout=10)
    async def live(image):
        barrier.wait()
        return LivenessResult(liveness_passed=True, liveness_score=.8, liveness_threshold=.6)
    async def face(reference, image):
        return VerificationResult(match_passed=True, match_score=.9, match_threshold=.7, face_detected=True)
    monkeypatch.setattr(checkins, "check_liveness", live)
    monkeypatch.setattr(checkins, "verify_face", face)
    def submit():
        with factory() as db:
            try:
                asyncio.run(checkins.create_checkin(payload, request, db.get(User, ids["user"]), db))
                return 201
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: submit(), range(2))) == [201, 400]
    with factory() as db:
        assert db.scalar(select(func.count(Checkin.id)).where(Checkin.session_id == ids["session"])) == 1
        assert db.get(Device, ids["device"]).total_checkins == 4


@pytest.mark.parametrize("field,value,expected", [("camera_consent", False, 400), ("is_active", False, 401)])
def test_enrollment_rechecks_account_and_consent_after_service(records, monkeypatch, field, value, expected):
    factory, ids, _, request = records
    with factory() as db:
        current = db.get(User, ids["user"])
        async def enroll(user_id, image):
            assert not db.in_transaction()
            with factory() as writer:
                setattr(writer.get(User, user_id), field, value)
                writer.commit()
            return EnrollmentResult(enrollment_successful=True, quality_score=.9, face_template_hash="b" * 64,
                                    details={"face_detected": True, "face_detection_confidence": .9})
        monkeypatch.setattr(users, "enroll_face", enroll)
        with pytest.raises(HTTPException) as failure:
            asyncio.run(users.enroll_my_face(FaceEnrollmentCreate(image="image"), request, current, db))
        assert failure.value.status_code == expected
        db.rollback()
    with factory() as db:
        assert db.get(User, ids["user"]).face_embedding_hash == "a" * 64
