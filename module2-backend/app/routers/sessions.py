"""Course sessions with an explicit, forward-only status workflow."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DatabaseSession

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, get_course_or_404, require_roles
from app.models import Checkin, Course, CourseTA, Enrollment, Session, User, utc_now
from app.schemas import (SessionCreate, SessionListResponse, SessionResponse, SessionStatus,
                         SessionUpdate, UserRole, as_utc)
from app.services.access import get_session as get_session_record

router = APIRouter(prefix="/sessions", tags=["sessions"])
TRANSITIONS = {"scheduled": {"active", "cancelled"}, "active": {"closed", "cancelled"},
               "closed": {"cancelled"}, "cancelled": set()}


def session_query():
    enrolled = select(func.count(Enrollment.id)).where(
        Enrollment.course_id == Session.course_id, Enrollment.is_active.is_(True)
    ).correlate(Session).scalar_subquery()
    checked_in = select(func.count(Checkin.id)).where(
        Checkin.session_id == Session.id
    ).correlate(Session).scalar_subquery()
    return select(Session, Course, enrolled, checked_in).join(Course, Session.course_id == Course.id)


def session_response(row) -> SessionResponse:
    session, course, enrolled, checked_in = row
    result = SessionResponse.model_validate(session)
    result.course_code, result.course_name = course.code, course.name
    result.total_enrolled, result.checked_in_count = enrolled, checked_in
    return result


def require_session_owner(session: Session, user: User) -> None:
    if user.role != "admin" and session.instructor_id != user.id:
        raise HTTPException(status_code=403, detail="session belongs to another instructor")


def validate_times(session: Session, *, require_future: bool = False) -> None:
    if require_future and as_utc(session.scheduled_start) <= utc_now():
        raise HTTPException(status_code=422, detail="scheduled_start must be in the future")
    if as_utc(session.scheduled_end) <= as_utc(session.scheduled_start):
        raise HTTPException(status_code=422, detail="scheduled_end must be after scheduled_start")
    if as_utc(session.checkin_closes_at) <= as_utc(session.checkin_opens_at):
        raise HTTPException(status_code=422, detail="checkin_closes_at must be after checkin_opens_at")


@router.get("/", response_model=SessionListResponse)
def list_sessions(
    status: SessionStatus | None = None, course_id: UUID4 | None = None,
    instructor_id: UUID4 | None = None, start_date: datetime | None = None,
    end_date: datetime | None = None, limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
    database: DatabaseSession = Depends(get_db),
):
    query = session_query()
    if current_user.role == "instructor":
        query = query.where(Session.instructor_id == current_user.id)
    if status is not None:
        query = query.where(Session.status == status.value)
    if course_id is not None:
        query = query.where(Session.course_id == str(course_id))
    if instructor_id is not None:
        query = query.where(Session.instructor_id == str(instructor_id))
    if start_date is not None:
        query = query.where(Session.scheduled_start >= as_utc(start_date))
    if end_date is not None:
        query = query.where(Session.scheduled_start <= as_utc(end_date))
    total = database.scalar(select(func.count()).select_from(query.subquery()))
    rows = database.execute(query.order_by(Session.scheduled_start, Session.id).offset(offset).limit(limit)).all()
    return {"items": [session_response(row) for row in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/active", response_model=list[SessionResponse])
def active_sessions(database: DatabaseSession = Depends(get_db)):
    now = utc_now()
    rows = database.execute(session_query().where(
        Session.status == "active", Session.checkin_opens_at <= now,
        Session.checkin_closes_at >= now, Course.is_active.is_(True)
    ).order_by(Session.scheduled_start, Session.id)).all()
    return [session_response(row) for row in rows]


@router.get("/my-sessions", response_model=list[SessionResponse])
def my_sessions(status: SessionStatus | None = None, upcoming: bool = False,
                limit: int = Query(50, ge=1, le=200),
                current_user: User = Depends(get_current_user),
                database: DatabaseSession = Depends(get_db)):
    query = session_query().where(Course.is_active.is_(True))
    if current_user.role == "student":
        query = query.where(Session.course_id.in_(select(Enrollment.course_id).where(
            Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True))))
    elif current_user.role == "instructor":
        query = query.where(Session.instructor_id == current_user.id)
    elif current_user.role == "ta":
        query = query.where(Session.course_id.in_(select(CourseTA.course_id).where(CourseTA.ta_id == current_user.id)))
    if status is not None:
        query = query.where(Session.status == status.value)
    if upcoming:
        query = query.where(Session.scheduled_start > utc_now())
    rows = database.execute(query.order_by(Session.scheduled_start, Session.id).limit(limit)).all()
    return [session_response(row) for row in rows]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID4, current_user: User = Depends(get_current_user),
                database: DatabaseSession = Depends(get_db)):
    row = database.execute(session_query().where(Session.id == str(session_id))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_response(row)


@router.post("/", response_model=SessionResponse, status_code=201)
def create_session(payload: SessionCreate, request: Request,
                   current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
                   database: DatabaseSession = Depends(get_db)):
    course = get_course_or_404(database, str(payload.course_id))
    if current_user.role != "admin" and course.instructor_id is not None and course.instructor_id != current_user.id:
        raise HTTPException(status_code=403, detail="course belongs to another instructor")
    if not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    values = payload.model_dump(exclude_none=True)
    values["course_id"] = course.id
    for field in ("venue_name", "venue_latitude", "venue_longitude", "geofence_radius_meters", "risk_threshold"):
        values.setdefault(field, getattr(course, field))
    if values["venue_latitude"] is None or values["venue_longitude"] is None:
        raise HTTPException(status_code=422, detail="session or course must specify venue coordinates")
    values.setdefault("checkin_opens_at", payload.scheduled_start - timedelta(minutes=15))
    values.setdefault("checkin_closes_at", payload.scheduled_start + timedelta(minutes=30))
    instructor_id = course.instructor_id if current_user.role == "admin" and course.instructor_id else current_user.id
    session = Session(**values, instructor_id=instructor_id, status="scheduled")
    validate_times(session, require_future=True)
    database.add(session)
    database.flush()
    write_audit_log(database, request, action="session_created", user_id=current_user.id,
                    resource_type="session", resource_id=session.id)
    database.commit()
    return session_response(database.execute(session_query().where(Session.id == session.id)).one())


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(session_id: UUID4, payload: SessionUpdate, request: Request,
                   current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
                   database: DatabaseSession = Depends(get_db)):
    session = get_session_record(database, str(session_id), lock=True)
    require_session_owner(session, current_user)
    changes = payload.model_dump(exclude_unset=True)
    new_status = changes.get("status", session.status)
    if new_status != session.status and new_status not in TRANSITIONS[session.status]:
        raise HTTPException(status_code=400, detail="invalid session status transition")
    if new_status == "active" and not get_course_or_404(database, session.course_id).is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    for field, value in changes.items():
        setattr(session, field, value)
    validate_times(session, require_future="scheduled_start" in changes)
    write_audit_log(database, request, action="session_updated", user_id=current_user.id,
                    resource_type="session", resource_id=session.id)
    database.commit()
    return session_response(database.execute(session_query().where(Session.id == session.id)).one())


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: UUID4, request: Request,
                   current_user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)),
                   database: DatabaseSession = Depends(get_db)):
    session = get_session_record(database, str(session_id), lock=True)
    require_session_owner(session, current_user)
    if session.status != "scheduled":
        raise HTTPException(status_code=400, detail="only scheduled sessions can be deleted")
    write_audit_log(database, request, action="session_deleted", user_id=current_user.id,
                    resource_type="session", resource_id=session.id)
    database.delete(session)
    database.commit()
    return Response(status_code=204)
