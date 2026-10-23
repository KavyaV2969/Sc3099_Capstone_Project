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
def test_local_and_invalid_ips(address, allowed):
    from app.utils import geolocation
    assert geolocation.ip_is_in_singapore(address) is allowed


@pytest.mark.parametrize("address,allowed", [
    ("155.69.1.1", True),            # NTU
    ("137.132.1.1", True),           # NUS
    ("::ffff:155.69.1.1", True),     # IPv4-mapped IPv6
    ("2001:208::1", True),           # Singapore IPv6 allocation
    ("1.21.224.0", True), ("1.21.255.255", True),    # first/last of 1.21.224.0/19
    ("1.21.223.255", False), ("1.22.0.0", False),    # just outside that block
    ("8.8.8.8", False), ("1.1.1.1", False), ("114.114.114.114", False),
    ("2001:4860:4860::8888", False),
])
def test_public_ips_use_bundled_apnic_ranges(address, allowed):
    from app.utils import geolocation
    assert geolocation.ip_is_in_singapore(address) is allowed


def test_ip_lookup_is_offline(monkeypatch):
    import socket
    from app.utils import geolocation
    def no_network(*args, **kwargs):
        pytest.fail("IP eligibility must not use the network")
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert geolocation.ip_is_in_singapore("155.69.1.1") is True
    assert geolocation.ip_is_in_singapore("8.8.8.8") is False


def test_bundled_ip_data_records_provenance():
    from app.utils.geolocation import DATA
    header = (DATA / "singapore_ip_ranges.txt").read_text(encoding="ascii").splitlines()[:6]
    assert any("ftp.apnic.net/stats/apnic/delegated-apnic-latest" in line for line in header)
    assert any("APNIC serial:" in line and "source MD5:" in line for line in header)
