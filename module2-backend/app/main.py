"""SAIV backend application assembly."""

import asyncio
import logging
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.config import get_settings
from app.db import database_readiness, get_db
from app.audit import write_audit_log
from app.middleware import RequestMiddleware
from app.metrics import registry
from app.rate_limit import redis_is_healthy
from app.responses import SafeJSONResponse
from app.routers import admin, audit, auth, checkins, courses, devices, enrollments, export, sessions, stats, users
from app.services.retention import retention_worker, run_retention_once

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    worker = None
    readiness = await asyncio.to_thread(database_readiness) if settings.retention_cleanup_enabled else None
    if readiness and not readiness.healthy:
        logger.error("Retention startup blocked by database readiness: %s", readiness.errors)
    if settings.retention_cleanup_enabled and readiness.healthy:
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

app.add_middleware(RequestMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "Content-Disposition", "X-Request-ID",
                    "X-Reporting-Available-From", "X-Reporting-Retention-Limited", "X-Reporting-Coverage"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        item = {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        errors.append(item)
    return SafeJSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    # Exception text can contain SQL parameters, credentials or upstream images.
    rid = getattr(request.state, "request_id", "")
    logger.error("unhandled request error category=%s request_id=%s", type(exc).__name__, rid)
    headers = {"X-Request-ID": rid}
    origin = request.headers.get("origin")
    if origin in settings.cors_origins:
        headers.update({"Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Expose-Headers": "X-Request-ID", "Vary": "Origin"})
    return SafeJSONResponse(status_code=500, content={"detail": "Internal server error"},
                            headers=headers)


def _audit_denial(request: Request, code: int):
    try:
        # A separate transaction: the failed request's dependency has rolled back.
        factory = app.dependency_overrides.get(get_db, get_db)
        with contextmanager(factory)() as database:
            write_audit_log(database, request, action="security_violation",
                user_id=getattr(request.state, "audit_user_id", None),
                details={"violation_type": f"http_{code}"}, success=False)
            database.commit()
    except Exception as exc:
        logger.error("security audit unavailable category=%s", type(exc).__name__)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in {401, 403, 429}:
        await run_in_threadpool(_audit_denial, request, exc.status_code)
    return SafeJSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


for router in (
    auth.router, users.router, admin.router, audit.router, courses.router,
    enrollments.router, sessions.router, checkins.router, stats.router,
    devices.router, export.router,
):
    app.include_router(router, prefix=settings.api_v1_prefix)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", tags=["health"])
def health_check():
    readiness = database_readiness()
    database = "healthy" if readiness.healthy else "unhealthy"
    if not readiness.healthy:
        logger.warning("Database readiness failed: %s", readiness.errors)
    redis = "healthy" if redis_is_healthy() else "unhealthy"
    body = {"service": "backend", "api": "healthy", "database": database, "redis": redis, "schema": readiness.schema}
    if database == "healthy" and redis == "healthy":
        return {"status": "healthy", **body}
    return JSONResponse(status_code=503, content={"status": "unhealthy", **body})
