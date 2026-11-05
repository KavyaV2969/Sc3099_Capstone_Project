"""Seed data is usable through the API, repeatable, and never resets real records."""
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import AuditLog, Checkin, Course, Enrollment, Session, User, utc_now
from app.schemas import as_utc
from app.security import verify_password
from scripts import seed_demo
from test_week3 import api

NOW = utc_now()


def test_seed_is_usable_and_repeatable_without_resets(api, monkeypatch):
    monkeypatch.setattr(seed_demo, "utc_now", lambda: NOW)
    with api.database() as db, db.begin():
        first = seed_demo.seed_demo(db, "DemoPassword123!")
    with api.database() as db:
        course = db.get(Course, first["course_id"])
        assert (course.code, course.name) == ("SC3099", "Capstone Project")
        student = db.scalar(select(User).where(User.email == "demo.student@example.com"))
        assert verify_password("DemoPassword123!", student.hashed_password)
        assert not student.camera_consent and not student.face_enrolled
        enrollment = db.scalar(select(Enrollment).where(Enrollment.course_id == course.id))
        assert enrollment.student_id == student.id and enrollment.is_active
        lecture, lab = [db.get(Session, sid) for sid in first["session_ids"]]
        assert lecture.status == "active" and lecture.attendance_roster == [student.id]
        assert as_utc(lecture.checkin_opens_at) < NOW < as_utc(lecture.checkin_closes_at)
        assert lab.status == "scheduled" and as_utc(lab.scheduled_start) > NOW
        assert lecture.require_liveness_check and lecture.require_face_match
        assert db.scalar(select(func.count(Checkin.id))) == 0
        audit_count = db.scalar(select(func.count(AuditLog.id)))
        assert audit_count == 7
        lecture.status = "closed"
        enrollment.is_active = False
        student.camera_consent = True
        db.commit()
        old_password = student.hashed_password
    with api.database() as db, db.begin():
        second = seed_demo.seed_demo(db, "DifferentPassword123!")
        assert second["course_id"] == first["course_id"]
        assert second["session_ids"] == first["session_ids"]
        assert second["created_accounts"] == []
        assert db.get(Session, first["session_ids"][0]).status == "closed"
        student = db.scalar(select(User).where(User.email == "demo.student@example.com"))
        assert student.hashed_password == old_password and student.camera_consent
        assert db.scalar(select(Enrollment.is_active)) is False
        assert db.scalar(select(func.count(AuditLog.id))) == audit_count
    courses = api.request("GET", "/courses/", "student").json()["items"]
    assert any(row["code"] == "SC3099" and row["name"] == "Capstone Project" for row in courses)


def test_course_conflict_rolls_back_all_new_records(api):
    with api.database() as db, db.begin():
        db.add(Course(code="SC3099", name="Existing Course", semester="AY26"))
    with pytest.raises(ValueError, match="SC3099 already exists"):
        with api.database() as db, db.begin():
            seed_demo.seed_demo(db, "DemoPassword123!")
    with api.database() as db:
        assert db.scalar(select(Course.name)) == "Existing Course"
        assert db.scalar(select(func.count(User.id)).where(User.email.like("demo.%"))) == 0
        assert db.scalar(select(func.count(AuditLog.id))) == 0


@pytest.mark.parametrize("conflict", ["role", "inactive"])
def test_account_conflicts_do_not_reset_accounts(api, conflict):
    with api.database() as db, db.begin():
        db.add(User(email="demo.instructor@example.com", full_name="Existing", hashed_password="unchanged",
                    role="student" if conflict == "role" else "instructor", is_active=conflict != "inactive"))
    with pytest.raises(ValueError, match="Demo account conflict"):
        with api.database() as db, db.begin():
            seed_demo.seed_demo(db, "DemoPassword123!")
    with api.database() as db:
        assert db.scalar(select(User.hashed_password).where(User.email == "demo.instructor@example.com")) == "unchanged"
        assert db.scalar(select(func.count(Course.id))) == 0
        assert db.scalar(select(User.id).where(User.email == "demo.admin@example.com")) is None


def test_seed_password_uses_existing_validation(api):
    with pytest.raises(ValidationError):
        with api.database() as db, db.begin():
            seed_demo.seed_demo(db, "short")
    with api.database() as db:
        assert db.scalar(select(func.count(User.id)).where(User.email.like("demo.%"))) == 0
