"""Redis-backed fixed-window rate limiting."""

from functools import lru_cache

import redis
from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.config import get_settings


@lru_cache
def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_timeout=2,
        socket_connect_timeout=2,
    )


def redis_is_healthy() -> bool:
    try:
        return bool(get_redis_client().ping())
    except RedisError:
        return False


def enforce_limit(*, key: str, limit: int, window_seconds: int) -> None:
    """Reject requests that exceed a Redis fixed-window counter."""
    try:
        client = get_redis_client()
        if hasattr(client, "eval"):
            count, ttl = client.eval(
                "local n = redis.call('INCR', KEYS[1]); "
                "if n == 1 or redis.call('TTL', KEYS[1]) < 0 then "
                "redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
                "return {n, redis.call('TTL', KEYS[1])}",
                1, key, window_seconds,
            )
        else:  # Lightweight test doubles; production Redis always uses the atomic branch.
            count = client.incr(key)
            if count == 1 and hasattr(client, "expire"):
                client.expire(key, window_seconds)
            ttl = client.ttl(key) if hasattr(client, "ttl") else window_seconds
        count = int(count)
        if count > limit:
            retry_after = max(1, int(ttl))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rate limiting service unavailable",
        ) from exc


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is not None:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_registration_limit(request: Request) -> None:
    enforce_limit(
        key=f"rate:register:{client_ip(request)}",
        limit=100_000,
        window_seconds=3600,
    )


def enforce_login_limit(request: Request) -> None:
    enforce_limit(
        key=f"rate:login:{client_ip(request)}",
        limit=100_000,
        window_seconds=3600,
    )


def enforce_user_api_limit(user_id: str) -> None:
    enforce_limit(key=f"rate:api:{user_id}", limit=1000, window_seconds=3600)


def enforce_checkin_limit(user_id: str) -> None:
    enforce_limit(key=f"rate:checkin:{user_id}", limit=10, window_seconds=60)
