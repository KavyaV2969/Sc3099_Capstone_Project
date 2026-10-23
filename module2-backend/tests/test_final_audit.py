"""Regressions for the final audit: spec audit actions, logout, numeric statistics,
soft-deleted enrollments, error codes and stored risk signals."""
import pytest
from sqlalchemy import select

from app.models import AuditLog, Enrollment, RiskSignal
from app.schemas import UserRole
from app.security import create_access_token, create_refresh_token
from test_week3 import api, course, session, enrollment, ready, checkin_payload, session_payload


def test_admin_setup_routes_log_spec_action_names(api, course):
    student = api.users["other_student"].id
    assert api.request("POST", "/admin/enrollments/", "admin",
                       json={"student_id": student, "course_id": course["id"]}).status_code == 201
    created = api.request("POST", "/sessions/", json=session_payload(course)).json()
    assert api.request("PATCH", f"/admin/sessions/{created['id']}/status", "admin",
                       json={"status": "active"}).status_code == 200
    with api.database() as db:
        actions = set(db.scalars(select(AuditLog.action)))
    assert {"enrollment_added", "session_updated"} <= actions
    assert not {"student_enrolled", "session_status_updated"} & actions


def test_logout_revokes_presented_tokens_and_is_audited(api):
    user = api.users["student"]
    access = create_access_token(user.id, user.email, UserRole.STUDENT)
    refresh = create_refresh_token(user.id, user.email, UserRole.STUDENT)
    headers = {"Authorization": f"Bearer {access}"}
    assert api.request("GET", "/users/me", None, headers=headers).status_code == 200
    other = api.users["other_student"]
    foreign = create_refresh_token(other.id, other.email, UserRole.STUDENT)
    assert api.request("POST", "/auth/logout", None, headers=headers,
                       json={"refresh_token": foreign}).status_code == 403
    assert api.request("GET", "/users/me", None, headers=headers).status_code == 200  # Nothing revoked.
    result = api.request("POST", "/auth/logout", None, headers=headers, json={"refresh_token": refresh})
    assert result.status_code == 200
    assert api.request("GET", "/users/me", None, headers=headers).status_code == 401
    assert api.request("POST", "/auth/refresh", None, json={"refresh_token": refresh}).status_code == 401
    assert api.request("POST", "/auth/logout", None).status_code == 401
    with api.database() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == "logout"))
        assert event.user_id == user.id and event.details["refresh_token_revoked"] is True


def test_statistics_are_numeric_before_activation(api, course, enrollment):
    scheduled = api.request("POST", "/sessions/", json=session_payload(course)).json()
    stats = api.request("GET", f"/stats/sessions/{scheduled['id']}").json()
    assert stats["total_enrolled"] == 1 and stats["attendance_rate"] == 0
    assert stats["coverage"]["denominator_source"] == "current_enrollment"
    report = api.request("GET", f"/stats/courses/{course['id']}").json()
    assert isinstance(report["overall_attendance_rate"], float)
    student = api.request("GET", f"/stats/students/{api.users['student'].id}").json()
    assert isinstance(student["attendance_rate"], float)


def test_enrollment_removal_is_an_idempotent_soft_delete(api, course, enrollment):
    path = f"/enrollments/{enrollment['id']}"
    assert api.request("DELETE", path).status_code == 204
    assert api.request("DELETE", path).status_code == 204
    with api.database() as db:
        row = db.get(Enrollment, enrollment["id"])
        assert row.is_active is False and row.dropped_at is not None
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "enrollment_removed")) is not None
    roster = api.request("GET", f"/enrollments/course/{course['id']}?is_active=false").json()
    assert [s["student_id"] for s in roster["students"]] == [api.users["student"].id]
    again = api.request("POST", "/enrollments/", json={"course_id": course["id"], "student_id": api.users["student"].id})
    assert again.status_code == 201
    with api.database() as db:
        row = db.get(Enrollment, enrollment["id"])
        assert row.is_active is True and row.dropped_at is None


def test_errors_carry_detail_and_code(api):
    unauthorized = api.request("GET", "/users/me", None)
    assert unauthorized.json() == {"detail": "authentication required", "code": "UNAUTHORIZED"}
    invalid = api.request("POST", "/auth/register", None, json={"email": "bad", "password": "x", "full_name": "X"})
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_ERROR"
    assert isinstance(invalid.json()["detail"], list)


def test_each_risk_factor_is_stored_as_a_risk_signal(api, ready):
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, latitude=1.34965))
    factors = result.json()["risk_factors"]
    assert {"device_unknown", "geo_out_of_bounds"} <= {f["type"] for f in factors}
    with api.database() as db:
        rows = list(db.scalars(select(RiskSignal).where(RiskSignal.checkin_id == result.json()["id"])))
    assert sorted(r.signal_type for r in rows) == sorted(f["type"] for f in factors)
    assert all(r.severity in {"low", "medium", "high", "critical"} for r in rows)
    assert sum(r.weight for r in rows) == pytest.approx(result.json()["risk_score"])
