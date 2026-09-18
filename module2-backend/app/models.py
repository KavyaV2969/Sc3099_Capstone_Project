"""Persistence models for authentication and the core attendance flow."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retention_deadline() -> datetime:
    return utc_now() + timedelta(days=30)


class JSONText(TypeDecorator):
    """Portable JSON storage that remains compatible with the existing TEXT columns."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'ta', 'instructor', 'admin')",
            name="ck_users_role",
        ),
        Index("ix_users_role", "role"),
        Index("ix_users_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="student")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    camera_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    geolocation_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    face_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    face_embedding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_deletion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSONText, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("venue_latitude BETWEEN -90 AND 90", name="ck_courses_latitude"),
        CheckConstraint("venue_longitude BETWEEN -180 AND 180", name="ck_courses_longitude"),
        CheckConstraint("geofence_radius_meters > 0", name="ck_courses_radius"),
        CheckConstraint("risk_threshold BETWEEN 0 AND 1", name="ck_courses_risk"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    semester: Mapped[str] = mapped_column(String(20), index=True)
    instructor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    venue_name: Mapped[str | None] = mapped_column(String(255))
    venue_latitude: Mapped[float | None] = mapped_column(Float)
    venue_longitude: Mapped[float | None] = mapped_column(Float)
    geofence_radius_meters: Mapped[float] = mapped_column(Float, default=100.0)
    risk_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CourseTA(Base):
    """Explicit TA assignments; a global TA role alone grants no roster access."""
    __tablename__ = "course_tas"

    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    ta_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_enrollments_student_course"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'active', 'closed', 'cancelled')", name="ck_sessions_status"),
        CheckConstraint("session_type IN ('lecture', 'tutorial', 'lab', 'exam')", name="ck_sessions_type"),
        CheckConstraint("scheduled_end > scheduled_start", name="ck_sessions_schedule"),
        CheckConstraint("checkin_closes_at > checkin_opens_at", name="ck_sessions_window"),
        CheckConstraint("venue_latitude BETWEEN -90 AND 90", name="ck_sessions_latitude"),
        CheckConstraint("venue_longitude BETWEEN -180 AND 180", name="ck_sessions_longitude"),
        CheckConstraint("geofence_radius_meters > 0", name="ck_sessions_radius"),
        CheckConstraint("risk_threshold BETWEEN 0 AND 1", name="ck_sessions_risk"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    instructor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    session_type: Mapped[str] = mapped_column(String(50), default="lecture")
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checkin_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checkin_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue_name: Mapped[str | None] = mapped_column(String(255))
    venue_latitude: Mapped[float] = mapped_column(Float)
    venue_longitude: Mapped[float] = mapped_column(Float)
    geofence_radius_meters: Mapped[float] = mapped_column(Float)
    require_liveness_check: Mapped[bool] = mapped_column(Boolean, default=True)
    require_face_match: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_fingerprint", name="uq_devices_user_fingerprint"),
        CheckConstraint("trust_score IN ('low', 'medium', 'high')", name="ck_devices_trust_score"),
        Index("ix_devices_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trust_score: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_checkins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("student_id", "session_id", name="uq_checkins_student_session"),
        CheckConstraint("status IN ('pending', 'approved', 'flagged', 'rejected', 'appealed')", name="ck_checkins_status"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_checkins_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_checkins_longitude"),
        CheckConstraint("location_accuracy_meters >= 0", name="ck_checkins_accuracy"),
        CheckConstraint("distance_from_venue_meters >= 0", name="ck_checkins_distance"),
        CheckConstraint("risk_score BETWEEN 0 AND 1", name="ck_checkins_risk"),
        Index("ix_checkins_status_checked_in", "status", "checked_in_at"),
        Index("ix_checkins_risk_score", "risk_score"),
        Index("ix_checkins_scheduled_deletion_at", "scheduled_deletion_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location_accuracy_meters: Mapped[float] = mapped_column(Float)
    distance_from_venue_meters: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_factors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONText, nullable=True)
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    liveness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_match_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    face_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_deletion_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=retention_deadline
    )
