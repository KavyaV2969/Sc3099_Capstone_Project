"""User-approved public contract reductions; strict evidence/write rules remain."""
import pytest
from pydantic import ValidationError
from app.models import Checkin
from app.schemas import CheckinCreate
from app.services.devices import payload_digest
from test_week3 import api, course, session, enrollment, ready, checkin_payload


@pytest.mark.parametrize("accuracy", [None, 0, 5.5])
def test_accuracy_persists_without_inventing_measurements(api, ready, accuracy):
    payload = checkin_payload(ready, location_accuracy_meters=accuracy)
    response = api.request("POST", "/checkins/", "student", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["location_accuracy_meters"] == accuracy
    assert response.json()["risk_score"] == (.2375 if accuracy is None else .2)
    with api.database() as db:
        assert db.get(Checkin, response.json()["id"]).location_accuracy_meters == accuracy


def test_omitted_accuracy_normalizes_to_null_for_signing(api, ready):
    omitted = checkin_payload(ready)
    omitted.pop("location_accuracy_meters")
    explicit = dict(omitted, location_accuracy_meters=None)
    assert payload_digest(CheckinCreate(**omitted)) == payload_digest(CheckinCreate(**explicit))
    response = api.request("POST", "/checkins/", "student", json=omitted)
    assert response.status_code == 201 and response.json()["location_accuracy_meters"] is None


@pytest.mark.parametrize("accuracy", [-1, float("nan"), float("inf"), -float("inf")])
def test_supplied_accuracy_must_be_finite_and_nonnegative(accuracy):
    from uuid import uuid4
    with pytest.raises(ValidationError):
        CheckinCreate(**checkin_payload({"id": str(uuid4())}, location_accuracy_meters=accuracy))


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("consent", [False, True])
@pytest.mark.parametrize("image", [None, "", "  ", "image"])
def test_optional_liveness_only_evaluates_usable_consented_evidence(api, ready, monkeypatch, live, consent, image):
    from app.models import Session, User
    from app.face_service import LivenessResult
    from app.routers import checkins
    calls = []
    async def verify(value):
        calls.append(value)
        return LivenessResult(liveness_passed=True, liveness_score=.8, liveness_threshold=.6)
    monkeypatch.setattr(checkins, "check_liveness", verify)
    with api.database() as db:
        db.get(Session, ready["id"]).require_liveness_check = live
        user = db.get(User, api.users["student"].id)
        user.camera_consent, user.geolocation_consent = consent, False
        db.commit()
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response=image))
    assert response.status_code == 201, response.text
    evaluated = live and consent and bool(image and image.strip())
    assert calls == ([image] if evaluated else [])
    assert response.json()["liveness_passed"] is (True if evaluated else None)
    assert response.json()["liveness_score"] == (.8 if evaluated else None)
    assert response.json()["risk_score"] == (.25 if evaluated else .2)
    with api.database() as db:
        assert db.get(User, api.users["student"].id).geolocation_consent is False


def test_keyless_inventory_key_omission_and_null_removal(api, ready):
    from app.models import Device
    from key_fixtures import PUBLIC_KEY
    payload = {"device_fingerprint":"keyless", "device_name":"Browser", "platform":"web", "browser":"Chrome"}
    created = api.request("POST", "/devices/", "student", json=payload)
    assert created.status_code == 201, created.text
    did = created.json()["id"]
    assert created.json()["is_trusted"] is False and "browser" not in created.json()
    with api.database() as db:
        assert db.get(Device, did).public_key is None
    proposed = checkin_payload(ready, device_fingerprint="keyless")
    assert api.request("POST", f"/devices/{did}/challenge", "student", json=proposed).status_code == 400
    assert api.request("PATCH", f"/devices/{did}", "admin", json={"is_trusted":True}).status_code == 400
    assert api.request("POST", "/devices/", "other_student", json=payload).status_code == 400
    assert api.request("POST", "/devices/", "student", json=dict(payload, public_key=PUBLIC_KEY)).status_code == 201
    assert api.request("PATCH", f"/devices/{did}", "admin", json={"is_trusted":True}).status_code == 200
    assert api.request("POST", "/devices/", "student", json=payload).json()["is_trusted"] is True
    with api.database() as db:
        assert db.get(Device, did).public_key == PUBLIC_KEY
    removed = api.request("POST", "/devices/", "student", json=dict(payload, public_key=None))
    assert removed.status_code == 201 and removed.json()["is_trusted"] is False
    with api.database() as db:
        assert db.get(Device, did).public_key is None
    assert api.request("POST", f"/devices/{did}/challenge", "student", json=proposed).status_code == 400
    unsigned = api.request("POST", "/checkins/", "student", json=proposed)
    assert unsigned.status_code == 201 and unsigned.json()["risk_score"] == .2
    assert api.request("PATCH", f"/devices/{did}", "admin", json={"is_active":False}).status_code == 200
    assert api.request("POST", "/devices/", "student", json=payload).status_code == 403


@pytest.mark.parametrize("role", ["other_instructor", "admin"])
def test_global_staff_reads_preserve_unrelated_write_denials(api, ready, role):
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready))
    cid = response.json()["id"]
    uid = api.users["student"].id
    with api.database() as db:
        db.get(Checkin, cid).status = "flagged"; db.commit()
    for path in [f"/users/{uid}", f"/users/{api.users['other_student'].id}",
                 f"/stats/students/{uid}", f"/stats/students/{api.users['other_student'].id}",
                 f"/stats/courses/{ready['course_id']}", f"/stats/sessions/{ready['id']}",
                 f"/enrollments/course/{ready['course_id']}", f"/checkins/{cid}",
                 f"/checkins/session/{ready['id']}", f"/export/attendance/{ready['course_id']}?format=json",
                 f"/export/session/{ready['id']}?format=json"]:
        assert api.request("GET", path, role).status_code == 200, path
    assert api.request("GET", "/checkins/", role).json()["total"] == 1
    assert api.request("GET", "/checkins/flagged", role).json()["total"] == 1
    assert api.request("GET", f"/checkins/{cid}", "other_student").status_code == 403
    assert api.request("GET", f"/users/{api.users['admin'].id}", "other_instructor").status_code == 403
    if role == "other_instructor":
        assert api.request("POST", "/enrollments/", role, json={"course_id":ready["course_id"],"student_id":api.users['other_student'].id}).status_code == 403
        assert api.request("POST", f"/checkins/{cid}/review", role, json={"status":"approved","review_notes":"Read access is not review ownership"}).status_code == 403
        assert api.request("PATCH", f"/sessions/{ready['id']}", role, json={"status":"closed"}).status_code == 403
        assert api.request("GET", "/sessions/my-sessions", role).json() == []


def test_flagged_envelope_pagination_filters_and_ta_removal(api, ready):
    from app.models import Course, CourseTA, Session, User, utc_now
    from datetime import timedelta
    with api.database() as db:
        other = Course(code="OTHER-QUEUE", name="Other", semester="AY26")
        db.add(other); db.flush()
        source = db.get(Session, ready['id'])
        extra = Session(course_id=other.id,instructor_id=api.users['other_instructor'].id,name="Other",
            scheduled_start=source.scheduled_start, scheduled_end=source.scheduled_end,
            checkin_opens_at=source.checkin_opens_at, checkin_closes_at=source.checkin_closes_at,
            venue_latitude=1.3483,venue_longitude=103.6831,geofence_radius_meters=100)
        db.add(extra); db.flush()
        rows = []
        for sid, uid, status in [(source.id,api.users['student'].id,"flagged"),
                                 (source.id,api.users['other_student'].id,"appealed"),
                                 (extra.id,api.users['student'].id,"flagged"),
                                 (extra.id,api.users['other_student'].id,"approved")]:
            row=Checkin(session_id=sid,student_id=uid,latitude=1.3483,longitude=103.6831,
                location_accuracy_meters=None,distance_from_venue_meters=0,status=status,risk_score=.5,
                scheduled_deletion_at=utc_now()+timedelta(days=30))
            db.add(row); rows.append(row)
        db.add(CourseTA(course_id=source.course_id,ta_id=api.users['ta'].id)); db.commit()
        other_id, extra_id = other.id, extra.id
    queue=api.request("GET", "/checkins/flagged?limit=1", "other_instructor").json()
    assert queue['total']==3 and queue['limit']==1 and queue['offset']==0 and len(queue['items'])==1
    next_page=api.request("GET", "/checkins/flagged?limit=1&offset=1", "other_instructor").json()
    assert next_page['total']==3 and next_page['items'][0]['id'] != queue['items'][0]['id']
    assert api.request("GET", "/checkins/flagged?offset=3", "admin").json()['items']==[]
    assert api.request("GET", f"/checkins/flagged?course_id={other_id}").json()['total']==1
    assert api.request("GET", f"/checkins/flagged?session_id={extra_id}").json()['total']==1
    assert api.request("GET", "/checkins/flagged", "ta").json()['total']==2
    assert api.request("GET", f"/checkins/flagged?course_id={other_id}", "ta").json()['total']==0
    assert api.request("GET", f"/checkins/session/{extra_id}", "ta").status_code==403
    assert api.request("GET", "/checkins/flagged", "student").status_code==403
    with api.database() as db:
        db.delete(db.get(CourseTA,(ready['course_id'],api.users['ta'].id))); db.commit()
    assert api.request("GET", "/checkins/flagged", "ta").json()['total']==0
    assert api.request("GET", f"/enrollments/course/{ready['course_id']}", "ta").status_code==403


def test_public_catalogue_more_than_fifty_courses_orders_newest_and_filters(api, course):
    from app.models import Course, utc_now
    from datetime import timedelta
    now = utc_now()
    with api.database() as db:
        for n in range(55):
            db.add(Course(code=f"PAGE{n:03}",name="Catalogue",semester="PUBLIC",
                instructor_id=api.users['instructor'].id,created_at=now+timedelta(seconds=n)))
        db.commit()
    first = api.request("GET", "/courses/?semester=PUBLIC", None).json()
    assert first['total']==55 and len(first['items'])==50 and first['items'][0]['code']=="PAGE054"
    last = api.request("GET", "/courses/?semester=PUBLIC&offset=50", None).json()
    assert last['total']==55 and len(last['items'])==5
    assert not ({c['id'] for c in first['items']} & {c['id'] for c in last['items']})
    result = api.request("GET", f"/courses/?semester=PUBLIC&instructor_id={api.users['instructor'].id}", None)
    assert result.status_code==200 and result.json()['total']==55
    assert api.request("GET", f"/courses/{course['id']}", None).status_code==401
    assert api.request("POST", "/courses/", None, json={"code":"NOAUTH","name":"No","semester":"AY26"}).status_code==401
    assert "hashed_password" not in str(first) and "student_email" not in str(first)
