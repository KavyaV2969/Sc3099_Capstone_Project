"""SAIV backend application assembly."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import database_is_healthy
from app.rate_limit import redis_is_healthy
from app.responses import SafeJSONResponse
from app.routers import admin, audit, auth, checkins, courses, devices, enrollments, export, sessions, stats, users
from app.services.retention import retention_worker, run_retention_once

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    worker = None
    if settings.retention_cleanup_enabled:
        try:
            await asyncio.to_thread(run_retention_once)
        except Exception:
            pass
        worker = asyncio.create_task(retention_worker(settings, stop))
    try:
        yield
    finally:
        stop.set()
        if worker:
            await worker


app = FastAPI(
    title=settings.app_name,
    description="Secure Attendance & Identity Verification System",
    version="0.2.0",
    default_response_class=SafeJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        item = {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        errors.append(item)
    return SafeJSONResponse(status_code=422, content={"detail": errors})


for router in (
    auth.router, users.router, admin.router, audit.router, courses.router,
    enrollments.router, sessions.router, checkins.router, stats.router,
    devices.router, export.router,
):
    app.include_router(router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health_check():
    database = "healthy" if database_is_healthy() else "unhealthy"
    redis = "healthy" if redis_is_healthy() else "unhealthy"
    body = {"service": "backend", "api": "healthy", "database": database, "redis": redis}
    if database == "healthy" and redis == "healthy":
        return {"status": "healthy", **body}
    return JSONResponse(status_code=503, content={"status": "unhealthy", **body})
