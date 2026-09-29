"""Thirty-day attendance retention and scheduled account anonymisation."""

import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select, update, text, or_
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.models import Checkin, Device, Session as AttendanceSession, User
from app.metrics import retention_runs, retention_last_success, retention_records
from app.security import hash_password

logger = logging.getLogger(__name__)


def cleanup_expired_records(database: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Delete expired check-ins and irreversibly anonymise due user accounts."""
    deadline = now or datetime.now(timezone.utc)
    if database.get_bind().dialect.name == "postgresql" and not database.scalar(
        text("SELECT pg_try_advisory_xact_lock(309930)")):
        database.rollback()
        database.info["retention_overlap_skipped"] = True
        retention_runs.labels("overlap_skipped").inc()
        return {"checkins_deleted": 0, "users_anonymised": 0}
    # Match request lock ordering before touching roster/session or device rows.
    list(database.scalars(select(User.id).where(or_(User.activation_expires_at <= deadline,
        User.scheduled_deletion_at <= deadline)).order_by(User.id).with_for_update()))
    checkins_deleted = database.execute(
        delete(Checkin).where(Checkin.scheduled_deletion_at <= deadline)
    ).rowcount or 0
    database.execute(update(AttendanceSession).where(
        AttendanceSession.checkin_closes_at <= deadline - timedelta(days=30)).values(attendance_roster=None))
    database.execute(update(User).where(User.activation_expires_at <= deadline).values(
        activation_token_hash=None, activation_expires_at=None))
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
        user.activation_token_hash = user.activation_expires_at = None
    database.commit()
    return {"checkins_deleted": checkins_deleted, "users_anonymised": len(users)}


def run_retention_once() -> dict[str, int]:
    with SessionLocal() as database:
        try:
            result = cleanup_expired_records(database)
            if database.info.pop("retention_overlap_skipped", False):
                return result
            retention_runs.labels("success").inc()
            retention_last_success.set(datetime.now(timezone.utc).timestamp())
            for kind, count in result.items():
                retention_records.labels(kind).inc(count)
            logger.info(
                "retention cleanup complete: checkins=%d users=%d",
                result["checkins_deleted"], result["users_anonymised"],
            )
            return result
        except Exception as exc:
            database.rollback()
            retention_runs.labels("failure").inc()
            logger.error("retention cleanup failed category=%s", type(exc).__name__)
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
