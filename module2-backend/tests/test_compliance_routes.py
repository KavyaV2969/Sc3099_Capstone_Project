"""Seeded route checks for the newly documented backend surface."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.dependencies import get_current_user
from app.main import app
from app.face_service import FaceResult
from app.models import AuditLog, Base, Checkin, Course, Device, Enrollment, Session as AttendanceSession, User


@pytest.fixture
def compliance_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    ids = {name: str(uuid4()) for name in ("admin", "instructor", "student", "student2", "course", "session", "checkin")}
    with Session(engine) as database:
        database.add_all([
            User(id=ids["admin"], email="admin@example.com", full_name="Admin", hashed_password="unused", role="admin"),
            User(id=ids["instructor"], email="teacher@example.com", full_name="Teacher", hashed_password="unused", role="instructor"),
            User(id=ids["student"], email="student@example.com", full_name="Student", hashed_password="unused",
                 role="student", camera_consent=True),
            User(id=ids["student2"], email="student2@example.com", full_name="Student Two", hashed_password="unused", role="student"),
            Course(id=ids["course"], code="SC3099", name="Capstone", semester="AY26",
                   instructor_id=ids["instructor"], venue_latitude=1.3483, venue_longitude=103.6831),
            Enrollment(student_id=ids["student"], course_id=ids["course"]),
            AttendanceSession(id=ids["session"], course_id=ids["course"], instructor_id=ids["instructor"],
                              name="Review Session", status="closed", scheduled_start=now - timedelta(hours=1),
                              scheduled_end=now, checkin_opens_at=now - timedelta(hours=1, minutes=15),
                              checkin_closes_at=now - timedelta(minutes=30), venue_latitude=1.3483,
                              venue_longitude=103.6831, geofence_radius_meters=100),
            Checkin(id=ids["checkin"], session_id=ids["session"], student_id=ids["student"],
                    checked_in_at=now - timedelta(minutes=55), latitude=1.3483, longitude=103.6831,
                    location_accuracy_meters=5, distance_from_venue_meters=0, status="flagged",
                    risk_score=.55, risk_factors=[{"type": "device"}],
                    scheduled_deletion_at=now + timedelta(days=30)),
        ])
        database.commit()

    def override_database():
        with Session(engine) as database:
            yield database

    def override_user(request: Request, database: Session = Depends(get_db)):
        selected = request.headers.get("x-test-user", "admin")
        return database.get(User, ids[selected])

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_current_user] = override_user
    with TestClient(app) as client:
        yield client, engine, ids
    app.dependency_overrides.clear()
    engine.dispose()


def test_seeded_statistics_are_zero_safe_and_consistent(compliance_api):
    client, _, ids = compliance_api
    overview = client.get("/api/v1/stats/overview").json()
    session = client.get(f"/api/v1/stats/sessions/{ids['session']}").json()
    course = client.get(f"/api/v1/stats/courses/{ids['course']}").json()
    student = client.get(f"/api/v1/stats/students/{ids['student']}").json()
    assert overview["total_sessions"] == 1 and overview["approval_rate"] == 0
    assert session["checked_in"] == 1 and session["risk_distribution"]["high"] == 1
    assert course["total_enrolled"] == 1 and course["overall_attendance_rate"] == 1
    assert student["courses"][0]["attendance_rate"] == 1


def test_appeal_review_and_audit_transitions(compliance_api):
    client, engine, ids = compliance_api
    appealed = client.post(
        f"/api/v1/checkins/{ids['checkin']}/appeal",
        headers={"x-test-user": "student"},
        json={"appeal_reason": "The indoor GPS reading was inaccurate."},
    )
    assert appealed.status_code == 200 and appealed.json()["status"] == "appealed"
    reviewed = client.post(
        f"/api/v1/checkins/{ids['checkin']}/review",
        headers={"x-test-user": "instructor"},
        json={"status": "approved", "review_notes": "Verified against the class record."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved" and reviewed.json()["verified_at"]
    with Session(engine) as database:
        actions = set(database.scalars(select(AuditLog.action)))
        assert {"checkin_appealed", "checkin_reviewed"} <= actions


def test_devices_bulk_enrollment_and_exports(compliance_api):
    client, engine, ids = compliance_api
    device = client.post(
        "/api/v1/devices/register", headers={"x-test-user": "student"},
        json={"device_fingerprint": "fingerprint", "device_name": "Phone",
              "platform": "ios", "public_key": "public-key"},
    )
    assert device.status_code == 201
    device_id = device.json()["id"]
    assert client.patch(
        f"/api/v1/devices/{device_id}", headers={"x-test-user": "student"},
        json={"is_trusted": True},
    ).status_code == 403
    assert client.patch(f"/api/v1/devices/{device_id}", json={"is_trusted": True}).json()["is_trusted"]
    bulk = client.post(
        "/api/v1/enrollments/bulk", headers={"x-test-user": "instructor"},
        json={"course_id": ids["course"], "student_emails": ["student2@example.com"],
              "create_accounts": False},
    )
    assert bulk.status_code == 200 and bulk.json()["enrolled"] == 1
    csv_export = client.get(f"/api/v1/export/session/{ids['session']}?format=csv")
    json_export = client.get(f"/api/v1/export/session/{ids['session']}?format=json")
    assert csv_export.status_code == 200 and csv_export.text.startswith("student_id,student_name")
    assert "attachment;" in csv_export.headers["content-disposition"]
    assert json_export.json()["summary"]["total"] == 1
    assert client.delete(
        f"/api/v1/devices/{device_id}", headers={"x-test-user": "student"}
    ).status_code == 204
    with Session(engine) as database:
        assert not database.get(Device, device_id).is_active
        assert database.scalar(select(AuditLog).where(AuditLog.action == "data_exported"))


def test_user_visibility_admin_updates_and_face_hash_only(compliance_api, monkeypatch):
    client, engine, ids = compliance_api
    assert client.get("/api/v1/users/").json()["total"] == 4
    assert client.get(
        f"/api/v1/users/{ids['student']}", headers={"x-test-user": "instructor"}
    ).status_code == 200
    assert client.get(
        f"/api/v1/users/{ids['student2']}", headers={"x-test-user": "instructor"}
    ).status_code == 403
    with Session(engine) as database:
        student = database.get(User, ids["student"])
        student.failed_login_attempts = 10
        student.is_active = False
        database.commit()
    updated = client.patch(
        f"/api/v1/users/{ids['student']}", json={"is_active": True}
    )
    assert updated.status_code == 200

    async def fake_enroll(user_id: str, image: str):
        assert user_id == ids["student"] and image == "transient-image"
        return FaceResult(
            enrollment_successful=True, face_template_hash="a" * 64, quality_score=.9
        )

    monkeypatch.setattr("app.routers.users.enroll_face", fake_enroll)
    enrolled = client.post(
        "/api/v1/users/me/face/enroll", headers={"x-test-user": "student"},
        json={"image": "transient-image"},
    )
    assert enrolled.status_code == 200 and enrolled.json()["quality_score"] == .9
    with Session(engine) as database:
        student = database.get(User, ids["student"])
        assert student.failed_login_attempts == 0
        assert student.face_embedding_hash == "a" * 64
        assert "transient-image" not in str(database.scalars(select(AuditLog.details)).all())
