"""Logout support: revoked JWTs are remembered in Redis until they would expire anyway."""

from hashlib import sha256
from time import time

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from app.rate_limit import get_redis_client


def _key(token: str) -> str:
    # Only a digest is stored; the bearer token itself never reaches Redis.
    return "revoked-token:" + sha256(token.encode("utf-8")).hexdigest()


def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="token revocation service unavailable")


def revoke_token(token: str, expires_at: int) -> None:
    ttl = int(expires_at - time())
    if ttl <= 0:
        return  # Already expired: nothing left to revoke.
    try:
        get_redis_client().set(_key(token), "1", ex=ttl)
    except RedisError:
        raise _unavailable() from None


def is_revoked(token: str) -> bool:
    try:
        return bool(get_redis_client().exists(_key(token)))
    except RedisError:
        raise _unavailable() from None
