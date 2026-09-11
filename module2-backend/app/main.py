"""SAIV Backend API authentication and core attendance service."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import database_is_healthy
from app.rate_limit import redis_is_healthy
from app.routers import admin, audit, auth, checkins, courses, enrollments, sessions, users

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Secure Attendance & Identity Verification System",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(users.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(audit.router, prefix=settings.api_v1_prefix)
app.include_router(courses.router, prefix=settings.api_v1_prefix)
app.include_router(enrollments.router, prefix=settings.api_v1_prefix)
app.include_router(sessions.router, prefix=settings.api_v1_prefix)
app.include_router(checkins.router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health_check():
    """Report API, PostgreSQL, and Redis health without exposing credentials."""
    database = "healthy" if database_is_healthy() else "unhealthy"
    redis = "healthy" if redis_is_healthy() else "unhealthy"
    body = {"service": "backend", "api": "healthy", "database": database, "redis": redis}
    if database == "healthy" and redis == "healthy":
        return {"status": "healthy", **body}
    return JSONResponse(status_code=503, content={"status": "unhealthy", **body})


# =============================================================================
# API endpoint reference (registered routers above implement the current scope)
# =============================================================================
# All paths are relative to the /api/v1 prefix (GET /users/me is served at
# GET /api/v1/users/me). This list mirrors docs/API-SPECIFICATION.md; if the
# two ever disagree, the specification (and tests/public/) is authoritative.

# -----------------------------------------------------------------------------
# Authentication Endpoints (auth.py)
# -----------------------------------------------------------------------------
# POST /auth/register - User registration
# POST /auth/login - JWT token generation
# POST /auth/refresh - Token refresh

# -----------------------------------------------------------------------------
# User Endpoints (users.py)
# -----------------------------------------------------------------------------
# GET /users/me - Current user info
# PUT /users/me - Update profile / consent flags
# POST /users/me/face/enroll - Enroll face (proxies to the face service)
# GET /users/ - List users (admin only)
# GET /users/{user_id} - User details (admin only)
# PATCH /users/{user_id} - Update user (admin only)

# -----------------------------------------------------------------------------
# Course Endpoints (courses.py)
# -----------------------------------------------------------------------------
# GET /courses/ - List courses
# GET /courses/{course_id} - Course details
# POST /courses/ - Create course (admin only)
# PUT /courses/{course_id} - Update course (admin only)
# DELETE /courses/{course_id} - Soft-delete course (admin only)

# -----------------------------------------------------------------------------
# Session Endpoints (sessions.py)
# -----------------------------------------------------------------------------
# GET /sessions/ - List sessions (instructor/admin)
# GET /sessions/active - Currently open sessions (public, no auth)
# GET /sessions/my-sessions - Sessions relevant to the current user
# GET /sessions/{session_id} - Session details
# POST /sessions/ - Create session (instructor)
# PATCH /sessions/{session_id} - Update session
# DELETE /sessions/{session_id} - Delete session

# -----------------------------------------------------------------------------
# Check-in Endpoints (checkins.py)
# -----------------------------------------------------------------------------
# POST /checkins/ - Submit check-in
# GET /checkins/ - List check-ins (with filters)
# GET /checkins/my-checkins - Student's own check-ins
# GET /checkins/session/{session_id} - Check-ins for a session
# GET /checkins/flagged - Flagged check-ins
# GET /checkins/{checkin_id} - Check-in details
# POST /checkins/{checkin_id}/appeal - Student appeals a check-in
# POST /checkins/{checkin_id}/review - Instructor reviews an appeal

# -----------------------------------------------------------------------------
# Statistics Endpoints (stats.py)
# -----------------------------------------------------------------------------
# GET /stats/overview - System overview
# GET /stats/sessions/{session_id} - Session statistics
# GET /stats/courses/{course_id} - Course statistics
# GET /stats/students/{student_id} - Student statistics

# -----------------------------------------------------------------------------
# Device Endpoints (devices.py)
# -----------------------------------------------------------------------------
# POST /devices/register - Register device
# GET /devices/my-devices - Current user's devices
# PATCH /devices/{device_id} - Update device
# DELETE /devices/{device_id} - Remove device

# -----------------------------------------------------------------------------
# Enrollment Endpoints (enrollments.py)
# -----------------------------------------------------------------------------
# GET /enrollments/my-enrollments - Student's enrollments
# GET /enrollments/course/{course_id} - Students enrolled in a course
# POST /enrollments/ - Enroll a student
# POST /enrollments/bulk - Bulk enroll
# DELETE /enrollments/{enrollment_id} - Drop enrollment

# -----------------------------------------------------------------------------
# Audit Log Endpoints (audit.py)
# -----------------------------------------------------------------------------
# GET /audit/ - Query audit logs (admin only)
# Audit logs are append-only: there is no create/update/delete endpoint.
# Entries are written internally by the other endpoints.

# -----------------------------------------------------------------------------
# Export Endpoints (export.py)
# -----------------------------------------------------------------------------
# GET /export/attendance/{course_id} - CSV attendance export for a course
# GET /export/session/{session_id} - CSV export for a session

# -----------------------------------------------------------------------------
# Admin Endpoints (admin.py) - Required for automated testing
# -----------------------------------------------------------------------------
# PATCH /admin/users/{user_id}/deactivate - Deactivate user (admin only)
# PATCH /admin/users/{user_id}/activate - Activate user (admin only)
# POST /admin/users/bulk - Bulk create users (admin only)
# PATCH /admin/sessions/{session_id}/status - Update session status (admin only)
# POST /admin/enrollments/ - Admin enrollment creation (admin only)
