"""Ownership-checked course and session attendance exports."""

import csv
import io
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.db import get_db
from app.dependencies import require_roles
from app.models import Checkin, Session as AttendanceSession, User, utc_now
from app.services.reporting import attendance, business_day, session_filters, MAX_CHECKINS, MAX_SESSIONS
from app.responses import SafeJSONResponse
from app.schemas import ExportFormat, UserRole, as_utc
from app.services.access import get_course, get_session, require_course_access, require_session_access

router = APIRouter(prefix="/export", tags=["export"])
HEADERS = ["student_id", "student_name", "student_email", "session_date", "session_name", "status", "checked_in_at", "risk_score"]


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_") or "attendance"


def _csv_cell(value):
    if isinstance(value, str) and re.match(r"^[\s\x00]*[=+\-@]", value):
        return "'" + value
    return value


def _response(rows, export_format: ExportFormat, filename: str, headers=None):
    headers = {**(headers or {}), "Content-Disposition": f'attachment; filename="{filename}.{export_format.value}"'}
    if export_format is ExportFormat.JSON:
        return SafeJSONResponse(content=json.loads(json.dumps(list(rows), default=str)), headers=headers)
    def chunks():
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow({name: _csv_cell(value) for name, value in row.items()})
            yield buffer.getvalue()
    return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8", headers=headers)


def _row_query(database: Session, *, course_id=None, session_id=None, start_date=None, end_date=None):
    filters, coverage = session_filters(start_date, end_date)
    roster_query = select(AttendanceSession.attendance_roster).where(*filters)
    if course_id: roster_query = roster_query.where(AttendanceSession.course_id == course_id)
    if session_id: roster_query = roster_query.where(AttendanceSession.id == session_id)
    rosters = list(database.scalars(roster_query.limit(MAX_SESSIONS + 1)))
    if len(rosters) > MAX_SESSIONS:
        raise HTTPException(status_code=422, detail="export exceeds 1000 sessions; narrow the date range")
    coverage["denominator_available"] = all(roster is not None for roster in rosters)
    query = (select(Checkin.student_id, User.full_name, User.email, AttendanceSession.scheduled_start,
                    AttendanceSession.name, Checkin.status, Checkin.checked_in_at, Checkin.risk_score)
             .join(User, User.id == Checkin.student_id)
             .join(AttendanceSession, AttendanceSession.id == Checkin.session_id)
             .where(*filters, Checkin.scheduled_deletion_at > utc_now()))
    if course_id: query = query.where(AttendanceSession.course_id == course_id)
    if session_id: query = query.where(AttendanceSession.id == session_id)
    count = database.scalar(select(func.count()).select_from(query.subquery())) or 0
    if count > MAX_CHECKINS:
        raise HTTPException(status_code=422, detail="export exceeds 10000 check-ins; narrow the date range")
    return query.order_by(AttendanceSession.scheduled_start, User.full_name, Checkin.id), coverage, count


def _rows(bind, query):
    # Own the streaming cursor/session: request dependencies may close before iteration.
    with Session(bind) as database:
        for sid, name, email, scheduled, session_name, status, checked, risk in database.execute(
                query.limit(MAX_CHECKINS).execution_options(yield_per=200)):
            yield {"student_id": sid, "student_name": name, "student_email": email,
                   "session_date": business_day(scheduled), "session_name": session_name,
                   "status": status, "checked_in_at": checked, "risk_score": risk}


def _coverage_headers(coverage):
    return {"X-Reporting-Available-From": coverage["available_from"],
            "X-Reporting-Coverage": json.dumps(coverage, separators=(",", ":")),
            "X-Reporting-Retention-Limited": str(coverage["limited_by_retention"]).lower()}


@router.get("/attendance/{course_id}")
def export_course(course_id: UUID4, request: Request, format: ExportFormat = ExportFormat.CSV,
                  start_date: datetime | None = None, end_date: datetime | None = None,
                  database: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    course = get_course(database, str(course_id))
    require_course_access(database, course, user, allow_ta=False)
    query, coverage, count = _row_query(database, course_id=course.id, start_date=start_date, end_date=end_date)
    rows = _rows(database.get_bind(), query)
    write_audit_log(database, request, action="data_exported", user_id=user.id,
                    resource_type="course", resource_id=course.id,
                    details={"format": format.value, "rows": count, "export_type": format.value})
    database.commit()
    return _response(rows, format, _safe(f"{course.code}-attendance"), _coverage_headers(coverage))


@router.get("/session/{session_id}")
def export_session(session_id: UUID4, request: Request, format: ExportFormat = ExportFormat.CSV,
                   database: Session = Depends(get_db),
                   user: User = Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))):
    session = get_session(database, str(session_id))
    course = require_session_access(database, session, user, allow_ta=False)
    query, coverage, count = _row_query(database, session_id=session.id)
    rows = _rows(database.get_bind(), query)
    records = list(database.scalars(select(Checkin).where(Checkin.session_id == session.id,
        Checkin.scheduled_deletion_at > utc_now()).limit(MAX_CHECKINS + 1)))
    summary = attendance(session, records)
    coverage["denominator_available"] = summary["denominator_available"]
    write_audit_log(database, request, action="data_exported", user_id=user.id,
                    resource_type="session", resource_id=session.id,
                    details={"format": format.value, "rows": count, "export_type": format.value})
    database.commit()
    if format is ExportFormat.JSON:
        rows = list(rows)
        approved = sum(row["status"] == "approved" for row in rows)
        payload = {"summary": {"session_id": session.id, "total": len(rows), "approved": approved,
                               **summary},
                   "checkins": rows, "coverage": coverage}
        return SafeJSONResponse(content=json.loads(json.dumps(payload, default=str)), headers={
            **_coverage_headers(coverage),
            "Content-Disposition": f'attachment; filename="{_safe(course.code + "-" + session.name)}.json"'})
    return _response(rows, format, _safe(f"{course.code}-{session.name}"), _coverage_headers(coverage))
