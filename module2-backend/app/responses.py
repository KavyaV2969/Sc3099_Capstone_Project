"""JSON rendering that neutralises HTML-significant characters in string values."""

import json
from typing import Any

from fastapi.responses import JSONResponse


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content, ensure_ascii=True, allow_nan=False,
            separators=(",", ":"),
        ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").encode("utf-8")
