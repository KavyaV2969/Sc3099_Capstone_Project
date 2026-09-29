"""HTTP-boundary and policy regressions for F01/F02 and creation defaults."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import face_service
from app.config import Settings
from app.models import AuditLog, Checkin, Course, Device, Session, User
from app.risk import assess_risk
from test_week3 import api, course, session, enrollment, ready, checkin_payload

LIVE = {"liveness_passed": True, "liveness_score": .8, "liveness_threshold": .6}
FACE = {"match_passed": True, "match_score": .9, "match_threshold": .7, "face_detected": True}
ENROLL = {"enrollment_successful": True, "quality_score": .5, "face_template_hash": "a" * 64,
          "details": {"face_detected": True, "face_detection_confidence": .7}}


@pytest.fixture
def face_http(monkeypatch):
    """Exercise the production client, response validators and actual HTTP payloads."""
    calls = []
    responses = {"/liveness/check": LIVE, "/face/verify": FACE, "/face/enroll": ENROLL}
    statuses = {}
    failures = {}
    real_client = httpx.AsyncClient
    # Alembic's logging setup runs earlier in the full suite and disables
    # existing loggers. Own this logger's test configuration explicitly.
    monkeypatch.setattr(face_service.logger, "disabled", False)

    def handler(request):
        path = request.url.path
        calls.append((path, json.loads(request.content)))
        if path in failures:
            raise failures[path]
        status = statuses.get(path, 201 if path == "/face/enroll" else 200)
        value = responses[path]
        if isinstance(value, bytes):
            return httpx.Response(status, content=value)
        return httpx.Response(status, json=value)

    monkeypatch.setattr(face_service.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return calls, responses, statuses, failures


def enabled(api, ready, live=True, face=True):
    with api.database() as db:
        row = db.get(Session, ready["id"])
        row.require_liveness_check, row.require_face_match = live, face
        user = db.get(User, api.users["student"].id)
        user.face_enrolled, user.face_embedding_hash = True, "b" * 64
        db.commit()


@pytest.mark.parametrize("live,face", [(False, False), (True, False), (False, True), (True, True)])
def test_flags_control_calls_and_approved_evidence(api, ready, face_http, live, face):
    enabled(api, ready, live, face)
    result = api.request("POST", "/checkins/", "student", json=checkin_payload(
        ready, liveness_challenge_response="private-image")).json()
    assert result["status"] == "approved"
    assert result["liveness_passed"] is (True if live else None)
    assert result["face_match_passed"] is (True if face else None)
    expected = (["/liveness/check"] if live else []) + (["/face/verify"] if face else [])
    assert [path for path, _ in face_http[0]] == expected
    if live:
        assert face_http[0][0][1] == {"challenge_response": "private-image", "challenge_type": "passive"}
    if face:
        assert face_http[0][-1][1] == {"image": "private-image", "reference_template_hash": "b" * 64}
    with api.database() as db:
        details = db.scalar(select(AuditLog.details).where(AuditLog.action == "checkin_approved"))
        assert details["policy"] == "weighted-v1" and details["network_detection"] == "unavailable"
        assert sum(details["contributions"].values()) == pytest.approx(result["risk_score"])
        assert "private-image" not in str(details) and "b" * 64 not in str(details)


@pytest.mark.parametrize("image", [None, "", "  \n\t"])
@pytest.mark.parametrize("live,face", [(True, False), (False, True), (True, True)])
def test_required_image_fails_before_any_call(api, ready, face_http, image, live, face):
    enabled(api, ready, live, face)
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response=image))
    assert response.status_code == 400 and face_http[0] == []
    with api.database() as db:
        assert db.scalar(select(func.count(Checkin.id))) == 0


def invalid_results(valid, passed, score, threshold):
    cases = [{}, [], {"unrelated": True}, {**valid, passed: None}, {**valid, score: None},
             {**valid, passed: "true"}, {**valid, passed: 1}, {**valid, score: "0.8"},
             {**valid, score: float("nan")}, {**valid, score: float("inf")},
             {**valid, score: -.1}, {**valid, score: 1.1}, {**valid, passed: False},
             {**valid, threshold: .1}, {**valid, threshold: "0.7"},
             {k: v for k, v in valid.items() if k != score}]
    return cases


@pytest.mark.parametrize("path,result", [
    *[("/liveness/check", r) for r in invalid_results(LIVE, "liveness_passed", "liveness_score", "liveness_threshold")],
    *[("/face/verify", r) for r in invalid_results(FACE, "match_passed", "match_score", "match_threshold")],
    ("/face/verify", {**FACE, "face_detected": False}),
    ("/face/verify", {**FACE, "current_template_hash": "bad-private-hash"}),
    ("/liveness/check", FACE), ("/face/verify", LIVE),
    ("/liveness/check", b"private-image-invalid-json"),
])
def test_invalid_service_results_never_create_attendance(api, ready, face_http, caplog, path, result):
    enabled(api, ready)
    face_http[1][path] = result
    with api.database() as db:
        db.add(Device(user_id=api.users["student"].id, device_fingerprint="test-device", public_key="legacy-test"))
        db.commit()
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response="private-image"))
    assert response.status_code == 503
    assert response.json()["detail"] == "face recognition service unavailable"
    assert "private-image" not in caplog.text and "bad-private-hash" not in caplog.text
    assert "category=invalid_response" in caplog.text
    with api.database() as db:
        assert db.scalar(select(func.count(Checkin.id))) == 0
        assert db.scalar(select(Device.total_checkins)) == 0
        assert db.scalar(select(AuditLog.success).where(AuditLog.action == "checkin_rejected")) is False


@pytest.mark.parametrize("status,expected", [(400, 400), (422, 400), (401, 503), (429, 503), (500, 503), (302, 503), (204, 503)])
def test_upstream_statuses_are_controlled(api, ready, face_http, status, expected):
    enabled(api, ready, True, False)
    face_http[2]["/liveness/check"] = status
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response="image"))
    assert response.status_code == expected


@pytest.mark.parametrize("error", [httpx.ReadTimeout("secret upstream body"), httpx.ConnectError("secret credentials")])
def test_transport_errors_are_sanitized(api, ready, face_http, error, caplog):
    enabled(api, ready, True, False)
    face_http[3]["/liveness/check"] = error
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response="image"))
    assert response.status_code == 503
    assert "secret" not in response.text + caplog.text
    assert "operation=/liveness/check" in caplog.text


@pytest.mark.parametrize("path,score,passed", [("/liveness/check", .6, True), ("/liveness/check", .5999, False),
                                             ("/face/verify", .7, True), ("/face/verify", .6999, False)])
def test_biometric_boundaries_and_rejected_records(api, ready, face_http, path, score, passed):
    enabled(api, ready, path == "/liveness/check", path == "/face/verify")
    key = "liveness" if path == "/liveness/check" else "match"
    face_http[1][path] = {**face_http[1][path], key + "_score": score, key + "_passed": passed}
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, liveness_challenge_response="image"))
    assert response.status_code == 201
    assert response.json()["status"] == ("approved" if passed else "rejected")
    assert (response.json()["verified_at"] is not None) == passed


@pytest.mark.parametrize("changes", [{"quality_score": .4999}, {"face_template_hash": "bad"}, {"face_template_hash": None},
                                     {"quality_score": "0.9"}, {"quality_score": float("nan")},
                                     {"enrollment_successful": "true"}, {"quality_score": None},
                                     {"details": None}, {"details": {"face_detected": False, "face_detection_confidence": .9}},
                                     {"details": {"face_detected": True, "face_detection_confidence": .6999}}])
def test_inconsistent_enrollment_preserves_previous_hash(api, face_http, changes):
    face_http[1]["/face/enroll"] = {**ENROLL, **changes}
    response = api.request("POST", "/users/me/face/enroll", "student", json={"image": "image"})
    assert response.status_code == 503
    with api.database() as db:
        user = db.get(User, api.users["student"].id)
        assert user.face_embedding_hash is None and user.face_enrolled is False


def test_enrollment_at_boundaries_and_valid_failure(api, face_http):
    response = api.request("POST", "/users/me/face/enroll", "student", json={"image": "image"})
    assert response.status_code == 200 and response.json()["quality_score"] == .5
    face_http[1]["/face/enroll"] = {"enrollment_successful": False, "quality_score": .1}
    assert api.request("POST", "/users/me/face/enroll", "student", json={"image": "image"}).status_code == 400
    with api.database() as db:
        assert db.get(User, api.users["student"].id).face_embedding_hash == "a" * 64


def risk(**changes):
    values = dict(distance=0, radius=100, location_accuracy=10, require_liveness=False, require_face=False,
                  liveness_score=None, liveness_passed=None, face_score=None, face_passed=None,
                  known_device=False, trusted_device=False, local_network=True, threshold=.5)
    return assess_risk(**(values | changes))


@pytest.mark.parametrize("threshold,status", [(0, "flagged"), (.2, "flagged"), (.2001, "approved"), (.5, "approved"), (1, "approved")])
def test_thresholds_apply_without_optional_biometrics(threshold, status):
    decision = risk(threshold=threshold)
    assert decision.score == .2 and decision.status == status
    assert decision.factors[0]["risk"] == 1 and decision.factors[0]["contribution"] == .2


def test_weights_accuracy_device_and_geofence_boundaries():
    assert risk(location_accuracy=100).score == .2
    assert risk(location_accuracy=100.01).score == .2375
    assert risk(known_device=True).score == .1
    assert risk(known_device=True, trusted_device=True).score == 0
    assert risk(trusted_device=True).score == .2  # Trust without ownership/existence is insufficient.
    assert risk(distance=200).status == "approved"
    assert risk(distance=200.01, threshold=1).status == "rejected"
    assert risk(distance=.1, radius=.2, location_accuracy=0).score == .275
    decision = risk(require_liveness=True, require_face=True, liveness_score=.8, liveness_passed=True,
                    face_score=.8, face_passed=True, local_network=False, distance=50)
    assert decision.contributions == pytest.approx({"liveness": .05, "face_match": .05, "device": .2, "network": .03, "geolocation": .075})
    assert decision.score == .405


def test_critical_score_overrides_threshold_and_failures_have_factors():
    decision = risk(require_liveness=True, liveness_score=0, liveness_passed=False,
                    require_face=True, face_score=.6, face_passed=False, distance=100, threshold=1)
    assert decision.score == .7 and decision.status == "rejected"
    assert {f["type"] for f in decision.factors if f["critical"]} == {"liveness", "face_match"}
    failed = risk(require_face=True, face_score=.6999, face_passed=False, known_device=True, trusted_device=True)
    assert failed.status == "rejected" and failed.score < .1 and failed.factors[0]["critical"]


@pytest.mark.parametrize("changes", [{"require_liveness": True}, {"require_face": True},
                                     {"require_face": True, "face_score": .9},
                                     {"require_face": True, "face_score": .9, "face_passed": False},
                                     {"require_face": True, "face_score": float("nan"), "face_passed": True},
                                     {"liveness_score": .8, "liveness_passed": True}])
def test_scorer_independently_refuses_unusable_evidence(changes):
    with pytest.raises(ValueError):
        risk(**changes)


def test_configured_defaults_and_explicit_zero(api, monkeypatch):
    import app.config as config
    settings = Settings(secret_key="default-test-key-at-least-thirty-two-chars", risk_score_threshold=.33)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    payload = {"code": "DEFAULT", "name": "Default", "semester": "AY26", "venue_latitude": 1.3483, "venue_longitude": 103.6831}
    created = api.request("POST", "/courses/", "admin", json=payload).json()
    assert created["risk_threshold"] == .33
    from test_week3 import session_payload
    assert api.request("POST", "/sessions/", json=session_payload(created)).json()["risk_threshold"] == .33
    assert api.request("POST", "/sessions/", json={**session_payload(created), "risk_threshold": 0}).json()["risk_threshold"] == 0
    zero = api.request("POST", "/courses/", "admin", json={**payload, "code": "ZERO", "risk_threshold": 0}).json()
    assert zero["risk_threshold"] == 0
    settings.risk_score_threshold = .9
    assert api.request("GET", f"/courses/{created['id']}").json()["risk_threshold"] == .33
    with api.database() as db:
        row = Course(code="ORM", name="ORM", semester="AY26")
        db.add(row)
        db.flush()
        assert row.risk_threshold == .9


@pytest.mark.parametrize("kind", ["unknown", "known", "trusted", "inactive", "other_owner"])
def test_unsigned_api_device_states_all_use_unknown_device_risk(api, ready, kind):
    if kind != "unknown":
        with api.database() as db:
            owner = api.users["other_student" if kind == "other_owner" else "student"].id
            db.add(Device(user_id=owner, device_fingerprint="test-device", is_trusted=kind == "trusted", is_active=kind != "inactive"))
            db.get(Session, ready["id"]).risk_threshold = 0
            db.commit()
    else:
        with api.database() as db:
            db.get(Session, ready["id"]).risk_threshold = 0
            db.commit()
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, location_accuracy_meters=10000))
    assert response.status_code == 201 and response.json()["status"] == "flagged"
    expected = .0375 + .2  # Inventory matching does not establish key possession.
    assert response.json()["risk_score"] == pytest.approx(expected)
