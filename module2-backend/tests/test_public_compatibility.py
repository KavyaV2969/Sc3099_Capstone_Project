"""Public consumer compatibility under the user-approved contract reductions."""
from datetime import timedelta

import pytest

from app.models import AuditLog, Checkin, utc_now
from key_fixtures import PUBLIC_KEY
from test_week3 import api, course, session, enrollment, ready, checkin_payload


def test_legacy_course_binding_flag_affirms_but_cannot_disable_signal(api):
    payload = {"code": "PUBLIC", "name": "Public compatibility", "semester": "Sem 1",
               "require_device_binding": True}
    created = api.request("POST", "/courses/", "admin", json=payload)
    assert created.status_code == 201, created.text
    assert "require_device_binding" not in created.json()
    assert api.request("GET", f"/courses/{created.json()['id']}", "student").status_code == 200
    payload.update(code="DISABLED", require_device_binding=False)
    assert api.request("POST", "/courses/", "admin", json=payload).status_code == 422
    assert api.request("GET", "/courses/", None).status_code == 200


def test_device_registration_alias_and_admin_inventory_keep_key_and_role_checks(api):
    payload = {"device_fingerprint": "public-device", "device_name": "Browser",
               "platform": "web", "public_key": PUBLIC_KEY}
    registered = api.request("POST", "/devices/", "student", json=payload)
    assert registered.status_code == 201, registered.text
    result = api.request("GET", "/devices/?limit=1", "admin")
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["id"] == registered.json()["id"]
    assert api.request("GET", "/devices/?offset=1", "admin").json()["items"] == []
    assert api.request("GET", "/devices/", "student").status_code == 403
    assert api.request("GET", "/devices/", "instructor").status_code == 403
    payload.pop("public_key")
    assert api.request("POST", "/devices/", "student", json=payload).status_code == 201


def test_audit_summary_aggregates_window_and_remains_admin_only(api):
    with api.database() as db:
        for age, action in [(1, "login_success"), (1, "login_success"), (2, "login_failed"),
                            (8, "login_failed")]:
            db.add(AuditLog(action=action, timestamp=utc_now()-timedelta(days=age)))
        db.commit()
    result = api.request("GET", "/audit/summary?days=7", "admin")
    assert result.status_code == 200
    assert result.json() == {"period_days": 7, "total_logs": 3,
                             "by_action": {"login_success": 2, "login_failed": 1}}
    assert api.request("GET", "/audit/summary", "instructor").status_code == 403
    assert api.request("GET", "/audit/summary?days=0", "admin").status_code == 422


@pytest.mark.parametrize("status", ["approved", "flagged", "rejected"])
def test_public_analytics_aliases_preserve_instructor_approved_attendance(api, ready, status):
    created = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert created.status_code == 201, created.text
    with api.database() as db:
        db.get(Checkin, created.json()["id"]).status = status
        db.commit()
    overview = api.request("GET", "/stats/overview").json()
    assert overview["total_courses"] == overview["total_students"] == 1
    assert overview["today_checkins"] == overview["total_checkins_today"]
    assert overview["flagged_pending"] == overview["flagged_pending_review"]
    other = api.request("GET", "/stats/overview", "other_instructor").json()
    assert other["total_courses"] == other["total_students"] == other["total_sessions"] == 1
    session_stats = api.request("GET", f"/stats/sessions/{ready['id']}").json()
    assert session_stats["checked_in_count"] == session_stats["checked_in"] == 1
    assert session_stats["approved_count"] == int(status == "approved")
    assert session_stats["flagged_count"] == int(status == "flagged")
    course_stats = api.request("GET", f"/stats/courses/{ready['course_id']}").json()
    assert course_stats["average_attendance_rate"] == course_stats["overall_attendance_rate"] == int(status == "approved")
    assert course_stats["flagged_checkins"] == int(status == "flagged")
    student = api.request("GET", f"/stats/students/{api.users['student'].id}").json()
    assert student["total_enrolled_courses"] == student["total_sessions"] == 1
    assert student["attended_sessions"] == student["attendance_rate"] == int(status == "approved")
    assert student["recent_sessions"] == student["recent_checkins"]
    assert api.request("GET", f"/stats/students/{api.users['student'].id}", "other_instructor").status_code == 200


def test_public_export_aliases_preserve_existing_records_and_roster_summary(api, ready):
    assert api.request("POST", "/checkins/", "student", json=checkin_payload(ready)).status_code == 201
    result = api.request("GET", f"/export/session/{ready['id']}?format=json")
    assert result.status_code == 200
    data = result.json()
    assert data["session_id"] == data["summary"]["session_id"] == ready["id"]
    assert data["records"] == data["checkins"] and len(data["records"]) == 1
    assert data["summary"]["attendance_rate"] == 1
    assert api.request("GET", f"/export/session/{ready['id']}?format=json", "other_instructor").status_code == 200
