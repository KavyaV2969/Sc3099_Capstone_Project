"""Readiness must fail closed and device registration must honor the contract."""
from key_fixtures import PUBLIC_KEY
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import main
from app.models import Device
from app.schema_contract import DatabaseReadiness, _normalize_check
from test_compliance_routes import compliance_api


def test_health_marks_reachable_schema_drift_unhealthy(monkeypatch):
    monkeypatch.setattr(main, "database_readiness", lambda: DatabaseReadiness(True, "incompatible", ("checkins: incompatible columns",)))
    monkeypatch.setattr(main, "redis_is_healthy", lambda: True)
    response = TestClient(main.app).get("/health")
    assert response.status_code == 503
    assert response.json()["schema"] == "incompatible"
    assert "checkins" not in response.text


def test_retention_never_starts_against_incompatible_schema(monkeypatch):
    monkeypatch.setattr(main.settings, "retention_cleanup_enabled", True)
    monkeypatch.setattr(main, "database_readiness", lambda: DatabaseReadiness(True, "incompatible"))
    def forbidden(*args):
        raise AssertionError("Retention must not run")
    monkeypatch.setattr(main, "run_retention_once", forbidden)
    monkeypatch.setattr(main, "retention_worker", forbidden)
    with TestClient(main.app):
        pass


def test_catalog_normalization_preserves_case_sensitive_values():
    a = "role::text = ANY (ARRAY['admin'::character varying]::text[])"
    b = "role::text = ANY (ARRAY['admin'::character varying::text])"
    assert _normalize_check(a) == _normalize_check(b)
    assert _normalize_check(a) != _normalize_check(a.replace("'admin'", "'ADMIN'"))


def test_registration_allows_keyless_but_rejects_blank_key_and_overlength_fingerprint(compliance_api):
    client, _, _ = compliance_api
    payload = {"device_fingerprint": "phone", "device_name": "Phone", "platform": "ios"}
    assert client.post("/api/v1/devices/register", json=payload).status_code == 201
    payload["public_key"] = ""
    assert client.post("/api/v1/devices/register", json=payload).status_code == 422
    payload["public_key"] = "   "
    assert client.post("/api/v1/devices/register", json=payload).status_code == 422
    payload.update(public_key=PUBLIC_KEY, device_fingerprint="x" * 65)
    assert client.post("/api/v1/devices/register", json=payload).status_code == 422


def test_global_fingerprint_conflict_and_reregistration(compliance_api):
    client, engine, ids = compliance_api
    payload = {"device_fingerprint": "unique-phone", "device_name": "Phone", "platform": "ios", "public_key": PUBLIC_KEY}
    first = client.post("/api/v1/devices/register", headers={"x-test-user": "student"}, json=payload)
    assert first.status_code == 201
    assert first.json()["last_seen_at"]
    repeated = client.post("/api/v1/devices/register", headers={"x-test-user": "student"}, json=payload)
    assert repeated.status_code == 201 and repeated.json()["id"] == first.json()["id"]
    conflict = client.post("/api/v1/devices/register", headers={"x-test-user": "student2"}, json=payload)
    assert conflict.status_code == 400
    with Session(engine) as database:
        devices = list(database.scalars(select(Device)))
        assert len(devices) == 1 and devices[0].user_id == ids["student"]


def test_nullable_legacy_device_fields_and_key_remain_readable(compliance_api):
    client, engine, ids = compliance_api
    with Session(engine) as database:
        device = Device(user_id=ids["student"], device_fingerprint="legacy-phone")
        database.add(device)
        database.commit()
        device_id = device.id
    response = client.get("/api/v1/devices/my-devices", headers={"x-test-user": "student"})
    assert response.status_code == 200
    assert response.json()[0]["device_name"] is None
    assert response.json()[0]["platform"] is None
    with Session(engine) as database:
        assert database.get(Device, device_id).public_key is None
