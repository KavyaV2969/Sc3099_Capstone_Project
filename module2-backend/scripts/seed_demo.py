"""Populate local SC3099 demo data without resetting existing accounts or sessions."""
import os
from datetime import timedelta
from secrets import token_urlsafe

from fastapi import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DatabaseSession

from app.audit import write_audit_log
from app.config import get_settings
from app.models import Course, Enrollment, Session, User, utc_now
from app.migration_support import acquire_migration_lock
from app.schemas import UserRegister
from app.security import hash_password
from app.services.enrollments import capture_roster, create_enrollment
from app.services.reporting import business_day


def seed_demo(database: DatabaseSession, password: str) -> dict:
    """Stage demo records; the caller commits all changes in one transaction."""
    request = Request({"type": "http", "headers": []})
    users, created_accounts = {}, []
    for role in ("admin", "instructor", "student"):
        data = UserRegister(email=f"demo.{role}@example.com", password=password,
                            full_name=f"Demo {role.title()}", role=role)
        user = database.scalar(select(User).where(User.email == data.email))
        if user is None:
            user = User(email=data.email, full_name=data.full_name, role=role,
                        hashed_password=hash_password(data.password))
            database.add(user)
            database.flush()
            write_audit_log(database, request, action="user_created", user_id=user.id,
                            resource_type="user", resource_id=user.id, details={"source": "seed_demo"})
            created_accounts.append(user.email)
        elif user.role != role or not user.is_active or user.scheduled_deletion_at is not None:
            raise ValueError(f"Demo account conflict: {data.email}; no accounts were reset")
        users[role] = user

    course = database.scalar(select(Course).where(Course.code == "SC3099"))
    if course is None:
        course = Course(code="SC3099", name="Capstone Project", semester="AY2026-27 Sem 1",
                        instructor_id=users["instructor"].id, venue_name="NTU",
                        venue_latitude=1.3483, venue_longitude=103.6831,
                        geofence_radius_meters=100, risk_threshold=.5)
        database.add(course)
        database.flush()
        write_audit_log(database, request, action="course_created", user_id=users["admin"].id,
                        resource_type="course", resource_id=course.id, details={"source": "seed_demo"})
    elif (course.name != "Capstone Project" or course.instructor_id != users["instructor"].id
          or not course.is_active):
        raise ValueError("SC3099 already exists with different ownership/name or is inactive; left untouched")

    enrollment = database.scalar(select(Enrollment).where(
        Enrollment.course_id == course.id, Enrollment.student_id == users["student"].id))
    if enrollment is None:
        enrollment = create_enrollment(database, student_id=users["student"].id, course_id=course.id)
        write_audit_log(database, request, action="student_enrolled", user_id=users["admin"].id,
                        resource_type="course", resource_id=course.id,
                        details={"source": "seed_demo", "student_id": users["student"].id})

    now, session_ids = utc_now(), []
    for kind, days in (("lecture", 0), ("lab", 1)):
        start = now + timedelta(days=days, minutes=5)
        name = f"SC3099 Demo {kind.title()} {business_day(start)}"
        session = database.scalar(select(Session).where(Session.course_id == course.id, Session.name == name))
        if session is None:
            session = Session(course_id=course.id, instructor_id=users["instructor"].id,
                              name=name, session_type=kind, status="active" if days == 0 else "scheduled",
                              scheduled_start=start, scheduled_end=start + timedelta(hours=3),
                              checkin_opens_at=start - timedelta(minutes=10),
                              checkin_closes_at=start + timedelta(hours=3),
                              venue_name=course.venue_name, venue_latitude=course.venue_latitude,
                              venue_longitude=course.venue_longitude,
                              geofence_radius_meters=course.geofence_radius_meters,
                              risk_threshold=course.risk_threshold,
                              require_liveness_check=True, require_face_match=True)
            database.add(session)
            database.flush()
            if session.status == "active":
                capture_roster(database, session)
            write_audit_log(database, request, action="session_created", user_id=users["instructor"].id,
                            resource_type="session", resource_id=session.id, details={"source": "seed_demo"})
        session_ids.append(session.id)
    return {"course_id": course.id, "session_ids": session_ids, "created_accounts": created_accounts}


def main():
    password = os.environ.get("SAIV_DEMO_PASSWORD") or token_urlsafe(18)
    engine = create_engine(get_settings().database_url)
    try:
        with DatabaseSession(engine) as database, database.begin():
            acquire_migration_lock(database.connection())
            if database.scalar(select(Course.id).where(Course.code == "SC3099")):
                print("SC3099 already present; existing database preserved.")
                return
            result = seed_demo(database, password)
    finally:
        engine.dispose()
    print(f"SC3099 - Capstone Project: {result['course_id']}")
    print("Demo accounts: demo.admin@example.com, demo.instructor@example.com, demo.student@example.com")
    if result["created_accounts"]:
        print("Created: " + ", ".join(result["created_accounts"]))
        print(f"Initial password for newly created accounts: {password}")
    print("Existing passwords, consent, enrollments and sessions were preserved.")


if __name__ == "__main__":
    main()
