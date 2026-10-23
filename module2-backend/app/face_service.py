"""Validated, privacy-preserving boundary to the Module 3 service."""
import logging
import zlib
from math import isclose
from time import monotonic
from typing import Annotated, TypeVar

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from app.config import get_settings
from app.metrics import request_id, traceparent, dependency_duration

logger = logging.getLogger(__name__)
Score = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
TemplateHash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-fA-F]{64}$")]


class ServiceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EnrollmentDetails(ServiceResponse):
    face_detected: StrictBool
    face_detection_confidence: Score


class EnrollmentResult(ServiceResponse):
    enrollment_successful: StrictBool
    quality_score: Score
    face_template_hash: TemplateHash | None = None
    details: EnrollmentDetails | None = None

    @model_validator(mode="after")
    def successful_evidence(self):
        if self.enrollment_successful and (
            self.face_template_hash is None or self.quality_score < .5
            or self.details is None or not self.details.face_detected
            or self.details.face_detection_confidence < .7
        ):
            raise ValueError("inconsistent enrollment evidence")
        return self


class VerificationResult(ServiceResponse):
    match_passed: StrictBool
    match_score: Score
    match_threshold: Score
    face_detected: StrictBool
    current_template_hash: TemplateHash | None = None

    @model_validator(mode="after")
    def consistent_match(self):
        if not isclose(self.match_threshold, .7, rel_tol=0, abs_tol=1e-9):
            raise ValueError("unexpected match threshold")
        if self.match_passed != (self.match_score >= .7) or (self.match_passed and not self.face_detected):
            raise ValueError("inconsistent match evidence")
        return self


class LivenessResult(ServiceResponse):
    liveness_passed: StrictBool
    liveness_score: Score
    liveness_threshold: Score
    face_embedding_hash: TemplateHash | None = None

    @model_validator(mode="after")
    def consistent_liveness(self):
        if not isclose(self.liveness_threshold, .6, rel_tol=0, abs_tol=1e-9):
            raise ValueError("unexpected liveness threshold")
        if self.liveness_passed != (self.liveness_score >= .6):
            raise ValueError("inconsistent liveness evidence")
        return self


Result = TypeVar("Result", bound=ServiceResponse)


async def _post(path: str, payload: dict, result_type: type[Result]) -> Result:
    settings = get_settings()
    started, upstream_status, category = monotonic(), None, "success"
    try:
        headers = {"Accept-Encoding": "identity", "X-Request-ID": request_id.get(),
                   "traceparent": traceparent.get()}
        async with httpx.AsyncClient(timeout=settings.face_service_timeout_seconds) as client:
            async with client.stream("POST", f"{settings.face_service_url.rstrip('/')}{path}",
                                     json=payload, headers=headers) as response:
                upstream_status = response.status_code
                if upstream_status in {400, 422}:
                    category = "invalid_input"
                    raise HTTPException(status_code=400, detail="face verification failed")
                expected_status = 201 if path == "/face/enroll" else 200
                if upstream_status != expected_status:
                    category = "unexpected_status"
                    raise HTTPException(status_code=503, detail="face recognition service unavailable")
                category = "invalid_response"
                encoding = response.headers.get("content-encoding", "identity").lower()
                if encoding not in {"identity", "gzip", "deflate"}:
                    raise ValueError("unsupported response encoding")
                # Custom transports can supply an already-read/decompressed response.
                prefetched = response.is_stream_consumed
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS) if encoding != "identity" and not prefetched else None
                body, wire_size = bytearray(), 0
                async def chunks():
                    if prefetched:
                        yield response.content
                    else:
                        async for chunk in response.aiter_raw():
                            yield chunk
                async for chunk in chunks():
                    wire_size += len(chunk)
                    if wire_size > 128 * 1024:
                        raise ValueError("response too large")
                    body.extend(decoder.decompress(chunk, 64 * 1024 + 1 - len(body)) if decoder else chunk)
                    if len(body) > 64 * 1024:
                        raise ValueError("response too large")
                if decoder and (not decoder.eof or decoder.unused_data):
                    raise ValueError("invalid compressed response")
        result = result_type.model_validate_json(bytes(body))
        category = "success"
        return result
    except HTTPException:
        raise
    except httpx.TimeoutException:
        category = "timeout"
        raise HTTPException(status_code=503, detail="face recognition service unavailable") from None
    except httpx.HTTPError:
        category = "transport"
        raise HTTPException(status_code=503, detail="face recognition service unavailable") from None
    except (ValueError, zlib.error):
        # Includes JSON and Pydantic failures; never log their payload-bearing text.
        raise HTTPException(status_code=503, detail="face recognition service unavailable") from None
    finally:
        dependency_duration.labels(path, category).observe(monotonic() - started)
        logger.log(logging.INFO if category == "success" else logging.WARNING,
                   "face_service operation=%s category=%s upstream_status=%s duration_ms=%.1f request_id=%s",
                   path, category, upstream_status, (monotonic() - started) * 1000, request_id.get())


async def enroll_face(user_id: str, image: str) -> EnrollmentResult:
    return await _post("/face/enroll", {"user_id": user_id, "image": image, "camera_consent": True}, EnrollmentResult)


async def verify_face(reference_template_hash: str, image: str) -> VerificationResult:
    return await _post("/face/verify", {"image": image, "reference_template_hash": reference_template_hash}, VerificationResult)


async def check_liveness(image: str) -> LivenessResult:
    return await _post("/liveness/check", {"challenge_response": image, "challenge_type": "passive"}, LivenessResult)
