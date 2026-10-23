"""JSON rendering that neutralises HTML-significant characters in string values."""

import json
from http import HTTPStatus
from typing import Any

from fastapi.responses import JSONResponse


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content, ensure_ascii=True, allow_nan=False,
            separators=(",", ":"),
        ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").encode("utf-8")


def error_code(status_code: int) -> str:
    """Machine-readable error code for the Module 2 error format {"detail", "code"}."""
    if status_code == 422:
        return "VALIDATION_ERROR"
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return "ERROR"


def error_body(status_code: int, detail: Any) -> dict:
    return {"detail": detail, "code": error_code(status_code)}
