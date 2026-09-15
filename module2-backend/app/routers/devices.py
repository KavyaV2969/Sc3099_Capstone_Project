"""Owner-scoped device registration and administration."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import get_current_user
from app.models import Device, User
from app.schemas import DeviceRegister, DeviceResponse, DeviceUpdate

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceRegister,
    request: Request,
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    device = database.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == payload.device_fingerprint,
        ).with_for_update()
    )
    if device is None:
        device = Device(user_id=user.id, **payload.model_dump())
        database.add(device)
    else:
        device.device_name = payload.device_name
        device.platform = payload.platform
        device.public_key = payload.public_key
        device.is_active = True
    write_audit_log(
        database, request, action="device_registered", user_id=user.id,
        resource_type="device", resource_id=device.id, device_id=device.id,
    )
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=400, detail="device already registered") from exc
    database.refresh(device)
    return device


@router.get("/my-devices", response_model=list[DeviceResponse])
def my_devices(
    database: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Device]:
    return list(database.scalars(
        select(Device).where(Device.user_id == user.id).order_by(Device.first_seen_at.desc())
    ))


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
    if changes.get("is_trusted") is True and not device.public_key:
        raise HTTPException(status_code=400, detail="a public key is required before trusting a device")
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
    write_audit_log(
        database, request, action="device_deactivated", user_id=user.id,
        resource_type="device", resource_id=device.id, device_id=device.id,
    )
    database.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
