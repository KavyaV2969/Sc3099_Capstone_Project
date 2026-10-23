"""Key possession proof bound to a single proposed check-in; no biometric storage."""
import base64
import json
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.rate_limit import get_redis_client


def parse_key(value: str):
    try:
        key = serialization.load_pem_public_key(value.encode("ascii"))
        if isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1):
            return key, "ECDSA-P256-SHA256"
        if isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048:
            return key, "RSASSA-PKCS1-v1_5-SHA256"
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm):
        pass
    raise HTTPException(status_code=400, detail="public_key must be PEM P-256 or RSA (at least 2048 bits)")


def canonical_key(value: str) -> str:
    key, _ = parse_key(value)
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def payload_digest(payload) -> str:
    data = payload.model_dump(mode="json", exclude={"device_challenge_id", "device_signature"})
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_challenge(device, payload, user_id: str) -> dict:
    _, algorithm = parse_key(device.public_key or "")
    challenge_id = str(uuid4())
    content = {"version": 1, "challenge_id": challenge_id, "nonce": token_urlsafe(32),
               "user_id": user_id, "device_id": device.id, "session_id": str(payload.session_id),
               "key_hash": sha256(canonical_key(device.public_key).encode()).hexdigest(),
               "payload_hash": payload_digest(payload)}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"))
    try:
        get_redis_client().set("device-proof:" + challenge_id, raw, ex=120, nx=True)
    except RedisError:
        raise HTTPException(status_code=503, detail="device proof service unavailable") from None
    return {"challenge_id": challenge_id, "expires_in_seconds": 120,
            "algorithm": algorithm, "signing_payload": base64.b64encode(raw.encode()).decode()}


def verify_proof(device, payload, user_id: str) -> str | None:
    if payload.device_challenge_id is None:
        return None
    if device is None or device.revoked_at is not None or not device.is_active:
        raise HTTPException(status_code=403, detail="device proof is invalid or expired")
    key, algorithm = parse_key(device.public_key or "")
    try:
        raw = get_redis_client().get("device-proof:" + str(payload.device_challenge_id))
    except RedisError:
        raise HTTPException(status_code=503, detail="device proof service unavailable") from None
    try:
        content = json.loads(raw or "null")
        if (not content or content["user_id"] != user_id or content["device_id"] != device.id
            or content["session_id"] != str(payload.session_id)
            or content["key_hash"] != sha256(canonical_key(device.public_key).encode()).hexdigest()
            or content["payload_hash"] != payload_digest(payload)):
            raise ValueError("invalid binding")
        signature = base64.b64decode(payload.device_signature, validate=True)
        if algorithm == "ECDSA-P256-SHA256":
            if len(signature) != 64:
                raise ValueError("expected WebCrypto P1363 signature")
            signature = utils.encode_dss_signature(int.from_bytes(signature[:32], "big"),
                                                   int.from_bytes(signature[32:], "big"))
            key.verify(signature, raw.encode(), ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, raw.encode(), padding.PKCS1v15(), hashes.SHA256())
        return raw
    except (ValueError, TypeError, KeyError, InvalidSignature):
        raise HTTPException(status_code=403, detail="device proof is invalid or expired") from None


def consume_proof(payload, expected: str | None) -> None:
    if expected is None:
        return
    try:
        consumed = get_redis_client().eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "return redis.call('DEL', KEYS[1]); end; return 0",
            1, "device-proof:" + str(payload.device_challenge_id), expected,
        )
    except RedisError:
        raise HTTPException(status_code=503, detail="device proof service unavailable") from None
    if not consumed:
        raise HTTPException(status_code=403, detail="device proof is invalid or expired")
