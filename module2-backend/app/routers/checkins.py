"""Week 3 GPS-only check-in skeleton; no camera or device processing."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_course_or_404, require_roles
from app.models import Checkin, Enrollment, User, utc_now
from app.routers.sessions import get_session_or_404
from app.schemas import CheckinCreate, CheckinResponse, UserRole, as_utc
from app.utils.geolocation import haversine_distance

router = APIRouter(prefix="/checkins", tags=["checkins"])


@router.post("/", response_model=CheckinResponse, status_code=201)
def create_checkin(payload: CheckinCreate, request: Request,
                   current_user: User = Depends(require_roles(UserRole.STUDENT)),
                   database: Session = Depends(get_db)):
    # Share the session lock with status updates so closing and check-in cannot race.
    session = get_session_or_404(database, str(payload.session_id), lock=True)
    write_audit_log(database, request, action="checkin_attempted", user_id=current_user.id,
                    resource_type="session", resource_id=session.id)

    def reject(code: int, detail: str):
        write_audit_log(database, request, action="checkin_rejected", user_id=current_user.id,
                        resource_type="session", resource_id=session.id,
                        details={"reason": detail}, success=False)
        database.commit()
        raise HTTPException(status_code=code, detail=detail)

    if session.status != "active":
        reject(400, "session is not active")
    now = utc_now()
    if not as_utc(session.checkin_opens_at) <= now <= as_utc(session.checkin_closes_at):
        reject(400, "check-in window is closed")
    if not get_course_or_404(database, session.course_id).is_active:
        reject(400, "course is inactive")
    enrollment = database.scalar(select(Enrollment).where(
        Enrollment.student_id == current_user.id, Enrollment.course_id == session.course_id,
        Enrollment.is_active.is_(True)))
    if enrollment is None:
        reject(403, "active enrollment is required")
    if database.scalar(select(Checkin.id).where(Checkin.student_id == current_user.id,
                                              Checkin.session_id == session.id)):
        reject(400, "already checked in")
    if not current_user.geolocation_consent:
        reject(403, "geolocation consent is required")
    if (session.require_liveness_check or session.require_face_match) and not current_user.camera_consent:
        reject(403, "camera consent is required")
    distance = haversine_distance(payload.latitude, payload.longitude,
                                  session.venue_latitude, session.venue_longitude)
    if distance <= session.geofence_radius_meters:
        checkin_status, risk_score = "approved", 0.0
    elif distance <= 2 * session.geofence_radius_meters:
        checkin_status, risk_score = "flagged", 0.5
    else:
        checkin_status, risk_score = "rejected", 1.0
    checkin = Checkin(session_id=session.id, student_id=current_user.id, checked_in_at=now,
                      latitude=payload.latitude, longitude=payload.longitude,
                      location_accuracy_meters=payload.location_accuracy_meters,
                      distance_from_venue_meters=distance, status=checkin_status, risk_score=risk_score)
    database.add(checkin)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=400, detail="already checked in") from None
    write_audit_log(database, request, action=f"checkin_{checkin_status}", user_id=current_user.id,
                    resource_type="checkin", resource_id=checkin.id)
    database.commit()
    database.refresh(checkin)
    return checkin
