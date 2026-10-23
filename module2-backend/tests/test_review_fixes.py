"""Regressions for the second review: skipped liveness, bulk-account locking cost,
the overview at scale, retention churn and literal user search."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from app.models import Checkin, Course, Session as AttendanceSession, User, utc_now
from app.risk import assess_risk
from app.security import UNUSABLE_PASSWORD, verify_password
from app.services.reporting import attendance, business_day, current_rosters, load_report, rate
from test_week3 import api, course, session, enrollment, ready, checkin_payload


def _risk(**changes):
    values = dict(distance=20, radius=100, location_accuracy=10, require_liveness=False, require_face=False,
                  liveness_score=None, liveness_passed=None, face_score=None, face_passed=None,
                  known_device=True, trusted_device=False, local_network=True, threshold=.5)
    return assess_risk(**{**values, **changes})


def test_skipping_required_liveness_is_never_auto_approved():
    skipped = _risk(liveness_requested=True)
    assert skipped.score < .5 and skipped.status == "flagged"
    assert "liveness_missing" in {f["type"] for f in skipped.factors}
    passed = _risk(liveness_requested=True, require_liveness=True, liveness_score=.9, liveness_passed=True)
    assert passed.status == "approved"
    assert _risk(liveness_requested=False).status == "approved"  # Not requested: unaffected.


def test_skipped_liveness_check_in_is_flagged_through_the_api(api, ready):
    with api.database() as db:
        db.get(AttendanceSession, ready["id"]).require_liveness_check = True
        db.commit()
    api.request("POST", "/devices/register", "student", json={"device_fingerprint": "test-device"})
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    assert result.status_code == 201 and result.json()["status"] == "flagged"
    assert result.json()["liveness_passed"] is None


def test_unusable_password_marker_never_verifies():
    assert verify_password("", UNUSABLE_PASSWORD) is False
    assert verify_password("!", UNUSABLE_PASSWORD) is False


def test_bulk_created_accounts_store_no_password_hash_and_cannot_log_in(api, course):
    email = f"new_{uuid4().hex[:6]}@example.com"
    result = api.request("POST", "/enrollments/bulk", "admin",
                         json={"course_id": course["id"], "student_emails": [email], "create_accounts": True})
    assert result.status_code == 200 and result.json()["created"] == 1
    with api.database() as db:
        assert db.scalar(select(User.hashed_password).where(User.email == email)) == UNUSABLE_PASSWORD
    login = api.request("POST", "/auth/login", None, json={"email": email, "password": "anything123"})
    assert login.status_code in (401, 403)


def test_user_search_treats_wildcards_literally(api):
    with api.database() as db:
        db.add_all([User(email=f"x{n}@example.com", full_name=name, hashed_password=UNUSABLE_PASSWORD)
                    for n, name in enumerate(["a_b student", "axb student", "100% present"])])
        db.commit()
    names = lambda term: {u["full_name"] for u in api.request("GET", f"/users/?search={term}", "admin").json()["items"]}
    assert names("a_b") == {"a_b student"}
    assert names("100%25") == {"100% present"}


def _reference_overview(database, course_ids, days=7):
    """The previous row-loading overview, kept as an oracle for the SQL version."""
    sessions, checkins, _ = load_report(database, course_ids)
    grouped = {s.id: [] for s in sessions}
    for c in checkins:
        grouped[c.session_id].append(c)
    fallback = current_rosters(database, {s.course_id for s in sessions})
    summaries = {s.id: attendance(s, grouped[s.id], fallback=fallback.get(s.course_id)) for s in sessions}
    today = business_day(utc_now())
    daily = {}
    for s in sessions:
        day = business_day(s.scheduled_start)
        if day < today - timedelta(days=min(days, 30) - 1):
            continue
        item = daily.setdefault(day, {"count": 0, "approved": 0, "slots": 0})
        item["count"] += len(grouped[s.id])
        item["approved"] += summaries[s.id]["approved_attendance"]
        item["slots"] += summaries[s.id]["total_enrolled"]
    days_of = {s.id: business_day(s.scheduled_start) for s in sessions}
    total = len(checkins)
    return {
        "total_sessions": len(sessions), "active_sessions": sum(s.status == "active" for s in sessions),
        "total_checkins_today": sum(days_of[c.session_id] == today for c in checkins),
        "total_checkins_week": sum(days_of[c.session_id] >= today - timedelta(days=6) for c in checkins),
        "average_attendance_rate": rate(sum(v["approved_attendance"] for v in summaries.values()),
                                        sum(v["total_enrolled"] for v in summaries.values())),
        "flagged_pending_review": sum(c.status in {"flagged", "appealed"} for c in checkins),
        "approval_rate": rate(sum(c.status == "approved" for c in checkins), total),
        "average_risk_score": round(sum(c.risk_score for c in checkins) / total, 4) if total else 0,
        "high_risk_checkins_today": sum(days_of[c.session_id] == today and c.risk_score >= .5 for c in checkins),
        "trends": {"checkins_by_day": [{"date": str(d), "count": v["count"]} for d, v in sorted(daily.items())],
                   "attendance_rate_by_day": [{"date": str(d), "rate": rate(v["approved"], v["slots"])}
                                              for d, v in sorted(daily.items())]},
    }


def _seed_students(db, count):
    ids = [str(uuid4()) for _ in range(count)]
    db.execute(insert(User), [{"id": i, "email": f"{i}@example.com", "full_name": "S", "role": "student",
                               "hashed_password": UNUSABLE_PASSWORD} for i in ids])
    return ids


def _seed_session(db, course_id, instructor_id, days_ago, *, roster=None, status="closed"):
    start = utc_now() - timedelta(days=days_ago)
    row = AttendanceSession(course_id=course_id, instructor_id=instructor_id, name=f"Day -{days_ago}",
        scheduled_start=start, scheduled_end=start + timedelta(hours=1),
        checkin_opens_at=start - timedelta(minutes=15), checkin_closes_at=start + timedelta(minutes=30),
        venue_latitude=1.3483, venue_longitude=103.6831, geofence_radius_meters=100,
        risk_threshold=.5, status=status, attendance_roster=roster)
    db.add(row); db.flush()
    return row.id


def test_sql_overview_matches_the_previous_row_loading_overview(api, course, enrollment):
    statuses = ["approved", "flagged", "rejected", "appealed", "approved", "pending"]
    with api.database() as db:
        students = _seed_students(db, 6)
        instructor = api.users["instructor"].id
        sessions = [
            _seed_session(db, course["id"], instructor, 0, roster=students[:4], status="active"),
            _seed_session(db, course["id"], instructor, 2, roster=students),
            _seed_session(db, course["id"], instructor, 10, roster=None),  # Falls back to enrollment.
            _seed_session(db, course["id"], instructor, 40, roster=students),  # Outside retention window.
        ]
        rows = []
        for s_index, session_id in enumerate(sessions):
            for n, student in enumerate(students):
                expired = s_index == 1 and n == 0
                rows.append({"id": str(uuid4()), "session_id": session_id, "student_id": student,
                    "status": statuses[(n + s_index) % len(statuses)], "risk_score": round(.1 + .13 * n, 2),
                    "latitude": 1.3483, "longitude": 103.6831, "distance_from_venue_meters": 0,
                    "checked_in_at": utc_now(), "scheduled_deletion_at":
                        utc_now() + (timedelta(days=-1) if expired else timedelta(days=30))})
        db.execute(insert(Checkin), rows)
        db.commit()
        expected = _reference_overview(db, [course["id"]])
    actual = api.request("GET", "/stats/overview").json()
    assert expected["total_checkins_today"] > 0 and expected["flagged_pending_review"] > 0
    for field, value in expected.items():
        if field == "average_risk_score":
            assert actual[field] == pytest.approx(value, abs=1e-4)
        else:
            assert actual[field] == value, field


def test_overview_has_no_ten_thousand_check_in_ceiling(api, course):
    with api.database() as db:
        students = _seed_students(db, 101)
        instructor = api.users["instructor"].id
        session_ids = [_seed_session(db, course["id"], instructor, day % 25, roster=students) for day in range(100)]
        db.execute(insert(Checkin), [{"id": str(uuid4()), "session_id": s, "student_id": st, "status": "approved",
            "risk_score": .1, "latitude": 1.3483, "longitude": 103.6831, "distance_from_venue_meters": 0,
            "checked_in_at": utc_now(), "scheduled_deletion_at": utc_now() + timedelta(days=30)}
            for s in session_ids for st in students])
        db.commit()
    result = api.request("GET", "/stats/overview")
    assert result.status_code == 200, result.text
    assert result.json()["total_sessions"] == 100 and result.json()["approval_rate"] == 1
    assert result.json()["average_attendance_rate"] == 1


def test_retention_skips_old_sessions_already_cleared(api, course):
    from sqlalchemy import event
    from app.services.retention import cleanup_expired_records
    with api.database() as db:
        _seed_session(db, course["id"], api.users["instructor"].id, 70, roster=["x"])
        db.commit()
    with api.database() as db:
        cleanup_expired_records(db)
    updates = []
    engine = api.database.kw["bind"]
    listener = lambda conn, cursor, statement, params, context, many: updates.append(
        context.rowcount if statement.startswith("UPDATE sessions") else None)
    event.listen(engine, "after_cursor_execute", listener)
    try:
        with api.database() as db:
            cleanup_expired_records(db)
    finally:
        event.remove(engine, "after_cursor_execute", listener)
    assert [n for n in updates if n is not None] == [0]  # Nothing rewritten on the second run.
    with api.database() as db:
        assert db.scalar(select(AttendanceSession.attendance_roster).where(
            AttendanceSession.name == "Day -70")) is None
