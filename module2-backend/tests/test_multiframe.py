"""Multi-frame HTTP contract, privacy, and device-proof regressions."""
import base64
import json
from hashlib import sha256
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import AuditLog, Checkin
from app.schemas import CheckinCreate
from app.services.devices import payload_digest
from key_fixtures import PRIVATE_KEY
from test_completion import register_device
from test_verification import enabled, face_http
from test_week3 import api, course, session, enrollment, ready, checkin_payload


@pytest.mark.parametrize("challenge_type,count", [
    ("blink", 24), ("head_turn", 25), ("passive", 30), ("blink", 1), ("head_turn", 30),
])
def test_all_frames_reach_liveness_and_only_first_reaches_face(api, ready, face_http, challenge_type, count, caplog):
    enabled(api, ready)
    frames = [f"private-frame-{n}" for n in range(count)]
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(
        ready, liveness_challenge_response=frames, challenge_type=challenge_type))
    assert response.status_code == 201, response.text
    assert response.json()["liveness_passed"] is True
    assert response.json()["face_match_passed"] is True
    assert face_http[0] == [
        ("/liveness/check", {"challenge_response": frames, "challenge_type": challenge_type}),
        ("/face/verify", {"image": frames[0], "reference_template_hash": "b" * 64}),
    ]
    with api.database() as db:
        audits = str(list(db.scalars(select(AuditLog.details))))
    assert "private-frame" not in response.text + audits + caplog.text


@pytest.mark.parametrize("challenge_type", ["passive", "blink", "head_turn"])
def test_single_image_still_supported_for_each_challenge(api, ready, face_http, challenge_type):
    enabled(api, ready)
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(
        ready, liveness_challenge_response="private-image", challenge_type=challenge_type))
    assert response.status_code == 201, response.text
    assert face_http[0][0][1] == {"challenge_response": "private-image", "challenge_type": challenge_type}
    assert face_http[0][1][1]["image"] == "private-image"


@pytest.mark.parametrize("changes", [
    {"liveness_challenge_response": []},
    {"liveness_challenge_response": ["private-frame"] * 31},
    {"liveness_challenge_response": [""]},
    {"liveness_challenge_response": ["private-frame", " \t"]},
    {"liveness_challenge_response": [None]},
    {"liveness_challenge_response": [12]},
    {"liveness_challenge_response": [["private-frame"]]},
    {"challenge_type": "headturn"},
    {"challenge_type": None},
])
def test_invalid_sequences_fail_before_upstream_or_attendance(api, ready, face_http, changes):
    enabled(api, ready)
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(ready, **changes))
    assert response.status_code == 422, response.text
    assert face_http[0] == []
    assert "private-frame" not in response.text
    with api.database() as db:
        assert db.scalar(select(func.count(Checkin.id))) == 0


def test_each_frame_retains_existing_decoded_size_limit():
    payload = checkin_payload({"id": str(uuid4())},
                              liveness_challenge_response=["small", "A" * 13_981_016])
    with pytest.raises(ValidationError, match="decoded image exceeds 10 MiB"):
        CheckinCreate(**payload)


def test_sequences_remain_subject_to_total_request_size(api, ready, face_http):
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(
        ready, liveness_challenge_response=["A" * 600_000] * 30, challenge_type="blink"))
    assert response.status_code == 413
    assert face_http[0] == []


def test_http_200_failed_blink_is_rejected(api, ready, face_http):
    enabled(api, ready)
    face_http[1]["/liveness/check"] = {
        "liveness_passed": False, "liveness_score": .3, "liveness_threshold": .6,
        "challenge_type": "blink", "details": {"challenge_completed": False},
    }
    response = api.request("POST", "/checkins/", "student", json=checkin_payload(
        ready, liveness_challenge_response=["frame"] * 24, challenge_type="blink"))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "rejected"
    assert response.json()["liveness_passed"] is False


def test_passive_hash_is_compatible_with_existing_device_proofs():
    payload = CheckinCreate(**checkin_payload({"id": str(uuid4())}, liveness_challenge_response="image"))
    old_data = payload.model_dump(mode="json", exclude={"device_challenge_id", "device_signature", "challenge_type"})
    old_digest = sha256(json.dumps(old_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert payload_digest(payload) == old_digest
    assert payload_digest(payload.model_copy(update={"challenge_type": "passive"})) == old_digest


@pytest.mark.parametrize("tamper", [None, "type", "frame", "order"])
def test_signed_sequences_bind_challenge_type_and_every_frame(api, ready, face_http, tamper):
    enabled(api, ready)
    device_id = register_device(api)
    payload = checkin_payload(ready, liveness_challenge_response=["first", "second"], challenge_type="blink")
    issued = api.request("POST", f"/devices/{device_id}/challenge", "student", json=payload)
    assert issued.status_code == 200, issued.text
    challenge = issued.json()
    signature = PRIVATE_KEY.sign(base64.b64decode(challenge["signing_payload"]), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    payload.update(device_challenge_id=challenge["challenge_id"], device_signature=base64.b64encode(
        r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode())
    if tamper == "type":
        payload["challenge_type"] = "head_turn"
    elif tamper == "frame":
        payload["liveness_challenge_response"][1] = "changed"
    elif tamper == "order":
        payload["liveness_challenge_response"].reverse()
    response = api.request("POST", "/checkins/", "student", json=payload)
    assert response.status_code == (201 if tamper is None else 403), response.text
    if tamper:
        assert face_http[0] == []
