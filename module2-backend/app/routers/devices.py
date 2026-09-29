"""Owner-scoped device registration and administration."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query, status
from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Device, User, utc_now
from app.schemas import CheckinCreate, DeviceRegister, DeviceResponse, DeviceUpdate, UserRole
from app.services.devices import canonical_key, parse_key, issue_challenge
from app.services.access import get_session
from app.rate_limit import enforce_limit

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
@router.post("/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceRegister,
    request: Request,
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    key = canonical_key(payload.public_key) if payload.public_key is not None else None
    try:
        device = database.scalar(
            select(Device).where(Device.device_fingerprint == payload.device_fingerprint).with_for_update()
        )
        if device is not None and device.user_id != user.id:
            raise HTTPException(status_code=400, detail="device already registered")
        if device is None:
            device = Device(user_id=user.id, **{**payload.model_dump(), "public_key": key})
            database.add(device)
        else:
            if device.revoked_at is not None:
                raise HTTPException(status_code=403, detail="device is administratively revoked")
            if "public_key" not in payload.model_fields_set:
                key = device.public_key
            if device.public_key != key:
                device.is_trusted, device.trust_score = False, "low"
            device.device_name = payload.device_name
            device.platform = payload.platform
            device.public_key = key
            device.is_active = True
        device.last_seen_at = utc_now()
        database.flush()
        write_audit_log(
            database, request, action="device_registered", user_id=user.id,
            resource_type="device", resource_id=device.id, device_id=device.id,
        )
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=400, detail="device already registered") from exc
    database.refresh(device)
    return device


@router.get("/my-devices", response_model=list[DeviceResponse])
def my_devices(
    limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Device]:
    return list(database.scalars(
        select(Device).where(Device.user_id == user.id).order_by(Device.first_seen_at.desc(), Device.id)
        .limit(limit).offset(offset)
    ))


@router.get("/")
def list_devices(
    limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    database: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    total = database.scalar(select(func.count()).select_from(Device)) or 0
    devices = database.scalars(select(Device).order_by(Device.first_seen_at.desc(), Device.id)
                               .limit(limit).offset(offset))
    return {"items": [DeviceResponse.model_validate(device) for device in devices],
            "total": total, "limit": limit, "offset": offset}


def _owned_or_admin(database: Session, device_id: UUID4, user: User, *, lock: bool = False) -> Device:
    statement = select(Device).where(Device.id == str(device_id))
    if lock:
        statement = statement.with_for_update()
    device = database.scalar(statement)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if user.role != "admin" and device.user_id != user.id:
        raise HTTPException(status_code=403, detail="insufficient permissions")
    return device


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: UUID4,
    payload: DeviceUpdate,
    request: Request,
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    device = _owned_or_admin(database, device_id, user, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    if "is_trusted" in changes and user.role != "admin":
        raise HTTPException(status_code=403, detail="only administrators may change device trust")
    if user.role != "admin" and device.revoked_at is not None:
        raise HTTPException(status_code=403, detail="device is administratively revoked")
    if changes.get("is_active") is False:
        device.is_trusted, device.trust_score = False, "low"
        if user.role == "admin":
            device.revoked_at = utc_now()
    elif changes.get("is_active") is True and user.role == "admin":
        device.revoked_at = None
    if changes.get("is_trusted") is True:
        parse_key(device.public_key or "")
        if device.revoked_at is not None or changes.get("is_active", device.is_active) is False:
            raise HTTPException(status_code=400, detail="inactive or revoked devices cannot be trusted")
    for field, value in changes.items():
        setattr(device, field, value)
    if "is_trusted" in changes:
        device.trust_score = "high" if device.is_trusted else "low"
    write_audit_log(
        database, request, action="device_updated", user_id=user.id,
        resource_type="device", resource_id=device.id, device_id=device.id,
        details={"fields": sorted(changes)},
    )
    database.commit()
    database.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_device(
    device_id: UUID4,
    request: Request,
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    device = _owned_or_admin(database, device_id, user, lock=True)
    device.is_active = False
    device.is_trusted, device.trust_score = False, "low"
    if user.role == "admin":
        device.revoked_at = utc_now()
    write_audit_log(
        database, request, action="device_deactivated", user_id=user.id,
        resource_type="device", resource_id=device.id, device_id=device.id,
    )
    database.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{device_id}/challenge")
def challenge(device_id: UUID4, payload: CheckinCreate,
              database: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Reuse attendance prerequisites; issuing a challenge creates no attendance.
    from app.routers.checkins import _validate_eligibility
    device = _owned_or_admin(database, device_id, user)
    if (device.user_id != user.id or not device.is_active or device.revoked_at is not None
        or device.device_fingerprint != payload.device_fingerprint):
        raise HTTPException(status_code=403, detail="device is unavailable")
    if payload.device_challenge_id or payload.device_signature:
        raise HTTPException(status_code=400, detail="challenge input must be unsigned")
    session = get_session(database, str(payload.session_id))
    _validate_eligibility(database, session, user, payload)
    enforce_limit(key="rate:device-proof:" + user.id, limit=20, window_seconds=60)
    result = issue_challenge(device, payload, user.id)
    database.commit()
    return result
