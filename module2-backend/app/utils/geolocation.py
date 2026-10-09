"""Venue distance and Singapore eligibility without a geospatial dependency."""
from bisect import bisect_right
from functools import lru_cache
from ipaddress import ip_address, ip_network
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

LOCAL_NETWORKS = tuple(ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters for valid latitude/longitude pairs."""
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("longitude must be between -180 and 180")
    phi1, phi2 = radians(lat1), radians(lat2)
    a = sin((phi2 - phi1) / 2) ** 2 + cos(phi1) * cos(phi2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(min(1.0, max(0.0, a))))


@lru_cache(maxsize=1)
def _singapore_polygons():
    path = DATA / "singapore.geojson"
    geometry = json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"]
    return geometry["coordinates"]


def _inside_ring(latitude: float, longitude: float, ring: list) -> bool:
    """Ray casting, treating points on a polygon edge as inside."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1)
        if abs(cross) < 1e-12 and min(x1, x2) <= longitude <= max(x1, x2) and min(y1, y2) <= latitude <= max(y1, y2):
            return True
        if (y1 > latitude) != (y2 > latitude):
            if longitude < x1 + (latitude - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def is_in_singapore(latitude: float, longitude: float) -> bool:
    # Cheap rejection before checking the bundled land polygons and their holes.
    if not (1 <= latitude <= 2 and 103 <= longitude <= 105):
        return False
    return any(_inside_ring(latitude, longitude, polygon[0]) and
               not any(_inside_ring(latitude, longitude, hole) for hole in polygon[1:])
               for polygon in _singapore_polygons())


@lru_cache(maxsize=1)
def _singapore_ip_ranges():
    """Sorted, merged (first, last) integer ranges per IP version from the bundled APNIC data."""
    ranges = {4: [], 6: []}
    for line in (DATA / "singapore_ip_ranges.txt").read_text(encoding="ascii").splitlines():
        if line and not line.startswith("#"):
            network = ip_network(line)
            ranges[network.version].append((int(network.network_address), int(network.broadcast_address)))
    for items in ranges.values():
        items.sort()
    return {version: (items, [first for first, _ in items]) for version, items in ranges.items()}


def ip_is_in_singapore(value: str) -> bool:
    """Allow local IPs; public IPs must fall in Singapore's APNIC-delegated blocks.

    The lookup is offline and deterministic: no third party receives student
    addresses, and grading without internet access behaves the same as with it.
    """
    try:
        address = ip_address(value)
    except ValueError:
        return False
    address = getattr(address, "ipv4_mapped", None) or address
    if address.is_loopback or address.is_link_local or any(address in network for network in LOCAL_NETWORKS):
        return True
    # Reserved/documentation/multicast addresses are not campus addresses.
    if not address.is_global or address.is_multicast:
        return False
    ranges, starts = _singapore_ip_ranges()[address.version]
    position = bisect_right(starts, int(address)) - 1
    return position >= 0 and int(address) <= ranges[position][1]
