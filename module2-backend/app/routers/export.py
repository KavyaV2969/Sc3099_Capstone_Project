"""Ownership-checked course and session attendance exports."""

import csv
import io
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import require_roles
from app.models import Checkin, Session as AttendanceSession, User
from app.responses import SafeJSONResponse
from app.schemas import ExportFormat, UserRole, as_utc
from app.services.access import get_course, get_session, require_course_access, require_session_access

router = APIRouter(prefix="/export", tags=["export"])
HEADERS = ["student_id", "student_name", "student_email", "session_date", "session_name", "status", "checked_in_at", "risk_score"]


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_") or "attendance"


def _response(rows: list[dict], export_format: ExportFormat, filename: str):
    if export_format is ExportFormat.JSON:
        return SafeJSONResponse(content=json.loads(json.dumps(rows, default=str)), headers={
            "Content-Disposition": f'attachment; filename="{filename}.json"'})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=HEADERS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}.csv"'})


def _rows(database: Session, *, course_id: str | None = None, session_id: str | None = None,
          start_date: datetime | None = None, end_date: datetime | None = None) -> list[dict]:
    query = (select(Checkin.student_id, User.full_name, User.email, AttendanceSession.scheduled_start,
                    AttendanceSession.name, Checkin.status, Checkin.checked_in_at, Checkin.risk_score)
             .join(User, User.id == Checkin.student_id)
             .join(AttendanceSession, AttendanceSession.id == Checkin.session_id))
    if course_id: query = query.where(AttendanceSession.course_id == course_id)
    if session_id: query = query.where(AttendanceSession.id == session_id)
    if start_date: query = query.where(AttendanceSession.scheduled_start >= as_utc(start_date))
    if end_date: query = query.where(AttendanceSession.scheduled_start <= as_utc(end_date))
    return [{"student_id": sid, "student_name": name, "student_email": email,
             "session_date": scheduled.date(), "session_name": session_name, "status": status,
             "checked_in_at": checked, "risk_score": risk}
            for sid, name, email, scheduled, session_name, status, checked, risk
            in database.execute(query.order_by(AttendanceSession.scheduled_start, User.full_name)).all()]


@router.get("/attendance/{course_id}")
def export_course(course_id: UUID4, request: Request, format: ExportFormat = ExportFormat.CSV,
                  start_date: datetime | None = None, end_date: datetime | None = None,
                  database: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    course = get_course(database, str(course_id))
    require_course_access(database, course, user, allow_ta=False)
    rows = _rows(database, course_id=course.id, start_date=start_date, end_date=end_date)
    write_audit_log(database, request, action="data_exported", user_id=user.id,
                    resource_type="course", resource_id=course.id,
                    details={"format": format.value, "rows": len(rows)})
    database.commit()
    return _response(rows, format, _safe(f"{course.code}-attendance"))


@router.get("/session/{session_id}")
def export_session(session_id: UUID4, request: Request, format: ExportFormat = ExportFormat.CSV,
                   database: Session = Depends(get_db),
                   user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    session = get_session(database, str(session_id))
    course = require_session_access(database, session, user, allow_ta=False)
    rows = _rows(database, session_id=session.id)
    write_audit_log(database, request, action="data_exported", user_id=user.id,
                    resource_type="session", resource_id=session.id,
                    details={"format": format.value, "rows": len(rows)})
    database.commit()
    if format is ExportFormat.JSON:
        approved = sum(row["status"] == "approved" for row in rows)
        payload = {"summary": {"session_id": session.id, "total": len(rows), "approved": approved,
                               "attendance_rate": approved / len(rows) if rows else 0.0},
                   "checkins": rows}
        return SafeJSONResponse(content=json.loads(json.dumps(payload, default=str)), headers={
            "Content-Disposition": f'attachment; filename="{_safe(course.code + "-" + session.name)}.json"'})
    return _response(rows, format, _safe(f"{course.code}-{session.name}"))
