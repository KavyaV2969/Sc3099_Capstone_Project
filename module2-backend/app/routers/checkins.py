"""Check-in submission, visibility, appeals, and review workflow."""

from datetime import datetime, timedelta
from dataclasses import dataclass, replace
from types import SimpleNamespace
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.face_service import check_liveness, verify_face
from app.models import Checkin, Course, Device, Enrollment, Session as AttendanceSession, User, utc_now
from app.rate_limit import client_ip, enforce_checkin_limit
from app.risk import POLICY, assess_risk
from app.metrics import checkin_attempts, checkin_success, checkin_outcomes
from app.schemas import CheckinAppeal, CheckinCreate, CheckinListResponse, CheckinResponse, CheckinReview, CheckinStatus, UserRole, as_utc
from app.services.access import accessible_course_ids, get_checkin, get_session, require_checkin_access, require_session_access
from app.services.checkins import checkin_query, serialize_checkin
from app.services.devices import verify_proof, consume_proof
from app.utils.geolocation import haversine_distance, ip_is_in_singapore, is_in_singapore

router = APIRouter(prefix="/checkins", tags=["checkins"])


def _reject(database: Session, request: Request, user_id: str, session_id: str, code: int, detail: str,
            headers: dict | None = None) -> None:
    write_audit_log(database, request, action="checkin_rejected", user_id=user_id,
                    resource_type="session", resource_id=session_id,
                    details={"reason": detail}, success=False)
    database.commit()
    raise HTTPException(status_code=code, detail=detail, headers=headers)


def _validate_eligibility(database: Session, session: AttendanceSession, user: User, payload: CheckinCreate) -> bool:
    if not user.is_active:
        raise HTTPException(status_code=401, detail="account is unavailable")
    if user.role != "student":
        raise HTTPException(status_code=403, detail="insufficient permissions")
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
    if session.require_face_match and not user.camera_consent:
        raise HTTPException(status_code=403, detail="camera consent is required")
    if session.require_face_match and not (user.face_enrolled and user.face_embedding_hash):
        raise HTTPException(status_code=400, detail="face enrollment is required")
    if session.require_face_match and not (
        payload.liveness_challenge_response and payload.liveness_challenge_response.strip()
    ):
        raise HTTPException(status_code=400, detail="face image is required")
    if not is_in_singapore(payload.latitude, payload.longitude):
        raise HTTPException(status_code=403, detail="check-ins must be within Singapore")
    return bool(session.require_liveness_check and user.camera_consent
                and payload.liveness_challenge_response and payload.liveness_challenge_response.strip())


@dataclass(frozen=True)
class VerificationPolicy:
    user_id: str
    session_id: str
    course_id: str
    require_liveness: bool
    require_face: bool
    reference_hash: str | None
    proof_content: str | None = None


async def _biometrics(policy: VerificationPolicy, payload: CheckinCreate) -> tuple:
    live_passed = live_score = face_passed = face_score = None
    if policy.require_liveness:
        result = await check_liveness(payload.liveness_challenge_response)
        live_passed, live_score = result.liveness_passed, result.liveness_score
    if policy.require_face:
        result = await verify_face(policy.reference_hash, payload.liveness_challenge_response)
        face_passed, face_score = result.match_passed, result.match_score
    return live_passed, live_score, face_passed, face_score


def _locked(database: Session, model, *conditions):
    """Refresh the identity map as well as acquiring a PostgreSQL row lock."""
    return database.scalar(select(model).where(*conditions).with_for_update()
                           .execution_options(populate_existing=True))


def _prepare(payload: CheckinCreate, request: Request, current_user: User,
             database: Session) -> VerificationPolicy:
    checkin_attempts.inc()
    user_id = current_user.id
    session_id = str(payload.session_id)
    write_audit_log(database, request, action="checkin_attempted", user_id=current_user.id,
                    resource_type="session", resource_id=session_id,
                    details={"student_id": user_id, "session_id": session_id,
                             "location": {"latitude": round(payload.latitude, 4),
                                          "longitude": round(payload.longitude, 4)}})
    try:
        enforce_checkin_limit(current_user.id)
        session = get_session(database, session_id)
        evaluate_liveness = _validate_eligibility(database, session, current_user, payload)
        if database.scalar(select(Checkin.id).where(Checkin.student_id == current_user.id,
                                                     Checkin.session_id == session.id)):
            raise HTTPException(status_code=400, detail="already checked in")
        policy = VerificationPolicy(user_id, session_id, session.course_id,
                                    evaluate_liveness, session.require_face_match,
                                    current_user.face_embedding_hash if session.require_face_match else None)
        device = database.scalar(select(Device).where(Device.user_id == user_id,
            Device.device_fingerprint == payload.device_fingerprint, Device.is_active.is_(True)))
        device_values = SimpleNamespace(id=device.id, public_key=device.public_key,
            revoked_at=device.revoked_at, is_active=device.is_active) if device else None
        database.commit()
        # Slow network/cache work runs without an open ORM transaction.
        if not ip_is_in_singapore(client_ip(request)):
            raise HTTPException(status_code=403, detail="check-ins require a Singapore or local IP address")
        return replace(policy, proof_content=verify_proof(device_values, payload, user_id))
    except HTTPException as exc:
        _reject(database, request, user_id, session_id, exc.status_code, str(exc.detail), exc.headers)


def _finalize(policy: VerificationPolicy, biometric: tuple, payload: CheckinCreate,
              request: Request, database: Session) -> Checkin:
    user_id, session_id = policy.user_id, policy.session_id
    try:
        # Global order for finalization: user, course, session, enrollment, device.
        current_user = _locked(database, User, User.id == user_id)
        if current_user is None or not current_user.is_active:
            raise HTTPException(status_code=401, detail="account is unavailable")
        if current_user.role != "student":
            raise HTTPException(status_code=403, detail="insufficient permissions")
        course = _locked(database, Course, Course.id == policy.course_id)
        session = _locked(database, AttendanceSession, AttendanceSession.id == session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if (session.course_id != policy.course_id
            or session.require_face_match != policy.require_face
            or (policy.require_face and current_user.face_embedding_hash != policy.reference_hash)):
            raise HTTPException(status_code=409, detail="verification policy changed; submit a new check-in")
        if course is None or not course.is_active:
            raise HTTPException(status_code=400, detail="course is inactive")
        enrollment = _locked(database, Enrollment, Enrollment.student_id == user_id,
                             Enrollment.course_id == policy.course_id)
        if enrollment is None or not enrollment.is_active:
            raise HTTPException(status_code=403, detail="active enrollment is required")
        evaluate_liveness = _validate_eligibility(database, session, current_user, payload)
        if evaluate_liveness != policy.require_liveness:
            raise HTTPException(status_code=409, detail="verification policy changed; submit a new check-in")
        if database.scalar(select(Checkin.id).where(Checkin.student_id == current_user.id,
                                                     Checkin.session_id == session.id)):
            raise HTTPException(status_code=400, detail="already checked in")
    except HTTPException as exc:
        _reject(database, request, user_id, session_id, exc.status_code, str(exc.detail))

    device = _locked(database, Device,
        Device.user_id == current_user.id, Device.device_fingerprint == payload.device_fingerprint,
        Device.is_active.is_(True))
    try:
        proof = verify_proof(device, payload, user_id)
        if proof != policy.proof_content:
            raise HTTPException(status_code=409, detail="device proof changed; submit a new check-in")
    except HTTPException as exc:
        _reject(database, request, user_id, session_id, exc.status_code, str(exc.detail))
    distance = haversine_distance(payload.latitude, payload.longitude,
                                  session.venue_latitude, session.venue_longitude)
    live_passed, live_score, face_passed, face_score = biometric
    network_hint = bool(re.search(r"\b(?:vpn|proxy|tunnel|tor)\b",
                       request.headers.get("user-agent", ""), re.IGNORECASE))
    previous = database.scalar(select(Checkin).where(Checkin.student_id == user_id,
        Checkin.status == "approved", Checkin.scheduled_deletion_at > utc_now())
        .order_by(Checkin.checked_in_at.desc()).limit(1))
    travel = False
    if previous and previous.location_accuracy_meters is not None and payload.location_accuracy_meters is not None:
        displacement = haversine_distance(payload.latitude, payload.longitude, previous.latitude, previous.longitude)
        elapsed = (utc_now() - as_utc(previous.checked_in_at)).total_seconds()
        certain_distance = max(0, displacement - previous.location_accuracy_meters - payload.location_accuracy_meters)
        travel = displacement >= 1000 and (elapsed <= 0 or certain_distance / elapsed > 100)
    try:
        decision = assess_risk(
            distance=distance, radius=session.geofence_radius_meters,
            location_accuracy=payload.location_accuracy_meters,
            liveness_score=live_score, liveness_passed=live_passed,
            face_score=face_score, face_passed=face_passed,
            require_liveness=policy.require_liveness, require_face=policy.require_face,
            known_device=proof is not None, trusted_device=bool(proof and device.is_trusted),
            local_network=True, network_risk=.8 if network_hint else 0,
            impossible_travel=travel, threshold=session.risk_threshold)
    except ValueError:
        _reject(database, request, user_id, session_id, 503, "verification evidence unavailable")
    now = utc_now()
    checkin = Checkin(
        session_id=session.id, student_id=current_user.id, device_id=device.id if device else None,
        checked_in_at=now, verified_at=now if decision.status == "approved" else None,
        scheduled_deletion_at=now + timedelta(days=30), latitude=round(payload.latitude, 4),
        longitude=round(payload.longitude, 4), location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance, status=decision.status, risk_score=decision.score,
        risk_factors=decision.factors, liveness_passed=live_passed, liveness_score=live_score,
        face_match_passed=face_passed, face_match_score=face_score)
    if device:
        device.last_seen_at = now
        device.total_checkins += 1
    database.add(checkin)
    try:
        consume_proof(payload, proof)
        database.flush()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="already checked in") from None
    except HTTPException as exc:
        database.rollback()
        _reject(database, request, user_id, session_id, exc.status_code, str(exc.detail))
    write_audit_log(database, request, action=f"checkin_{decision.status}", user_id=current_user.id,
                    resource_type="checkin", resource_id=checkin.id, device_id=checkin.device_id,
                    details={"risk_score": decision.score, "policy": POLICY,
                             "risk_threshold": session.risk_threshold,
                             "require_liveness_check": policy.require_liveness,
                             "require_face_match": policy.require_face,
                             "contributions": decision.contributions,
                             "network_detection": "user_agent_hint" if network_hint else "unavailable",
                             "device_proof": bool(proof),
                             "reason": [factor["type"] for factor in decision.factors
                                        if factor["critical"] or factor["type"] == "impossible_travel"],
                             "reviewer_id": None},
                    success=decision.status != "rejected")
    database.commit()
    database.refresh(checkin)
    checkin_outcomes.labels(checkin.status).inc()
    if checkin.status == "approved":
        checkin_success.inc()
    return checkin


@router.post("/", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED)
async def create_checkin(payload: CheckinCreate, request: Request,
                         current_user: User = Depends(require_roles(UserRole.STUDENT)),
                         database: Session = Depends(get_db)) -> Checkin:
    policy = await run_in_threadpool(_prepare, payload, request, current_user, database)
    try:
        biometric = await _biometrics(policy, payload)
    except HTTPException as exc:
        await run_in_threadpool(_reject, database, request, policy.user_id, policy.session_id,
                                exc.status_code, str(exc.detail))
    return await run_in_threadpool(_finalize, policy, biometric, payload, request, database)


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
    if user.role == "instructor": query = query.where(Course.id.in_(accessible_course_ids(user, read_only=True)))
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
                offset: int = Query(0, ge=0),
                database: Session = Depends(get_db),
                user: User = Depends(require_roles(UserRole.STUDENT))):
    query = checkin_query().where(Checkin.student_id == user.id)
    if course_id: query = query.where(Course.id == str(course_id))
    return [serialize_checkin(row) for row in database.execute(query.order_by(Checkin.checked_in_at.desc(), Checkin.id).limit(limit).offset(offset)).all()]


@router.get("/session/{session_id}", response_model=list[CheckinResponse])
def session_checkins(session_id: UUID4, limit: int = Query(100, ge=1, le=100),
                     offset: int = Query(0, ge=0), database: Session = Depends(get_db),
                     user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN))):
    session = get_session(database, str(session_id))
    require_session_access(database, session, user, read_only=True)
    return [serialize_checkin(row) for row in database.execute(
        checkin_query().where(Checkin.session_id == session.id).order_by(Checkin.checked_in_at, Checkin.id)
        .limit(limit).offset(offset)).all()]


@router.get("/flagged", response_model=CheckinListResponse)
def flagged_checkins(course_id: UUID4 | None = None, session_id: UUID4 | None = None,
                     limit: int = Query(default=50, ge=1, le=100),
                     offset: int = Query(0, ge=0),
                     database: Session = Depends(get_db),
                     user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.TA, UserRole.ADMIN))):
    query = checkin_query().where(Checkin.status.in_(("flagged", "appealed")))
    if user.role == "instructor":
        query = query.where(Course.id.in_(accessible_course_ids(user, read_only=True)))
    elif user.role == "ta":
        from app.models import CourseTA
        query = query.join(CourseTA, CourseTA.course_id == Course.id).where(CourseTA.ta_id == user.id)
    if course_id: query = query.where(Course.id == str(course_id))
    if session_id: query = query.where(Checkin.session_id == str(session_id))
    total = database.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = database.execute(query.order_by(Checkin.checked_in_at, Checkin.id).limit(limit).offset(offset)).all()
    return {"items": [serialize_checkin(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{checkin_id}", response_model=CheckinResponse)
def checkin_detail(checkin_id: UUID4, database: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    checkin = get_checkin(database, str(checkin_id))
    require_checkin_access(database, checkin, user, read_only=True)
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
    write_audit_log(database, request, action=f"checkin_{payload.status}", user_id=reviewer.id,
                    resource_type="checkin", resource_id=checkin.id,
                    details={"checkin_id": checkin.id, "reviewer_id": reviewer.id,
                             "reason": payload.review_notes, "method": "manual"},
                    success=payload.status == "approved")
    database.commit()
    database.refresh(checkin)
    return checkin
