"""Bound body reads before parsing and correlate requests without inspecting payloads."""
import logging
import re
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeout
from starlette.responses import JSONResponse
from app.metrics import request_id, traceparent, request_duration, request_errors

MAX_BODY_BYTES = 16 * 1024 * 1024
logger = logging.getLogger(__name__)


class RequestMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        headers = dict(scope.get("headers", []))
        parent = headers.get(b"traceparent", b"").decode("ascii", errors="ignore")
        valid_parent = re.fullmatch(r"00-([0-9a-f]{32})-([0-9a-f]{16})-0[01]", parent)
        trace_id = valid_parent[1] if valid_parent and int(valid_parent[1], 16) and int(valid_parent[2], 16) else uuid4().hex
        rid_token = request_id.set(rid)
        trace_token = traceparent.set(f"00-{trace_id}-{uuid4().hex[:16]}-01")
        received, status, started, response_started = 0, 500, monotonic(), False

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="request body exceeds 16 MiB")
            return message

        async def correlated_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            length = headers.get(b"content-length")
            if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
                response = JSONResponse({"detail": "request body exceeds 16 MiB"}, status_code=413)
                await response(scope, receive, correlated_send)
            else:
                try:
                    await self.app(scope, bounded_receive, correlated_send)
                except HTTPException:
                    raise
                except Exception as exc:
                    # Do not rethrow SQL/service exceptions into Uvicorn's raw traceback logger.
                    logger.error("unhandled request error category=%s request_id=%s", type(exc).__name__, rid)
                    if not response_started:
                        unavailable = isinstance(exc, (OperationalError, DatabaseTimeout))
                        await JSONResponse({"detail": "Database unavailable" if unavailable else "Internal server error"},
                                           status_code=503 if unavailable else 500)(
                            scope, receive, correlated_send)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"] if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
            request_duration.labels(method, route, str(status)).observe(monotonic() - started)
            if status >= 400:
                request_errors.labels(str(status)).inc()
            logger.info("request request_id=%s method=%s route=%s status=%d duration_ms=%.1f",
                        rid, scope["method"], route, status, (monotonic() - started) * 1000)
            request_id.reset(rid_token)
            traceparent.reset(trace_token)
