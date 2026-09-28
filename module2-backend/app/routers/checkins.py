"""Check-in submission, visibility, appeals, and review workflow."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.face_service import check_liveness, verify_face
from app.models import Checkin, Course, Device, Enrollment, Session as AttendanceSession, User, utc_now
from app.rate_limit import client_ip, enforce_checkin_limit
from app.risk import RiskDecision, assess_risk
from app.schemas import CheckinAppeal, CheckinCreate, CheckinListResponse, CheckinResponse, CheckinReview, CheckinStatus, UserRole, as_utc
from app.services.access import get_checkin, get_session, require_checkin_access, require_session_access
from app.services.checkins import checkin_query, serialize_checkin
from app.utils.geolocation import haversine_distance, ip_is_in_singapore, is_in_singapore

router = APIRouter(prefix="/checkins", tags=["checkins"])


def _reject(database: Session, request: Request, user: User, session_id: str, code: int, detail: str) -> None:
    write_audit_log(database, request, action="checkin_rejected", user_id=user.id,
                    resource_type="session", resource_id=session_id,
                    details={"reason": detail}, success=False)
    database.commit()
    raise HTTPException(status_code=code, detail=detail)


def _validate_eligibility(database: Session, session: AttendanceSession, user: User, payload: CheckinCreate) -> None:
    if session.status != "active":
        raise HTTPException(status_code=400, detail="session is not active")
    now = utc_now()
    if not as_utc(session.checkin_opens_at) <= now <= as_utc(session.checkin_closes_at):
        raise HTTPException(status_code=400, detail="check-in window is closed")
    course = database.get(Course, session.course_id)
    if course is None or not course.is_active:
        raise HTTPException(status_code=400, detail="course is inactive")
    enrolled = database.scalar(select(Enrollment.id).where(
        Enrollment.student_id == user.id, Enrollment.course_id == session.course_id,
        Enrollment.is_active.is_(True)))
    if enrolled is None:
        raise HTTPException(status_code=403, detail="active enrollment is required")
    if not user.geolocation_consent:
        raise HTTPException(status_code=403, detail="geolocation consent is required")
    if (session.require_liveness_check or session.require_face_match) and not user.camera_consent:
        raise HTTPException(status_code=403, detail="camera consent is required")
    if session.require_face_match and not (user.face_enrolled and user.face_embedding_hash):
        raise HTTPException(status_code=400, detail="face enrollment is required")
    if not is_in_singapore(payload.latitude, payload.longitude):
        raise HTTPException(status_code=403, detail="check-ins must be within Singapore")


async def _biometrics(session: AttendanceSession, user: User, payload: CheckinCreate) -> tuple:
    live_passed = live_score = face_passed = face_score = None
    if session.require_liveness_check and payload.liveness_challenge_response:
        result = await check_liveness(payload.liveness_challenge_response)
        live_passed, live_score = result.liveness_passed, result.liveness_score
    if session.require_face_match:
        if not payload.liveness_challenge_response:
            raise HTTPException(status_code=400, detail="face image is required")
        result = await verify_face(user.face_embedding_hash, payload.liveness_challenge_response)
        face_passed, face_score = result.match_passed, result.match_score
    return live_passed, live_score, face_passed, face_score


@router.post("/", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED)
async def create_checkin(payload: CheckinCreate, request: Request,
                         current_user: User = Depends(require_roles(UserRole.STUDENT)),
                         database: Session = Depends(get_db)) -> Checkin:
    enforce_checkin_limit(current_user.id)
    session = get_session(database, str(payload.session_id))
    write_audit_log(database, request, action="checkin_attempted", user_id=current_user.id,
                    resource_type="session", resource_id=session.id)
    try:
        _validate_eligibility(database, session, current_user, payload)
        if not ip_is_in_singapore(client_ip(request)):
            raise HTTPException(status_code=403, detail="check-ins require a Singapore or local IP address")
        if database.scalar(select(Checkin.id).where(Checkin.student_id == current_user.id,
                                                     Checkin.session_id == session.id)):
            raise HTTPException(status_code=400, detail="already checked in")
        database.commit()
        biometric = await _biometrics(session, current_user, payload)
    except HTTPException as exc:
        _reject(database, request, current_user, session.id, exc.status_code, str(exc.detail))

    session = get_session(database, session.id, lock=True)
    try:
        _validate_eligibility(database, session, current_user, payload)
        if database.scalar(select(Checkin.id).where(Checkin.student_id == current_user.id,
                                                     Checkin.session_id == session.id)):
            raise HTTPException(status_code=400, detail="already checked in")
    except HTTPException as exc:
        _reject(database, request, current_user, session.id, exc.status_code, str(exc.detail))

    device = database.scalar(select(Device).where(
        Device.user_id == current_user.id, Device.device_fingerprint == payload.device_fingerprint,
        Device.is_active.is_(True)).with_for_update())
    distance = haversine_distance(payload.latitude, payload.longitude,
                                  session.venue_latitude, session.venue_longitude)
    live_passed, live_score, face_passed, face_score = biometric
    if device is None and all(value is None for value in biometric):
        if distance <= session.geofence_radius_meters:
            legacy_status, legacy_score = "approved", 0.0
        elif distance <= 2 * session.geofence_radius_meters:
            legacy_status, legacy_score = "flagged", 0.5
        else:
            legacy_status, legacy_score = "rejected", 1.0
        decision = RiskDecision(
            score=legacy_score, status=legacy_status,
            factors=[] if legacy_score == 0 else [{"type": "geolocation", "severity": "high", "weight": .15}],
        )
    else:
        decision = assess_risk(
            distance=distance, radius=session.geofence_radius_meters,
            location_accuracy=payload.location_accuracy_meters,
            liveness_score=live_score, liveness_passed=live_passed,
            face_score=face_score, face_passed=face_passed,
            known_device=device is not None, trusted_device=bool(device and device.is_trusted),
            local_network=True, threshold=session.risk_threshold)
    now = utc_now()
    checkin = Checkin(
        session_id=session.id, student_id=current_user.id, device_id=device.id if device else None,
        checked_in_at=now, verified_at=now if decision.status == "approved" else None,
        scheduled_deletion_at=now + timedelta(days=30), latitude=payload.latitude,
        longitude=payload.longitude, location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance, status=decision.status, risk_score=decision.score,
        risk_factors=decision.factors, liveness_passed=live_passed, liveness_score=live_score,
        face_match_passed=face_passed, face_match_score=face_score)
    if device:
        device.last_seen_at = now
        device.total_checkins += 1
    database.add(checkin)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="already checked in") from None
    write_audit_log(database, request, action=f"checkin_{decision.status}", user_id=current_user.id,
                    resource_type="checkin", resource_id=checkin.id, device_id=checkin.device_id,
                    details={"risk_score": decision.score})
    database.commit()
    database.refresh(checkin)
    return checkin


@router.get("/", response_model=CheckinListResponse)
def list_checkins(
    session_id: UUID4 | None = None, course_id: UUID4 | None = None,
    student_id: UUID4 | None = None,
    status_filter: CheckinStatus | None = Query(default=None, alias="status"),
    min_risk_score: float | None = Query(default=None, ge=0, le=1),
    max_risk_score: float | None = Query(default=None, ge=0, le=1),
    start_date: datetime | None = None, end_date: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    database: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    query = checkin_query()
    if user.role == "instructor": query = query.where((Course.instructor_id == user.id) | (AttendanceSession.instructor_id == user.id))
    if session_id: query = query.where(Checkin.session_id == str(session_id))
    if course_id: query = query.where(Course.id == str(course_id))
    if student_id: query = query.where(Checkin.student_id == str(student_id))
    if status_filter: query = query.where(Checkin.status == status_filter.value)
    if min_risk_score is not None: query = query.where(Checkin.risk_score >= min_risk_score)
    if max_risk_score is not None: query = query.where(Checkin.risk_score <= max_risk_score)
    if start_date: query = query.where(Checkin.checked_in_at >= as_utc(start_date))
    if end_date: query = query.where(Checkin.checked_in_at <= as_utc(end_date))
    total = database.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = database.execute(query.order_by(Checkin.checked_in_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [serialize_checkin(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/my-checkins", response_model=list[CheckinResponse])
def my_checkins(course_id: UUID4 | None = None, limit: int = Query(default=50, ge=1, le=100),
                database: Session = Depends(get_db),
                user: User = Depends(require_roles(UserRole.STUDENT))):
    query = checkin_query().where(Checkin.student_id == user.id)
    if course_id: query = query.where(Course.id == str(course_id))
    return [serialize_checkin(row) for row in database.execute(query.order_by(Checkin.checked_in_at.desc()).limit(limit)).all()]


@router.get("/session/{session_id}", response_model=list[CheckinResponse])
def session_checkins(session_id: UUID4, database: Session = Depends(get_db),
                     user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN))):
    session = get_session(database, str(session_id))
    require_session_access(database, session, user)
    return [serialize_checkin(row) for row in database.execute(
        checkin_query().where(Checkin.session_id == session.id).order_by(Checkin.checked_in_at)).all()]


@router.get("/flagged", response_model=list[CheckinResponse])
def flagged_checkins(course_id: UUID4 | None = None, session_id: UUID4 | None = None,
                     limit: int = Query(default=50, ge=1, le=100),
                     database: Session = Depends(get_db),
                     user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN))):
    query = checkin_query().where(Checkin.status.in_(("flagged", "appealed")))
    if user.role == "instructor":
        query = query.where((Course.instructor_id == user.id) | (AttendanceSession.instructor_id == user.id))
    elif user.role == "ta":
        from app.models import CourseTA
        query = query.join(CourseTA, CourseTA.course_id == Course.id).where(CourseTA.ta_id == user.id)
    if course_id: query = query.where(Course.id == str(course_id))
    if session_id: query = query.where(Checkin.session_id == str(session_id))
    return [serialize_checkin(row) for row in database.execute(query.order_by(Checkin.checked_in_at).limit(limit)).all()]


@router.get("/{checkin_id}", response_model=CheckinResponse)
def checkin_detail(checkin_id: UUID4, database: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    checkin = get_checkin(database, str(checkin_id))
    require_checkin_access(database, checkin, user)
    return serialize_checkin(database.execute(checkin_query().where(Checkin.id == checkin.id)).one())


@router.post("/{id}/appeal", response_model=CheckinResponse)
def appeal_checkin(id: UUID4, payload: CheckinAppeal, request: Request,
                   database: Session = Depends(get_db),
                   user: User = Depends(require_roles(UserRole.STUDENT))):
    checkin = get_checkin(database, str(id), lock=True)
    if checkin.student_id != user.id:
        raise HTTPException(status_code=403, detail="only the check-in owner may appeal")
    if checkin.appealed_at is not None:
        raise HTTPException(status_code=400, detail="check-in has already been appealed")
    if checkin.status not in {"flagged", "rejected"}:
        raise HTTPException(status_code=400, detail="only flagged or rejected check-ins may be appealed")
    if utc_now() > as_utc(checkin.checked_in_at) + timedelta(days=7):
        raise HTTPException(status_code=400, detail="appeal window has expired")
    checkin.status, checkin.appeal_reason, checkin.appealed_at = "appealed", payload.appeal_reason, utc_now()
    write_audit_log(database, request, action="checkin_appealed", user_id=user.id,
                    resource_type="checkin", resource_id=checkin.id)
    database.commit()
    database.refresh(checkin)
    return checkin


@router.post("/{id}/review", response_model=CheckinResponse)
def review_checkin(id: UUID4, payload: CheckinReview, request: Request,
                   database: Session = Depends(get_db),
                   reviewer: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN))):
    checkin = get_checkin(database, str(id), lock=True)
    require_session_access(database, get_session(database, checkin.session_id), reviewer)
    if checkin.status not in {"flagged", "appealed"}:
        raise HTTPException(status_code=409, detail="check-in is no longer awaiting review")
    checkin.status, checkin.review_notes = payload.status, payload.review_notes
    checkin.reviewed_by_id, checkin.reviewed_at = reviewer.id, utc_now()
    checkin.verified_at = checkin.reviewed_at if payload.status == "approved" else None
    write_audit_log(database, request, action="checkin_reviewed", user_id=reviewer.id,
                    resource_type="checkin", resource_id=checkin.id,
                    details={"status": payload.status})
    database.commit()
    database.refresh(checkin)
    return checkin
