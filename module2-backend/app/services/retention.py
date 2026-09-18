"""Thirty-day attendance retention and scheduled account anonymisation."""

import asyncio
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.models import Checkin, Device, User
from app.security import hash_password

logger = logging.getLogger(__name__)


def cleanup_expired_records(database: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Delete expired check-ins and irreversibly anonymise due user accounts."""
    deadline = now or datetime.now(timezone.utc)
    checkins_deleted = database.execute(
        delete(Checkin).where(Checkin.scheduled_deletion_at <= deadline)
    ).rowcount or 0
    users = database.scalars(
        select(User).where(
            User.scheduled_deletion_at.is_not(None),
            User.scheduled_deletion_at <= deadline,
        ).with_for_update()
    ).all()
    for user in users:
        database.execute(delete(Device).where(Device.user_id == user.id))
        user.email = f"deleted-{user.id}@deleted.invalid"
        user.full_name = "Deleted User"
        user.hashed_password = hash_password(secrets.token_urlsafe(32))
        user.role = "student"
        user.is_active = False
        user.failed_login_attempts = 0
        user.camera_consent = False
        user.geolocation_consent = False
        user.face_enrolled = False
        user.face_embedding_hash = None
        user.last_login_at = None
        user.scheduled_deletion_at = None
    database.commit()
    return {"checkins_deleted": checkins_deleted, "users_anonymised": len(users)}


def run_retention_once() -> dict[str, int]:
    with SessionLocal() as database:
        try:
            result = cleanup_expired_records(database)
            logger.info(
                "retention cleanup complete: checkins=%d users=%d",
                result["checkins_deleted"], result["users_anonymised"],
            )
            return result
        except Exception:
            database.rollback()
            logger.exception("retention cleanup failed")
            raise


async def retention_worker(settings: Settings, stop: asyncio.Event) -> None:
    if not settings.retention_cleanup_enabled:
        return
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.retention_cleanup_interval_seconds)
        except TimeoutError:
            try:
                await asyncio.to_thread(run_retention_once)
            except Exception:
                pass
