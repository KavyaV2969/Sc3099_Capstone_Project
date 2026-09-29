"""Regression cases for the backend audit; isolated API data, real JWTs."""
from unittest.mock import MagicMock
from datetime import timedelta
from urllib.parse import urlparse, parse_qs
import base64
import asyncio
import gzip
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils, rsa, padding
from key_fixtures import PRIVATE_KEY, PUBLIC_KEY

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Checkin, Course, Device, Enrollment, Session as AttendanceSession, User, utc_now
from app.routers import auth
from app.schemas import UserRegister
from app.services.enrollments import create_enrollment
from test_week3 import api, course, session, enrollment, ready, checkin_payload, session_payload


@pytest.mark.parametrize("agent,expected", [("Browser Monitor", .2), ("Tor Browser", .32), ("VPN Client", .32)])
def test_network_hint_uses_words_and_preserves_private_ip(api, ready, agent, expected):
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready), headers={"User-Agent":agent})
    assert result.status_code == 201 and result.json()["risk_score"] == expected


@pytest.mark.parametrize("displacement,elapsed,accuracy,flagged", [(.005,1,10,False),(.02,5,10,True),
    (.02,60,10,False),(.02,-1,10,True),(.02,5,2000,False)])
def test_impossible_travel_boundaries_flag_without_rejection(api, ready, displacement, elapsed, accuracy, flagged):
    first = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert first.status_code == 201
    with api.database() as db:
        previous = db.get(Checkin, first.json()["id"])
        previous.latitude -= displacement
        previous.checked_in_at = utc_now() - timedelta(seconds=elapsed)
        previous.location_accuracy_meters = accuracy
        db.commit()
    next_session = api.request("POST", "/sessions/", json=session_payload({"id":ready["course_id"]})).json()
    assert api.request("PATCH", f"/sessions/{next_session['id']}", json={"status":"active"}).status_code == 200
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(next_session))
    assert result.status_code == 201, result.text
    assert (result.json()["status"] == "flagged") is flagged
    assert result.json()["status"] != "rejected"


def test_legacy_unknown_roster_is_not_reconstructed_after_admin_reset(api, ready):
    with api.database() as db:
        db.get(AttendanceSession, ready["id"]).attendance_roster = None
        db.commit()
    api.request("PATCH", f"/admin/sessions/{ready['id']}/status", "admin", json={"status":"scheduled"})
    api.request("PATCH", f"/sessions/{ready['id']}", json={"status":"active"})
    assert api.request("GET", f"/stats/sessions/{ready['id']}").json()["attendance_rate"] is None


def test_singapore_reporting_midnight():
    from datetime import datetime, timezone
    from app.services.reporting import business_day
    assert str(business_day(datetime(2026,9,28,16,0,tzinfo=timezone.utc))) == "2026-09-29"
    assert str(business_day(datetime(2026,9,28,15,59,tzinfo=timezone.utc))) == "2026-09-28"


def test_ta_removal_immediately_revokes_course_access(api, ready):
    from app.models import CourseTA
    with api.database() as db:
        db.add(CourseTA(course_id=ready["course_id"],ta_id=api.users["ta"].id)); db.commit()
    path = f"/stats/sessions/{ready['id']}"
    assert api.request("GET",path,"ta").status_code == 200
    with api.database() as db:
        db.delete(db.get(CourseTA,(ready["course_id"],api.users["ta"].id))); db.commit()
    assert api.request("GET",path,"ta").status_code == 403
    assert api.request("GET",path,"admin").status_code == 200


def test_shared_course_review_access_does_not_allow_other_session_mutation(api, ready):
    with api.database() as db:
        db.get(Course,ready["course_id"]).instructor_id=None; db.commit()
    other = api.request("POST","/sessions/","other_instructor",json=session_payload({"id":ready["course_id"]})).json()
    assert api.request("GET",f"/stats/sessions/{other['id']}").status_code == 200
    assert api.request("PATCH",f"/sessions/{other['id']}",json={"status":"active"}).status_code == 403


@pytest.mark.parametrize("dependency",["biometric","ip"])
def test_slow_dependencies_do_not_block_unrelated_requests(api, ready, monkeypatch, dependency):
    from threading import Event
    from app.main import app
    from app.routers import checkins
    from app.face_service import LivenessResult
    from app.security import create_access_token
    from app.schemas import UserRole
    entered,release=Event(),Event()
    if dependency=="ip":
        def slow_ip(_):
            entered.set(); assert release.wait(timeout=3); return True
        monkeypatch.setattr(checkins,"ip_is_in_singapore",slow_ip)
    else:
        with api.database() as db:
            db.get(AttendanceSession,ready["id"]).require_liveness_check=True; db.commit()
        async def slow_live(_):
            entered.set()
            while not release.is_set(): await asyncio.sleep(.01)
            return LivenessResult(liveness_passed=True,liveness_score=.9,liveness_threshold=.6)
        monkeypatch.setattr(checkins,"check_liveness",slow_live)
    actor=api.users["student"]
    headers={"Authorization":"Bearer "+create_access_token(actor.id,actor.email,UserRole.STUDENT),"X-Forwarded-For":"127.0.0.1"}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://backend",headers=headers) as client:
            body=checkin_payload(ready)
            if dependency=="biometric": body["liveness_challenge_response"]="private-image"
            pending=asyncio.create_task(client.post("/api/v1/checkins/",json=body))
            try:
                assert await asyncio.to_thread(entered.wait,2)
                result=await asyncio.wait_for(client.get("/api/v1/users/me"),timeout=1)
                assert result.status_code==200
            finally: release.set()
            assert (await pending).status_code==201
    asyncio.run(exercise())


@pytest.mark.parametrize("database_outage", [False,True])
def test_unexpected_errors_are_sanitized_in_response_and_logs(api, monkeypatch, caplog, database_outage):
    from app.dependencies import get_current_user
    from app.main import app
    def fail():
        if database_outage:
            from sqlalchemy.exc import OperationalError
            raise OperationalError("SQL",{},RuntimeError("private-password"))
        raise RuntimeError("SQL private-password bearer-secret image-payload")
    app.dependency_overrides[get_current_user] = fail
    try:
        result = api.request("GET", "/users/me", "student")
        assert result.status_code == (503 if database_outage else 500)
        assert result.json() == {"detail":"Database unavailable" if database_outage else "Internal server error"}
        assert "private-password" not in caplog.text and "image-payload" not in caplog.text
        assert result.headers["x-request-id"]
    finally:
        app.dependency_overrides.pop(get_current_user)


def test_registration_flush_conflict_is_controlled(api, monkeypatch):
    database = MagicMock()
    database.scalar.return_value = None
    database.flush.side_effect = IntegrityError("insert", {}, Exception("private SQL"))
    monkeypatch.setattr(auth, "enforce_registration_limit", lambda _: None)
    with pytest.raises(HTTPException) as result:
        auth.register(UserRegister(email="conflict@example.com", full_name="Conflict",
                                   password="securepass123", role="student"), None, database)
    assert result.value.status_code == 400
    assert "private SQL" not in str(result.value.detail)
    database.rollback.assert_called_once()


def test_shared_enrollment_flush_conflict_is_controlled():
    database = MagicMock()
    database.scalar.side_effect = [User(role="student", is_active=True), Course(is_active=True), None]
    database.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    with pytest.raises(HTTPException) as result:
        create_enrollment(database, student_id="student", course_id="course")
    assert result.value.status_code == 400


def test_rate_blocked_checkin_attempt_still_audits_minimized_location(api, ready, monkeypatch):
    from app.routers import checkins
    def limited(_):
        raise HTTPException(status_code=429,detail="rate limit exceeded",headers={"Retry-After":"55"})
    monkeypatch.setattr(checkins,"enforce_checkin_limit",limited)
    result=api.request("POST","/checkins/","student",json=checkin_payload(ready,latitude=1.3483000123))
    assert result.status_code==429 and result.headers["retry-after"]=="55"
    with api.database() as db:
        event=db.scalar(select(AuditLog).where(AuditLog.action=="checkin_attempted"))
        assert event.details["location"]["latitude"]==1.3483
        assert db.scalar(select(Checkin.id)) is None


def test_used_session_cannot_be_deleted_after_admin_reset(api, ready):
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert response.status_code == 201, response.text
    assert api.request("PATCH", f"/admin/sessions/{ready['id']}/status", "admin",
                       json={"status": "scheduled"}).status_code == 200
    response = api.request("DELETE", f"/sessions/{ready['id']}")
    assert response.status_code == 400
    with api.database() as database:
        assert database.scalar(select(Checkin.id)) is not None


def test_session_teacher_can_read_student_but_only_taught_courses(api, session, enrollment):
    with api.database() as db:
        db.get(Course, session["course_id"]).instructor_id = None
        other = Course(code="OTHER", name="Other", semester="AY26", instructor_id=api.users["other_instructor"].id)
        db.add(other)
        db.flush()
        db.add(Enrollment(course_id=other.id, student_id=api.users["student"].id))
        db.commit()
    sid = api.users["student"].id
    assert api.request("GET", f"/users/{sid}").status_code == 200
    report = api.request("GET", f"/stats/students/{sid}")
    assert report.status_code == 200, report.text
    assert [item["course_code"] for item in report.json()["courses"]] == ["SC3099"]
    assert api.request("GET", f"/users/{sid}", "other_student").status_code == 403
    assert len(api.request("GET", f"/stats/students/{sid}", "admin").json()["courses"]) == 2


def test_bulk_activation_is_single_use_and_not_a_default_password(api, course):
    response = api.request("POST", "/enrollments/bulk", json={"course_id": course["id"],
        "student_emails": ["new@example.com", "new@example.com"], "create_accounts": True})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["created"] == 1
    assert response.json()["already_enrolled"] == 1
    token = parse_qs(urlparse(response.json()["details"][0]["activation_url"]).query)["token"][0]
    with api.database() as db:
        user = db.scalar(select(User).where(User.email == "new@example.com"))
        assert not user.is_active and user.activation_token_hash != token
    activation = {"token": token, "password": "securepass123", "full_name": "New Student"}
    assert api.request("POST", "/auth/activate", None, json=activation).status_code == 200
    assert api.request("POST", "/auth/activate", None, json=activation).status_code == 400
    assert api.request("POST", "/auth/login", None,
                       json={"email": "new@example.com", "password": "securepass123"}).status_code == 200


def test_bulk_unknown_duplicates_and_inactive_course(api, course):
    body = {"course_id": course["id"], "student_emails": ["missing@example.com"] * 2}
    result = api.request("POST", "/enrollments/bulk", json=body)
    assert result.json()["not_found"] == 2
    assert result.json()["already_enrolled"] == 0
    api.request("DELETE", f"/courses/{course['id']}", "admin")
    assert api.request("POST", "/enrollments/bulk", json=body).status_code == 400
    assert api.request("POST", "/admin/enrollments/", "admin", json={
        "course_id": course["id"], "student_id": api.users["student"].id}).status_code == 400


def test_expired_activation_does_not_change_account(api, course):
    result = api.request("POST", "/enrollments/bulk", json={"course_id": course["id"],
        "student_emails": ["expired@example.com"], "create_accounts": True})
    token = parse_qs(urlparse(result.json()["details"][0]["activation_url"]).query)["token"][0]
    with api.database() as db:
        db.scalar(select(User).where(User.email == "expired@example.com")).activation_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert api.request("POST", "/auth/activate", None,
                       json={"token": token, "password": "securepass123"}).status_code == 400


def register_device(api, key=PUBLIC_KEY):
    result = api.request("POST", "/devices/register", "student", json={
        "device_fingerprint": "test-device", "device_name": "Phone", "platform": "web", "public_key": key})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def signed_payload(api, device_id, ready, key=PRIVATE_KEY):
    payload = checkin_payload(ready)
    issued = api.request("POST", f"/devices/{device_id}/challenge", "student", json=payload)
    assert issued.status_code == 200, issued.text
    challenge = issued.json()
    signature = key.sign(base64.b64decode(challenge["signing_payload"]), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    return {**payload, "device_challenge_id": challenge["challenge_id"],
            "device_signature": base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()}


def test_device_key_trust_and_admin_revocation(api):
    bad = api.request("POST", "/devices/register", "student", json={
        "device_fingerprint": "bad", "device_name": "Phone", "platform": "web", "public_key": "arbitrary"})
    assert bad.status_code == 400
    did = register_device(api)
    assert api.request("PATCH", f"/devices/{did}", "admin", json={"is_trusted": True}).status_code == 200
    replacement = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    assert register_device(api, replacement) == did
    assert not api.request("GET", "/devices/my-devices", "student").json()[0]["is_trusted"]
    assert api.request("PATCH", f"/devices/{did}", "admin", json={"is_active": False}).status_code == 200
    assert api.request("PATCH", f"/devices/{did}", "student", json={"is_active": True}).status_code == 403
    assert api.request("POST", "/devices/register", "student", json={
        "device_fingerprint": "test-device", "device_name": "Phone", "platform": "web", "public_key": PUBLIC_KEY}).status_code == 403


@pytest.mark.parametrize("trusted,expected", [(True, 0), (False, .1)])
def test_valid_device_proof_earns_trust_and_is_consumed(api, ready, trusted, expected):
    did = register_device(api)
    if trusted:
        api.request("PATCH", f"/devices/{did}", "admin", json={"is_trusted": True})
    payload = signed_payload(api, did, ready)
    result = api.request("POST", "/checkins/", "student", json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["risk_score"] == expected
    from app.rate_limit import get_redis_client
    assert get_redis_client().get("device-proof:" + payload["device_challenge_id"]) is None


def test_unsigned_registered_trusted_device_remains_unknown(api, ready):
    did = register_device(api)
    api.request("PATCH", f"/devices/{did}", "admin", json={"is_trusted": True})
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert result.status_code == 201, result.text
    assert result.json()["risk_score"] == .2


@pytest.mark.parametrize("attack", ["payload", "signature", "expired", "revoked", "key_changed", "foreign", "session"])
def test_invalid_device_proof_creates_no_attendance(api, ready, attack):
    did = register_device(api)
    payload = signed_payload(api, did, ready)
    if attack == "payload":
        payload["location_accuracy_meters"] += 1
    elif attack == "signature":
        payload["device_signature"] = base64.b64encode(b"x" * 64).decode()
    elif attack == "expired":
        from app.rate_limit import get_redis_client
        get_redis_client().delete("device-proof:" + payload["device_challenge_id"])
    elif attack == "key_changed":
        replacement = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        register_device(api, replacement)
    elif attack == "foreign":
        with api.database() as db:
            db.get(Device, did).user_id = api.users["other_student"].id
            db.commit()
    elif attack == "session":
        other = api.request("POST", "/sessions/", json=session_payload({"id":ready["course_id"]})).json()
        api.request("PATCH", f"/sessions/{other['id']}", json={"status":"active"})
        payload["session_id"] = other["id"]
    else:
        api.request("PATCH", f"/devices/{did}", "admin", json={"is_active": False})
    assert api.request("POST", "/checkins/", "student", json=payload).status_code == 403
    with api.database() as db:
        assert db.scalar(select(Checkin.id)) is None


def test_rsa_proof_and_weak_or_unsupported_keys(api, ready):
    from app.services.devices import parse_key
    for key in (rsa.generate_private_key(public_exponent=65537,key_size=1024), ec.generate_private_key(ec.SECP384R1())):
        with pytest.raises(HTTPException):
            parse_key(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    did = register_device(api,key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    payload = checkin_payload(ready)
    challenge = api.request("POST",f"/devices/{did}/challenge","student",json=payload).json()
    assert challenge["algorithm"] == "RSASSA-PKCS1-v1_5-SHA256"
    signature = key.sign(base64.b64decode(challenge["signing_payload"]),padding.PKCS1v15(),hashes.SHA256())
    result = api.request("POST","/checkins/","student",json={**payload,
        "device_challenge_id":challenge["challenge_id"],"device_signature":base64.b64encode(signature).decode()})
    assert result.status_code == 201 and result.json()["risk_score"] == .1


def test_approved_rates_and_roster_survive_withdrawal(api, ready):
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert result.status_code == 201
    added = api.request("POST", "/enrollments/", json={"course_id": ready["course_id"],
        "student_id": api.users["other_student"].id})
    assert added.status_code == 201
    api.request("DELETE", f"/enrollments/{added.json()['id']}")
    stats = api.request("GET", f"/stats/sessions/{ready['id']}").json()
    exported = api.request("GET", f"/export/session/{ready['id']}?format=json").json()
    assert stats["total_enrolled"] == 2 and stats["attendance_rate"] == .5
    assert exported["summary"]["attendance_rate"] == stats["attendance_rate"]
    historical = api.request("GET",f"/stats/students/{api.users['other_student'].id}")
    assert historical.status_code == 200
    assert historical.json()["courses"][0]["total_sessions"] == 1
    assert historical.json()["courses"][0]["attendance_rate"] == 0
    with api.database() as db:
        db.scalar(select(Checkin)).status = "rejected"
        db.commit()
    assert api.request("GET", f"/stats/sessions/{ready['id']}").json()["attendance_rate"] == 0
    assert api.request("GET", f"/export/session/{ready['id']}?format=json").json()["summary"]["attendance_rate"] == 0


@pytest.mark.parametrize("prefix",["\t","\u00a0"])
def test_legacy_roster_is_unavailable_and_csv_formulas_are_neutralized(api, ready, prefix):
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201
    with api.database() as db:
        db.get(AttendanceSession, ready["id"]).attendance_roster = None
        db.get(User, api.users["student"].id).full_name = prefix + "=1+1"
        db.commit()
    stats = api.request("GET", f"/stats/sessions/{ready['id']}").json()
    assert stats["attendance_rate"] is None
    assert not stats["coverage"]["denominator_available"]
    course_export = api.request("GET",f"/export/attendance/{ready['course_id']}?format=json")
    import json
    assert isinstance(course_export.json(), list)
    assert not json.loads(course_export.headers["x-reporting-coverage"])["denominator_available"]
    export = api.request("GET", f"/export/session/{ready['id']}?format=csv")
    import csv, io
    assert list(csv.DictReader(io.StringIO(export.text)))[0]["student_name"] == "'" + prefix + "=1+1"


def test_reports_disclose_retention_and_exclude_cancelled_future_sessions(api, ready):
    from test_week3 import session_payload
    future = api.request("POST", "/sessions/", json={**session_payload({"id": ready["course_id"]}),
        "scheduled_start": (utc_now() + timedelta(days=1)).isoformat(),
        "scheduled_end": (utc_now() + timedelta(days=1, hours=1)).isoformat()})
    assert future.status_code == 201
    api.request("PATCH", f"/admin/sessions/{future.json()['id']}/status", "admin", json={"status": "active"})
    start = (utc_now() - timedelta(days=90)).isoformat()
    stats = api.request("GET", f"/stats/courses/{ready['course_id']}", params={"start_date": start}).json()
    assert stats["total_sessions"] == 1 and stats["coverage"]["limited_by_retention"]
    api.request("PATCH", f"/sessions/{ready['id']}", json={"status": "cancelled"})
    assert api.request("GET", f"/stats/courses/{ready['course_id']}").json()["total_sessions"] == 0


def test_consent_withdrawal_erases_face_and_deletion_is_idempotent(api):
    did = register_device(api)
    with api.database() as db:
        user = db.get(User, api.users["student"].id)
        user.face_enrolled, user.face_embedding_hash = True, "a" * 64
        db.commit()
    assert api.request("PUT", "/users/me", "student", json={"camera_consent": False}).status_code == 200
    with api.database() as db:
        user = db.get(User, api.users["student"].id)
        assert not user.face_enrolled and user.face_embedding_hash is None
    first = api.request("DELETE", "/users/me", "student")
    second = api.request("DELETE", "/users/me", "student")
    assert first.status_code == second.status_code == 200
    assert first.json()["scheduled_deletion_at"] == second.json()["scheduled_deletion_at"]
    assert api.request("GET", "/users/me", "student").status_code == 401
    with api.database() as db:
        assert db.get(Device, did).revoked_at is not None
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "user_deletion_requested")))) == 1
        from app.services.retention import cleanup_expired_records
        result = cleanup_expired_records(db, now=utc_now() + timedelta(days=31))
        assert result["users_anonymised"] == 1
        assert db.get(User, api.users["student"].id).full_name == "Deleted User"
        assert db.get(Device, did) is None


def test_attempt_location_precision_and_manual_outcome_audit(api, ready):
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, latitude=1.3483000123))
    assert result.json()["latitude"] == 1.3483
    with api.database() as db:
        checkin = db.scalar(select(Checkin))
        checkin.status = "flagged"
        cid = checkin.id
        db.commit()
    assert api.request("POST", f"/checkins/{cid}/review", json={"status": "rejected", "review_notes": "Mismatch"}).status_code == 200
    with api.database() as db:
        attempt = db.scalar(select(AuditLog).where(AuditLog.action == "checkin_attempted"))
        assert attempt.details["location"]["latitude"] == 1.3483
        outcome = db.scalar(select(AuditLog).where(AuditLog.action == "checkin_rejected"))
        assert outcome.details["reviewer_id"] == api.users["instructor"].id
        assert outcome.details["reason"] == "Mismatch"


def test_browser_headers_metrics_and_security_denial(api, ready):
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready),
                           headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 201
    exposed = response.headers["access-control-expose-headers"].lower()
    assert all(name in exposed for name in ["retry-after", "content-disposition", "x-request-id"])
    assert len(response.headers["x-request-id"]) == 32
    denial = api.request("GET", "/users/", "student")
    assert denial.status_code == 403
    with api.database() as db:
        violation = db.scalar(select(AuditLog).where(AuditLog.action == "security_violation"))
        assert violation.details["request_id"] == denial.headers["x-request-id"]
        assert violation.details["violation_type"] == "http_403"
    from fastapi.testclient import TestClient
    from app.main import app
    metrics = TestClient(app).get("/metrics")
    assert metrics.status_code == 200
    assert all(name in metrics.text for name in ["http_request_duration_seconds_bucket", "checkin_attempts_total", "checkin_success_total"])
    assert api.users["student"].email not in metrics.text


def test_body_limit_rejects_content_length_and_chunked_uploads():
    from fastapi.testclient import TestClient
    from app.main import app
    response = TestClient(app).post("/api/v1/auth/register", content=b"", headers={"Content-Length": str(17 * 1024 * 1024)})
    assert response.status_code == 413
    async def request():
        async def chunks():
            for _ in range(17):
                yield b"x" * 1024 * 1024
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/auth/register", content=chunks(), headers={"Content-Type": "application/json"})
    assert asyncio.run(request()).status_code == 413


def test_mutation_extras_qr_and_image_size_are_rejected(api, ready):
    for changes in [{"qr_code": "unused-token"}, {"unknown_option": True},
                    {"liveness_challenge_response": "a" * 13_981_020}]:
        result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, **changes))
        assert result.status_code == 422
        assert "unused-token" not in result.text
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, secret_key="test-secret-with-at-least-32-characters", CORS_ORIGINS="*")


@pytest.mark.parametrize("compressed", [False, True])
def test_streamed_upstream_response_is_bounded(monkeypatch, compressed):
    from app import face_service
    original = httpx.AsyncClient
    data = b"x" * 70000
    raw = gzip.compress(data) if compressed else data
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
    def respond(request):
        return httpx.Response(200, stream=Stream(), headers={"Content-Encoding": "gzip"} if compressed else {})
    monkeypatch.setattr(face_service.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(HTTPException) as result:
        asyncio.run(face_service.check_liveness("image"))
    assert result.value.status_code == 503
