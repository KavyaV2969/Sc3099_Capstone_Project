"""Small, strict client for the Module 3 face-recognition service."""

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings


class FaceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enrollment_successful: bool | None = None
    face_template_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    quality_score: float = Field(default=0.0, ge=0, le=1)
    match_passed: bool | None = None
    match_score: float | None = Field(default=None, ge=0, le=1)
    liveness_passed: bool | None = None
    liveness_score: float | None = Field(default=None, ge=0, le=1)


async def _post(path: str, payload: dict) -> dict:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.face_service_timeout_seconds) as client:
            response = await client.post(f"{settings.face_service_url.rstrip('/')}{path}", json=payload)
        if response.status_code >= 500:
            raise HTTPException(status_code=503, detail="face recognition service unavailable")
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail="face verification failed")
        return response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="face recognition service unavailable") from exc


async def enroll_face(user_id: str, image: str) -> FaceResult:
    return FaceResult.model_validate(await _post(
        "/face/enroll", {"user_id": user_id, "image": image, "camera_consent": True}
    ))


async def verify_face(reference_template_hash: str, image: str) -> FaceResult:
    return FaceResult.model_validate(await _post(
        "/face/verify", {"image": image, "reference_template_hash": reference_template_hash}
    ))


async def check_liveness(image: str) -> FaceResult:
    return FaceResult.model_validate(await _post(
        "/liveness/check", {"challenge_response": image, "challenge_type": "passive"}
    ))
