"""Standard Haversine distances and invalid coordinate inputs."""
import pytest

from app.utils.geolocation import haversine_distance


def test_identical_coordinates():
    assert haversine_distance(1.3483, 103.6831, 1.3483, 103.6831) == pytest.approx(0)


def test_nearby_coordinates():
    assert haversine_distance(1.3483, 103.6831, 1.3493, 103.6831) == pytest.approx(111.195, abs=0.01)


def test_antipodal_and_dateline_coordinates():
    assert haversine_distance(0, 0, 0, 180) == pytest.approx(20_015_087, abs=1)
    assert haversine_distance(0, 179.999, 0, -179.999) == pytest.approx(222.39, abs=0.1)


@pytest.mark.parametrize("coordinates", [(91, 0, 0, 0), (0, 181, 0, 0), (0, 0, -91, 0),
                                         (0, 0, 0, -181), (float('nan'), 0, 0, 0),
                                         (0, float('inf'), 0, 0)])
def test_invalid_coordinates(coordinates):
    with pytest.raises(ValueError):
        haversine_distance(*coordinates)


@pytest.mark.parametrize("latitude,longitude,allowed", [
    (1.3483, 103.6831, True),  # NTU
    (1.3521, 103.8198, True),  # Central Singapore
    (1.2494, 103.83, True),    # Sentosa
    (1.46, 103.75, False),    # Johor: inside a broad Singapore bounding box
    (1.0456, 104.0305, False), # Batam
    (40.7128, -74.006, False),
    (float("nan"), 103.8, False),
])
def test_singapore_gps_boundary(latitude, longitude, allowed):
    from app.utils.geolocation import is_in_singapore
    assert is_in_singapore(latitude, longitude) is allowed


@pytest.mark.parametrize("address,allowed", [
    ("127.0.0.1", True), ("10.2.3.4", True), ("172.16.1.2", True),
    ("192.168.1.2", True), ("::1", True), ("fd00::1", True),
    ("::ffff:192.168.1.2", True), ("203.0.113.1", False),
    ("224.0.0.1", False), ("not-an-ip", False), ("", False),
])
def test_local_and_invalid_ips_do_not_need_lookup(monkeypatch, address, allowed):
    from app.utils import geolocation
    def unexpected():
        pytest.fail("local/invalid IP triggered an external lookup")
    monkeypatch.setattr(geolocation, "get_redis_client", unexpected)
    assert geolocation.ip_is_in_singapore(address) is allowed


def test_public_country_lookup_is_cached(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.utils import geolocation
    cached, calls = {}, []
    def save(key, seconds, value):
        assert seconds == 86400
        cached[key] = value
    def lookup(url, **kwargs):
        calls.append(url)
        assert kwargs["timeout"] == 3.0
        return httpx.Response(200, request=httpx.Request("GET", url),
                              json={"success": True, "country_code": "SG"})
    monkeypatch.setattr(geolocation, "get_redis_client", lambda: SimpleNamespace(get=cached.get, setex=save))
    monkeypatch.setattr(geolocation.httpx, "get", lookup)
    assert geolocation.ip_is_in_singapore("8.8.8.8") is True
    assert geolocation.ip_is_in_singapore("8.8.8.8") is True
    assert calls == ["https://ipwho.is/8.8.8.8"]


@pytest.mark.parametrize("failure", ["timeout", "http", "unsuccessful", "missing_country", "malformed"])
def test_public_lookup_failures_return_503(monkeypatch, failure):
    import httpx
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.utils import geolocation
    monkeypatch.setattr(geolocation, "get_redis_client", lambda: SimpleNamespace(get=lambda _: None))
    def lookup(url, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout")
        data = {"success": True, "country_code": "SG"}
        if failure == "unsuccessful":
            data["success"] = False
        elif failure == "missing_country":
            data.pop("country_code")
        elif failure == "malformed":
            data = []
        return httpx.Response(429 if failure == "http" else 200,
                              request=httpx.Request("GET", url), json=data)
    monkeypatch.setattr(geolocation.httpx, "get", lookup)
    with pytest.raises(HTTPException) as error:
        geolocation.ip_is_in_singapore("8.8.8.8")
    assert error.value.status_code == 503
