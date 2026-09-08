"""Run the Week 3 flow against a live API, PostgreSQL, and Redis.

Creates three test accounts, one course/enrollment, and three closed sessions.
Leaves the records available for inspection; never prints credentials or tokens.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from uuid import uuid4

import httpx


def main() -> None:
    base_url = os.getenv("TEST_BACKEND_URL", "http://localhost:8000")
    run_id = uuid4().hex[:10]
    users, headers = {}, {}
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        def request(method, path, role=None, *, expected=200, **kwargs):
            response = client.request(method, "/api/v1" + path,
                                      headers=headers.get(role, {}), **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status_code}")
            return response.json() if response.content else None

        health = client.get("/health")
        health.raise_for_status()
        assert health.json()["database"] == health.json()["redis"] == "healthy"

        for role in ("admin", "instructor", "student"):
            email = f"week3-{run_id}-{role}@example.com"
            password = secrets.token_urlsafe(24)
            users[role] = request("POST", "/auth/register", expected=201, json={
                "email": email, "password": password,
                "full_name": f"Week 3 smoke {role}", "role": role,
            })
            login = request("POST", "/auth/login", json={"email": email, "password": password})
            headers[role] = {"Authorization": f"Bearer {login['access_token']}"}

        course = request("POST", "/courses/", "admin", expected=201, json={
            "code": f"W3-{run_id}", "name": "Week 3 API smoke test",
            "semester": "AY2026-27 Sem 1", "instructor_id": users["instructor"]["id"],
            "venue_name": "NTU test venue", "venue_latitude": 1.3483,
            "venue_longitude": 103.6831, "geofence_radius_meters": 100,
        })
        enrollment = request("POST", "/enrollments/", "instructor", expected=201, json={
            "student_id": users["student"]["id"], "course_id": course["id"],
        })
        mine = request("GET", "/enrollments/my-enrollments", "student")
        assert any(row["id"] == enrollment["id"] for row in mine)

        results = []
        for latitude, outcome in ((1.3483, "approved"), (1.34965, "flagged"), (1.351, "rejected")):
            start = datetime.now(timezone.utc) + timedelta(minutes=5)
            session = request("POST", "/sessions/", "instructor", expected=201, json={
                "course_id": course["id"], "name": f"Week 3 {outcome} smoke test",
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start + timedelta(hours=1)).isoformat(),
            })
            assert session["status"] == "scheduled"
            path = f"/sessions/{session['id']}"
            payload = {"session_id": session["id"], "latitude": latitude,
                       "longitude": 103.6831, "location_accuracy_meters": 10,
                       "device_fingerprint": f"week3-{run_id}"}
            request("POST", "/checkins/", "student", expected=400, json=payload)
            request("PATCH", path, "instructor", json={"status": "active"})
            active = request("GET", "/sessions/active")
            assert any(row["id"] == session["id"] for row in active)
            if outcome == "approved":
                request("POST", "/checkins/", "student", expected=403, json=payload)
                request("PUT", "/users/me", "student", json={
                    "camera_consent": True, "geolocation_consent": True,
                })
            checkin = request("POST", "/checkins/", "student", expected=201, json=payload)
            assert checkin["status"] == outcome
            assert checkin["liveness_passed"] is None
            request("POST", "/checkins/", "student", expected=400, json=payload)
            closed = request("PATCH", path, "instructor", json={"status": "closed"})
            assert closed["status"] == "closed" and closed["checked_in_count"] == 1
            request("PATCH", path, "instructor", expected=400, json={"status": "active"})
            request("DELETE", path, "instructor", expected=400)
            results.append({"session_id": session["id"], "checkin_id": checkin["id"],
                            "status": outcome, "distance_meters": round(checkin["distance_from_venue_meters"], 2)})

        print(json.dumps({"result": "passed", "course_id": course["id"],
                          "course_code": course["code"], "checkins": results}, indent=2))


if __name__ == "__main__":
    main()
