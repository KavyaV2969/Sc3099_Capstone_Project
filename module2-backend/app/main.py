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
