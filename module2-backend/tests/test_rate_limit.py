"""The clarified IP limits remain enforced, with socket/header IP selection."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app import rate_limit


def request(headers=(), client=("192.168.1.3", 1234)):
    return Request({"type": "http", "headers": list(headers), "client": client})


def test_client_ip_header_precedence_and_socket_fallback():
    assert rate_limit.client_ip(request()) == "192.168.1.3"
    assert rate_limit.client_ip(request([(b"x-forwarded-for", b" 8.8.8.8, 10.0.0.1")])) == "8.8.8.8"
    assert rate_limit.client_ip(request([(b"x-forwarded-for", b"")])) == ""


@pytest.mark.parametrize("enforce,prefix", [(rate_limit.enforce_login_limit, "login"),
                                           (rate_limit.enforce_registration_limit, "register")])
def test_ip_limit_allows_100000_then_rejects(monkeypatch, enforce, prefix):
    count = 99999
    def incr(key):
        nonlocal count
        assert key == f"rate:{prefix}:192.168.1.3"
        count += 1
        return count
    cache = SimpleNamespace(incr=incr, ttl=lambda _: 100)
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: cache)
    enforce(request())
    with pytest.raises(HTTPException) as error:
        enforce(request())
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "100"


def test_ip_counter_has_one_hour_expiry(monkeypatch):
    expires = []
    cache = SimpleNamespace(incr=lambda _: 1, expire=lambda key, seconds: expires.append((key, seconds)))
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: cache)
    rate_limit.enforce_registration_limit(request())
    assert expires == [("rate:register:192.168.1.3", 3600)]
