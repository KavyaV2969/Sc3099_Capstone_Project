"""Redis-backed fixed-window rate limiting."""

from functools import lru_cache

import redis
from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.config import get_settings


@lru_cache
def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def redis_is_healthy() -> bool:
    try:
        return bool(get_redis_client().ping())
    except RedisError:
        return False


def enforce_limit(*, key: str, limit: int, window_seconds: int) -> None:
    """Reject requests that exceed a Redis fixed-window counter."""
    try:
        client = get_redis_client()
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, window_seconds)
        if count > limit:
            retry_after = max(1, int(client.ttl(key)))
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
    return request.client.host if request.client else "unknown"


def enforce_registration_limit(request: Request) -> None:
    enforce_limit(
        key=f"rate:register:{client_ip(request)}",
        limit=10,
        window_seconds=3600,
    )


def enforce_login_limit(request: Request) -> None:
    enforce_limit(
        key=f"rate:login:{client_ip(request)}",
        limit=60,
        window_seconds=3600,
    )


def enforce_user_api_limit(user_id: str) -> None:
    enforce_limit(key=f"rate:api:{user_id}", limit=1000, window_seconds=3600)
