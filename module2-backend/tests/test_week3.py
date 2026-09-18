"""Focused Week 3 API tests with real JWTs and an isolated SQLite database."""
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import dependencies
from app.db import get_db
from app.main import app
from app.models import AuditLog, Base, Checkin, Course, CourseTA, Enrollment, Session, User, utc_now
from app.schemas import UserRole, as_utc
from app.security import create_access_token
from app.utils.geolocation import haversine_distance


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    with factory() as database:
        users = {}
        for label in ("admin", "instructor", "other_instructor", "student", "other_student", "ta"):
            role = label.removeprefix("other_")
            user = User(email=f"{label}@example.com", full_name=label, role=role,
                        hashed_password="unused", camera_consent=True, geolocation_consent=True)
            database.add(user)
            database.flush()
            users[label] = user
        database.commit()
    def override_db():
        with factory() as database:
            try:
                yield database
            except Exception:
                database.rollback()
                raise
    monkeypatch.setattr(dependencies, "enforce_user_api_limit", lambda _: None)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        class API:
            def request(self, method, path, role="instructor", **kwargs):
                headers = {"X-Forwarded-For": "127.0.0.1"}
                if role:
                    user = users[role]
                    token = create_access_token(user.id, user.email, UserRole(user.role))
                    headers["Authorization"] = f"Bearer {token}"
                headers.update(kwargs.pop("headers", {}))
                return client.request(method, "/api/v1" + path, headers=headers, **kwargs)
        api = API()
        api.users, api.database = users, factory
        yield api
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def course(api):
    response = api.request("POST", "/courses/", "admin", json={
        "code": "SC3099", "name": "Capstone", "semester": "AY2026-27 Sem 1",
        "instructor_id": api.users["instructor"].id, "venue_name": "LT1",
        "venue_latitude": 1.3483, "venue_longitude": 103.6831,
        "geofence_radius_meters": 100,
    })
    assert response.status_code == 201, response.text
    return response.json()


def session_payload(course):
    start = utc_now() + timedelta(minutes=5)
    return {"course_id": course["id"], "name": "Lecture 1", "session_type": "lecture",
            "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(hours=1)).isoformat()}


@pytest.fixture
def session(api, course):
    response = api.request("POST", "/sessions/", json=session_payload(course))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def enrollment(api, course):
    response = api.request("POST", "/enrollments/", json={
        "course_id": course["id"], "student_id": api.users["student"].id})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ready(api, session, enrollment):
    response = api.request("PATCH", f"/sessions/{session['id']}", json={"status": "active"})
    assert response.status_code == 200, response.text
    return response.json()


def checkin_payload(session, **changes):
    return {"session_id": session["id"], "latitude": 1.3483, "longitude": 103.6831,
            "location_accuracy_meters": 10.0, "device_fingerprint": "test-device", **changes}


def test_course_crud_and_filters(api, course):
    assert course["instructor_name"] == "instructor"
    response = api.request("GET", f"/courses/{course['id']}", "student")
    assert response.json()["code"] == "SC3099"
    response = api.request("PUT", f"/courses/{course['id']}", "admin", json={"name": "Updated"})
    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    response = api.request("GET", "/courses/?semester=AY2026-27%20Sem%201&limit=1&offset=0", "student")
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1
    assert api.request("GET", "/courses/?offset=1", "student").json()["items"] == []
    assert api.request("DELETE", f"/courses/{course['id']}", "admin").status_code == 204
    assert api.request("GET", "/courses/", "student").json()["total"] == 0
    assert api.request("GET", "/courses/?is_active=false", "student").json()["total"] == 1
    with api.database() as database:
        assert database.get(Course, course["id"]).is_active is False


@pytest.mark.parametrize("role", ["student", "ta", "instructor"])
def test_course_create_requires_admin(api, course, role):
    assert api.request("POST", "/courses/", role, json=course).status_code == 403


@pytest.mark.parametrize("changes", [{"code": " "}, {"name": " "}, {"venue_latitude": 91},
                                     {"venue_longitude": -181}, {"geofence_radius_meters": 0},
                                     {"risk_threshold": 1.1}, {"name": None}])
def test_course_update_validation(api, course, changes):
    assert api.request("PUT", f"/courses/{course['id']}", "admin", json=changes).status_code == 422


def test_course_ownership_and_instructor_validation(api, course):
    path = f"/courses/{course['id']}"
    assert api.request("PUT", path, "instructor", json={"name": "No"}).status_code == 403
    assert api.request("PUT", path, "other_instructor", json={"name": "No"}).status_code == 403
    assert api.request("DELETE", path).status_code == 403
    assert api.request("PUT", path, "admin", json={"instructor_id": str(uuid4())}).status_code == 404
    assert api.request("PUT", path, "admin", json={"instructor_id": api.users["student"].id}).status_code == 400
    assert api.request("POST", "/courses/", "admin", json=course).status_code == 400
    assert api.request("GET", f"/courses/{uuid4()}").status_code == 404
    assert api.request("GET", "/courses/", None).status_code == 401


def test_enrollment_roster_duplicate_and_remove(api, course, enrollment):
    payload = {"course_id": course["id"], "student_id": api.users["student"].id}
    assert api.request("POST", "/enrollments/", json=payload).status_code == 400
    roster = api.request("GET", f"/enrollments/course/{course['id']}").json()
    assert roster["total_enrolled"] == 1
    assert roster["students"][0]["student_email"] == "student@example.com"
    assert "hashed_password" not in str(roster)
    assert api.request("GET", f"/enrollments/course/{course['id']}?search=missing").json()["students"] == []
    mine = api.request("GET", "/enrollments/my-enrollments", "student").json()
    assert mine[0]["course_code"] == course["code"]
    assert api.request("GET", "/enrollments/my-enrollments", "other_student").json() == []
    assert api.request("DELETE", f"/enrollments/{enrollment['id']}", "other_instructor").status_code == 403
    assert api.request("DELETE", f"/enrollments/{enrollment['id']}", "admin").status_code == 204
    assert api.request("GET", "/enrollments/my-enrollments", "student").json() == []
    assert api.request("POST", "/enrollments/", "admin", json=payload).status_code == 201


def test_enrollment_role_ownership_and_missing_users(api, course):
    path = "/enrollments/"
    payload = {"course_id": course["id"], "student_id": api.users["instructor"].id}
    assert api.request("POST", path, json=payload).status_code == 400
    payload["student_id"] = str(uuid4())
    assert api.request("POST", path, json=payload).status_code == 404
    payload["student_id"] = api.users["student"].id
    assert api.request("POST", path, "other_instructor", json=payload).status_code == 403
    assert api.request("POST", path, "student", json=payload).status_code == 403
    assert api.request("GET", f"/enrollments/course/{course['id']}", "other_instructor").status_code == 403


def test_ta_access_requires_course_assignment(api, course, session, enrollment):
    path = f"/enrollments/course/{course['id']}"
    assert api.request("GET", path, "ta").status_code == 403
    assert api.request("GET", "/sessions/my-sessions", "ta").json() == []
    with api.database() as database:
        database.add(CourseTA(course_id=course["id"], ta_id=api.users["ta"].id))
        database.commit()
    assert api.request("GET", path, "ta").status_code == 200
    assert len(api.request("GET", "/sessions/my-sessions", "ta").json()) == 1
    assert api.request("DELETE", f"/enrollments/{enrollment['id']}", "ta").status_code == 403


def test_session_defaults_workflow_and_reverse_transition(api, session, course):
    assert session["status"] == "scheduled"
    assert session["venue_latitude"] == course["venue_latitude"]
    from datetime import datetime
    start = datetime.fromisoformat(session["scheduled_start"].replace("Z", "+00:00"))
    opens = datetime.fromisoformat(session["checkin_opens_at"].replace("Z", "+00:00"))
    closes = datetime.fromisoformat(session["checkin_closes_at"].replace("Z", "+00:00"))
    assert start - opens == timedelta(minutes=15)
    assert closes - start == timedelta(minutes=30)
    path = f"/sessions/{session['id']}"
    for status in ("active", "closed"):
        response = api.request("PATCH", path, json={"status": status})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status
    assert api.request("PATCH", path, json={"status": "active"}).status_code == 400
    assert api.request("GET", path, "student").json()["status"] == "closed"
    assert api.request("DELETE", path).status_code == 400


@pytest.mark.parametrize("initial", ["scheduled", "active"])
def test_cancellation_is_terminal(api, session, initial):
    path = f"/sessions/{session['id']}"
    if initial == "active":
        assert api.request("PATCH", path, json={"status": "active"}).status_code == 200
    assert api.request("PATCH", path, json={"status": "cancelled"}).status_code == 200
    assert api.request("PATCH", path, json={"status": "active"}).status_code == 400
    assert api.request("DELETE", path).status_code == 400


def test_session_delete_and_ownership(api, session, course):
    path = f"/sessions/{session['id']}"
    assert api.request("PATCH", path, "other_instructor", json={"name": "No"}).status_code == 403
    assert api.request("DELETE", path, "other_instructor").status_code == 403
    assert api.request("POST", "/sessions/", "other_instructor", json=session_payload(course)).status_code == 403
    assert api.request("POST", "/sessions/", "admin", json=session_payload(course)).status_code == 201
    assert api.request("DELETE", path).status_code == 204
    assert api.request("GET", path).status_code == 404


def test_session_time_validation_on_create_and_partial_update(api, session, course):
    payload = session_payload(course)
    payload["scheduled_end"] = payload["scheduled_start"]
    assert api.request("POST", "/sessions/", json=payload).status_code == 422
    payload = session_payload(course)
    payload["scheduled_start"] = (utc_now() - timedelta(hours=1)).isoformat()
    assert api.request("POST", "/sessions/", json=payload).status_code == 422
    path = f"/sessions/{session['id']}"
    for changes in ({"scheduled_end": session["scheduled_start"]},
                    {"checkin_closes_at": session["checkin_opens_at"]}, {"status": None},
                    {"scheduled_start": None}, {"venue_latitude": 91}):
        assert api.request("PATCH", path, json=changes).status_code == 422
    assert api.request("PATCH", path, json={"status": "active"}).status_code == 200
    assert api.request("DELETE", path).status_code == 400


def test_session_lists_are_scoped_and_public_window_filtered(api, ready, course):
    assert len(api.request("GET", "/sessions/active", None).json()) == 1
    assert len(api.request("GET", "/sessions/my-sessions", "student").json()) == 1
    assert api.request("GET", "/sessions/my-sessions", "other_student").json() == []
    assert api.request("GET", "/sessions/", "other_instructor").json()["total"] == 0
    assert api.request("GET", "/sessions/", "student").status_code == 403
    assert api.request("GET", "/sessions/?status=active", "admin").json()["total"] == 1
    assert api.request("GET", "/sessions/?status=closed", "admin").json()["total"] == 0
    assert api.request("GET", "/sessions/?offset=1", "admin").json()["items"] == []
    with api.database() as database:
        row = database.get(Session, ready["id"])
        row.checkin_opens_at = utc_now() + timedelta(minutes=10)
        database.commit()
    assert api.request("GET", "/sessions/active", None).json() == []


@pytest.mark.parametrize("latitude,status,risk", [(1.3483, "approved", 0.0),
                                                 (1.34965, "flagged", 0.5),
                                                 (1.351, "rejected", 1.0)])
def test_checkin_geofence_stored_with_audit(api, ready, latitude, status, risk):
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, latitude=latitude))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == status
    assert result["risk_score"] == risk
    assert result["liveness_passed"] is None
    assert result["student_id"] == api.users["student"].id
    with api.database() as database:
        assert database.get(Checkin, result["id"]).status == status
        actions = database.scalars(select(AuditLog.action)).all()
        assert "checkin_attempted" in actions
        assert f"checkin_{status}" in actions
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 400


def test_checkin_requires_enrollment_role_and_existing_session(api, ready):
    payload = checkin_payload(ready)
    assert api.request("POST", "/checkins/", "other_student", json=payload).status_code == 403
    assert api.request("POST", "/checkins/", "instructor", json=payload).status_code == 403
    assert api.request("POST", "/checkins/", None, json=payload).status_code == 401
    payload["session_id"] = str(uuid4())
    assert api.request("POST", "/checkins/", "student", json=payload).status_code == 404


@pytest.mark.parametrize("status", ["scheduled", "closed", "cancelled"])
def test_checkin_requires_active_session(api, ready, status):
    with api.database() as database:
        database.get(Session, ready["id"]).status = status
        database.commit()
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 400


@pytest.mark.parametrize("when", ["before", "after"])
def test_checkin_window_enforced(api, ready, when):
    with api.database() as database:
        row = database.get(Session, ready["id"])
        if when == "before":
            row.checkin_opens_at = utc_now() + timedelta(minutes=1)
        else:
            row.checkin_closes_at = utc_now() - timedelta(minutes=1)
        database.commit()
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 400
    with api.database() as database:
        assert database.scalar(select(func.count(Checkin.id))) == 0
        assert database.scalar(select(AuditLog).where(AuditLog.action == "checkin_rejected")).success is False


@pytest.mark.parametrize("consent", ["camera_consent", "geolocation_consent"])
def test_checkin_requires_consent(api, ready, consent):
    with api.database() as database:
        setattr(database.get(User, api.users["student"].id), consent, False)
        database.commit()
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 403


def test_camera_consent_not_required_for_gps_only_session(api, ready):
    with api.database() as database:
        row = database.get(Session, ready["id"])
        row.require_liveness_check = row.require_face_match = False
        database.get(User, api.users["student"].id).camera_consent = False
        database.commit()
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201


@pytest.mark.parametrize("kind", ["enrollment", "course"])
def test_inactive_enrollment_or_course_cannot_check_in(api, ready, course, enrollment, kind):
    with api.database() as database:
        row = database.get(Enrollment, enrollment["id"]) if kind == "enrollment" else database.get(Course, course["id"])
        row.is_active = False
        database.commit()
    expected = 403 if kind == "enrollment" else 400
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == expected


@pytest.mark.parametrize("changes", [{"latitude": 91}, {"longitude": -181}, {"location_accuracy_meters": -1}])
def test_checkin_coordinate_validation(api, ready, changes):
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready, **changes)).status_code == 422


@pytest.mark.parametrize("multiple,status", [(1, "approved"), (0.999, "flagged"), (0.5, "flagged"), (0.499, "rejected")])
def test_exact_geofence_boundaries(api, ready, multiple, status):
    distance = haversine_distance(1.3483, 103.6831, 1.3493, 103.6831)
    with api.database() as database:
        database.get(Session, ready["id"]).geofence_radius_meters = distance * multiple
        database.commit()
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, latitude=1.3493))
    assert response.status_code == 201
    assert response.json()["status"] == status


def test_full_flow_closes_session_and_preserves_attendance(api, ready, enrollment):
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201
    path = f"/sessions/{ready['id']}"
    response = api.request("PATCH", path, json={"status": "closed"})
    assert response.status_code == 200
    assert response.json()["checked_in_count"] == 1
    assert response.json()["total_enrolled"] == 1
    assert api.request("GET", "/sessions/active", None).json() == []
    assert api.request("DELETE", path).status_code == 400
    assert api.request("DELETE", f"/enrollments/{enrollment['id']}").status_code == 204
    with api.database() as database:
        assert database.scalar(select(func.count(Checkin.id))) == 1


@pytest.mark.parametrize("kind", ["enrollment", "checkin"])
def test_database_uniqueness_prevents_duplicate_records(api, ready, enrollment, kind):
    from sqlalchemy.exc import IntegrityError
    if kind == "checkin":
        assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201
    with api.database() as database:
        if kind == "enrollment":
            duplicate = Enrollment(student_id=api.users["student"].id, course_id=enrollment["course_id"])
        else:
            duplicate = Checkin(session_id=ready["id"], student_id=api.users["student"].id,
                                latitude=1.3483, longitude=103.6831, location_accuracy_meters=10,
                                distance_from_venue_meters=0, status="approved", risk_score=0)
        database.add(duplicate)
        with pytest.raises(IntegrityError):
            database.commit()
        database.rollback()


@pytest.mark.parametrize("boundary", ["checkin_opens_at", "checkin_closes_at"])
def test_checkin_window_includes_exact_boundaries(api, ready, boundary, monkeypatch):
    from app.routers import checkins
    with api.database() as database:
        now = as_utc(getattr(database.get(Session, ready["id"]), boundary))
    monkeypatch.setattr(checkins, "utc_now", lambda: now)
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201


@pytest.fixture
def login_user(api, monkeypatch):
    from app.routers import auth
    from app.security import hash_password
    monkeypatch.setattr(auth, "enforce_login_limit", lambda _: None)
    password = "valid-password-123"
    password_hash = hash_password(password)
    with api.database() as database:
        for role in ("student", "other_student"):
            database.get(User, api.users[role].id).hashed_password = password_hash
        database.commit()
    return {"email": api.users["student"].email, "password": password}


def test_tenth_failure_blocks_account_across_ips_and_correct_password(api, login_user):
    wrong = {**login_user, "password": "wrong-password"}
    for attempt in range(1, 11):
        response = api.request("POST", "/auth/login", None, json=wrong,
                               headers={"X-Forwarded-For": f"10.0.0.{attempt}"})
        assert response.status_code == (429 if attempt == 10 else 401)
    assert api.request("POST", "/auth/login", None, json=login_user).status_code == 429
    assert api.request("POST", "/auth/login", None, json={**login_user, "email": login_user["email"].upper()}).status_code == 429
    with api.database() as database:
        user = database.get(User, api.users["student"].id)
        assert user.failed_login_attempts == 10
        assert user.is_active is True  # Login blocking is separate from account deactivation.


def test_success_resets_failures_and_other_accounts_are_not_blocked(api, login_user):
    wrong = {**login_user, "password": "wrong-password"}
    for _ in range(9):
        assert api.request("POST", "/auth/login", None, json=wrong).status_code == 401
    assert api.request("POST", "/auth/login", None, json=login_user).status_code == 200
    with api.database() as database:
        assert database.get(User, api.users["student"].id).failed_login_attempts == 0
    for _ in range(9):
        assert api.request("POST", "/auth/login", None, json=wrong).status_code == 401
    assert api.request("POST", "/auth/login", None, json=wrong).status_code == 429
    other = {**login_user, "email": api.users["other_student"].email}
    assert api.request("POST", "/auth/login", None, json=other).status_code == 200


def test_admin_activation_unblocks_login(api, login_user):
    with api.database() as database:
        database.get(User, api.users["student"].id).failed_login_attempts = 10
        database.commit()
    path = f"/admin/users/{api.users['student'].id}/activate"
    assert api.request("PATCH", path, "instructor").status_code == 403
    assert api.request("POST", "/auth/login", None, json=login_user).status_code == 429
    assert api.request("PATCH", path, "admin").status_code == 200
    assert api.request("POST", "/auth/login", None, json=login_user).status_code == 200


@pytest.mark.parametrize("coordinates", [(40.7128, -74.0060), (1.46, 103.75)])
def test_foreign_gps_rejected_even_for_matching_venue_and_local_ip(api, ready, coordinates):
    latitude, longitude = coordinates
    with api.database() as database:
        row = database.get(Session, ready["id"])
        row.venue_latitude, row.venue_longitude = coordinates
        database.commit()
    response = api.request("POST", "/checkins/", "student",
                           json=checkin_payload(ready, latitude=latitude, longitude=longitude))
    assert response.status_code == 403
    with api.database() as database:
        assert database.scalar(select(func.count(Checkin.id))) == 0


@pytest.mark.parametrize("forwarded,country,expected", [
    ("8.8.8.8, 10.0.0.1", "US", 403),
    ("8.8.8.8, 10.0.0.1", "SG", 201),
    ("192.168.1.2, 8.8.8.8", None, 201),
    ("::1", None, 201),
    ("not-an-ip", None, 403),
])
def test_checkin_uses_first_forwarded_ip(api, ready, monkeypatch, forwarded, country, expected):
    from types import SimpleNamespace
    from app.utils import geolocation
    def cached_country(key):
        assert country is not None, "local/invalid addresses must not trigger a lookup"
        assert key == "geo:country:8.8.8.8"
        return country
    monkeypatch.setattr(geolocation, "get_redis_client", lambda: SimpleNamespace(get=cached_country))
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready),
                           headers={"X-Forwarded-For": forwarded})
    assert response.status_code == expected


def test_lookup_failure_does_not_create_an_approved_checkin(api, ready, monkeypatch):
    from app.routers import checkins
    from fastapi import HTTPException
    def unavailable(_):
        raise HTTPException(status_code=503, detail="IP country lookup unavailable")
    monkeypatch.setattr(checkins, "ip_is_in_singapore", unavailable)
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert response.status_code == 503
    with api.database() as database:
        assert database.scalar(select(func.count(Checkin.id))) == 0


def test_course_without_instructor_supports_enrollment_and_multiple_session_owners(api):
    response = api.request("POST", "/courses/", "admin", json={
        "code": "UNASSIGNED", "name": "Shared course", "semester": "AY2026-27 Sem 1",
        "venue_latitude": 1.3483, "venue_longitude": 103.6831,
    })
    assert response.status_code == 201, response.text
    course = response.json()
    assert course["instructor_id"] is None
    assert course["instructor_name"] is None
    enrollment = api.request("POST", "/enrollments/", "admin", json={
        "course_id": course["id"], "student_id": api.users["student"].id})
    assert enrollment.status_code == 201
    mine = api.request("GET", "/enrollments/my-enrollments", "student").json()
    assert mine[0]["course_code"] == "UNASSIGNED"
    assert "instructor_name" not in mine[0]
    roster_path = f"/enrollments/course/{course['id']}"
    assert api.request("GET", roster_path, "instructor").status_code == 403
    sessions = {}
    for role in ("instructor", "other_instructor"):
        response = api.request("POST", "/sessions/", role, json=session_payload(course))
        assert response.status_code == 201, response.text
        sessions[role] = response.json()
        assert sessions[role]["instructor_id"] == api.users[role].id
        assert api.request("GET", roster_path, role).status_code == 200
    for role in sessions:
        mine = api.request("GET", "/sessions/my-sessions", role).json()
        assert [row["id"] for row in mine] == [sessions[role]["id"]]
        listed = api.request("GET", "/sessions/", role).json()
        assert listed["total"] == 1
    assert api.request("PATCH", f"/sessions/{sessions['instructor']['id']}", "other_instructor",
                       json={"status": "active"}).status_code == 403
    assert api.request("DELETE", f"/enrollments/{enrollment.json()['id']}", "instructor").status_code == 204


def test_admin_can_clear_optional_course_assignment(api, course):
    response = api.request("PUT", f"/courses/{course['id']}", "admin", json={"instructor_id": None})
    assert response.status_code == 200
    assert response.json()["instructor_id"] is None
    assert api.request("POST", "/sessions/", "other_instructor", json=session_payload(course)).status_code == 201
