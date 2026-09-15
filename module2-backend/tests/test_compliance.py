"""Coverage for the documented compliance additions."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.dependencies import get_current_user
from app.models import AuditLog, Base, Checkin, Course, Session as AttendanceSession, User
from app.risk import assess_risk
from app.schemas import CheckinStatus
from app.services.retention import cleanup_expired_records


def test_openapi_contains_all_documented_backend_routes():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/users/", "/api/v1/users/{user_id}",
        "/api/v1/checkins/", "/api/v1/checkins/flagged", "/api/v1/checkins/{checkin_id}",
        "/api/v1/checkins/{id}/appeal", "/api/v1/checkins/{id}/review",
        "/api/v1/stats/overview", "/api/v1/stats/sessions/{session_id}",
        "/api/v1/stats/courses/{course_id}", "/api/v1/stats/students/{student_id}",
        "/api/v1/devices/register", "/api/v1/devices/my-devices", "/api/v1/devices/{device_id}",
        "/api/v1/enrollments/bulk", "/api/v1/export/attendance/{course_id}",
        "/api/v1/export/session/{session_id}", "/api/v1/admin/users/bulk",
        "/api/v1/admin/enrollments/",
    }
    assert expected <= paths
    assert "/api/v1/audit/summary" not in paths
    assert "/api/v1/admin/devices" not in paths


def test_all_id_paths_reject_non_uuid_values():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=str(uuid4()), email="admin@example.com", full_name="Admin",
        hashed_password="unused", role="admin",
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/checkins/not-a-uuid")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


def test_weighted_risk_uses_documented_bands_and_critical_rejection():
    medium = assess_risk(
        distance=0, radius=100, location_accuracy=5,
        liveness_score=.8, liveness_passed=True, face_score=.8, face_passed=True,
        known_device=False, trusted_device=False, local_network=True, threshold=.5,
    )
    critical = assess_risk(
        distance=10, radius=100, location_accuracy=5,
        liveness_score=.8, liveness_passed=False, face_score=.9, face_passed=True,
        known_device=True, trusted_device=True, local_network=True, threshold=.5,
    )
    assert medium.status == "approved"
    assert 0 <= medium.score < .5
    assert critical.status == "rejected"


def test_retention_deletes_checkins_anonymises_users_and_keeps_audit():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    student_id, instructor_id, course_id, session_id = map(lambda _: str(uuid4()), range(4))
    with Session(engine) as database:
        database.add_all([
            User(id=student_id, email="student@example.com", full_name="Student", hashed_password="old",
                 role="student", scheduled_deletion_at=now - timedelta(seconds=1),
                 camera_consent=True, geolocation_consent=True, face_enrolled=True),
            User(id=instructor_id, email="teacher@example.com", full_name="Teacher", hashed_password="old", role="instructor"),
            Course(id=course_id, code="TEST", name="Test", semester="AY26", instructor_id=instructor_id,
                   venue_latitude=1.3, venue_longitude=103.8),
            AttendanceSession(id=session_id, course_id=course_id, instructor_id=instructor_id, name="One",
                              scheduled_start=now, scheduled_end=now + timedelta(hours=1),
                              checkin_opens_at=now - timedelta(minutes=1), checkin_closes_at=now + timedelta(minutes=30),
                              venue_latitude=1.3, venue_longitude=103.8, geofence_radius_meters=100),
            Checkin(session_id=session_id, student_id=student_id, checked_in_at=now - timedelta(days=31),
                    scheduled_deletion_at=now - timedelta(days=1), latitude=1.3, longitude=103.8,
                    location_accuracy_meters=1, distance_from_venue_meters=0, status="approved", risk_score=0),
            AuditLog(user_id=student_id, action="checkin_approved", details={"risk_score": 0}),
        ])
        database.commit()
        first = cleanup_expired_records(database, now=now)
        second = cleanup_expired_records(database, now=now)
        student = database.get(User, student_id)
        assert first == {"checkins_deleted": 1, "users_anonymised": 1}
        assert second == {"checkins_deleted": 0, "users_anonymised": 0}
        assert database.scalar(select(Checkin)) is None
        assert database.scalar(select(AuditLog)).details == {"risk_score": 0}
        assert student.email.endswith("@deleted.invalid")
        assert student.full_name == "Deleted User"
        assert not student.is_active and not student.camera_consent and not student.face_enrolled
    engine.dispose()


def test_checkin_status_includes_appealed():
    assert CheckinStatus.APPEALED.value == "appealed"
