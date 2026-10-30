"""
SAIV Face Recognition & Risk Service - Module 3

This is the skeleton implementation for the Face Recognition module.
Students must implement face enrollment, verification, liveness detection,
and risk scoring.

Privacy Requirements:
- NO raw face images should be stored
- Process images in-memory only
- Store only SHA-256 hashes of face embeddings

Recommended Libraries:
- MediaPipe: Face detection and 468-landmark face mesh
- OpenCV: Image processing
- Pillow: Image loading from base64
- NumPy: Numerical operations
"""

import base64
import ipaddress
import numpy as np
import mediapipe as mp
import threading
import cv2
import torch
import math
import time 
from uniface.spoofing import MiniFASNet, MiniFASNetWeights
from facenet_pytorch import InceptionResnetV1
from io import BytesIO
from PIL import Image
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool 
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Dict, List, Any, Literal, Union

#### CONFIGURATIONS 
FACENET_INPUT_SIZE = 160
FACE_CROP_MARGIN = 0.15
EMBEDDING_DIM = 512

SIMHASH_SEED = 3099
SIMHASH_BITS = 256
PLANES = np.random.default_rng(SIMHASH_SEED).standard_normal((SIMHASH_BITS, EMBEDDING_DIM))

ENROLL_MIN_CONFIDENCE = 0.7
ENROLL_MIN_QUALITY = 0.5

MATCH_THRESHOLD = 0.7
MATCH_HAMMING_THRESHOLD = 60

MAX_IMAGE_BYTES = 10*1024*1024 #image above 10MB size to be rejected 
MIN_FACE_SIZE_PX = 40 #facenet reqs 160x160 so if face size in pixels is too small, the embedding would be inaccurate 

LIVENESS_THRESHOLD = 0.6
# LIVENESS_WEIGHTS = {
#     "depth" : 0.30, 
#     "mesh" : 0.25,
#     "texture" : 0.25,
#     "color" : 0.20
# }
LIVENESS_MODEL = "MiniFASNetV2 (uniface)"

FACE_MESH_LANDMARKS = 468
MESH_CROP_MARGIN = 0.5
DEPTH_FLAT_Z = 0.01
DEPTH_REAL_Z = 0.05

MAX_CHALLENGE_FRAMES = 30
KEY_FRAME_SAMPLES = 4
EAR_MIN_OPEN = 0.15
BLINK_OPEN_RATIO = 0.8
BLINK_CLOSED_RATIO = 0.55
HEAD_TURN_MIN_DEG = 20
SAME_PERSON_HAMMING_MAX = 80
CHALLENGE_FAILED_SCORE_CAP = 0.3

RIGHT_EYE_EAR = [33, 160, 158, 133, 153, 144]
LEFT_EYE_EAR = [362, 385, 387, 263, 373, 380]
FACE_EDGE_IMAGE_LEFT = 234
FACE_EDGE_IMAGE_RIGHT = 454
NOSE_TIP = 1

RISK_WEIGHTS = {
    "liveness" : 0.25,
    "face_match" : 0.25,
    "device" : 0.2, 
    "network" : 0.15,
    "geolocation" : 0.15
}

RISK_THRESHOLD = 0.5
MISSING_SIGNAL_RISK = 0.5

DEVICE_RISK_THRESHOLD = 0.5

GEO_TOO_PRECISE_M = 10
GEO_RADIUS_M = 100
GEO_POOR_M = 5000
GEO_RISK_THRESHOLD = 0.5

VPN_KEYWORDS = ["vpn", "proxy", "tunnel", "tor"]
#PROMETHEUS METRICS
HTTP_REQUESTS = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10))
HTTP_IN_FLIGHT = Gauge("http_requests_in_progress", "Requests currently being processed")

ENROLL_RESULTS = Counter("face_enroll_total", "Enrollment outcomes", ["result"])
VERIFY_RESULTS = Counter("face_verify_total", "Verification outcomes", ["result"])
VERIFY_HAMMING = Histogram("face_verify_hamming_distance", "SimHash Hamming Distance probe vs reference", buckets=(10, 20, 30, 40, 50, 60, 70, 80, 100, 128, 256))
LIVENESS_RESULTS = Counter("face_liveness_total", "Liveness outcomes", ["challenge_type", "result"])
RISK_LEVELS = Counter("face_risk_assess_total", "Risk assessment by level", ["level"])
RISK_SCORE = Histogram("face_risk_score", "Distribution of risk scores", buckets =(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))

torch.set_num_threads(1)
cv2.setNumThreads(0)

# =============================================================================
#ANTI-SPOOF MODEL LOADING ON APP STARTUP
# =============================================================================
ANTI_SPOOF_REAL_INDEX = 1 #model outputs 3 classes - index 1 refers to the real face

anti_spoof_model : Optional[MiniFASNet] = None
anti_spoof_lock = threading.Lock()

def get_anti_spoof_model() -> MiniFASNet:
    global anti_spoof_model
    if anti_spoof_model is None:
        with anti_spoof_lock:
            if anti_spoof_model is None:
                model = MiniFASNet(model_name=MiniFASNetWeights.V2, providers=["CPUExecutionProvider"])
                width, height = model.input_size
                model.session.run(None, {model.input_name : np.zeros((1, 3, height, width), np.float32)})
                anti_spoof_model = model
    return anti_spoof_model

def predict_spoof(image_rgb: np.ndarray, bbox_xywh: List[int]) -> dict:
    model = get_anti_spoof_model()
    x,y,w,h = bbox_xywh
    image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    try:
        blob = model.preprocess(image_bgr, [x, y, x + w, y + h])
        logits = model.session.run(None, {model.input_name: blob})[0][0].astype(np.float64)
    finally:
        del image_bgr

    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    real_prob = float(probs[ANTI_SPOOF_REAL_INDEX])

    return{
        "real_probability" : real_prob,
        "spoof_probability" : 1.0 - real_prob,
        "predicted_label" : "real" if int(np.argmax(probs)) == ANTI_SPOOF_REAL_INDEX else "spoof"
    }



# =============================================================================
#FACE EMBEDDING MODEL LOADING ON APP STARTUP
# =============================================================================

facenet_model: Optional[InceptionResnetV1] = None
facenet_lock = threading.Lock()

def get_facenet_model() -> InceptionResnetV1:
    global facenet_model
    if facenet_model is None:
        with facenet_lock:
            if facenet_model is None: 
                facenet_model = InceptionResnetV1(pretrained="vggface2").eval()
    return facenet_model

@asynccontextmanager
async def lifespan(app : FastAPI):
    print("lifespan: loading facenet!")
    get_facenet_model()
    print("lifespan: facenet ready!")
    print("lifespan: loading anti-spoof model!")
    get_anti_spoof_model()
    print("lifespan: anti-spoof model ready!")
    yield

app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk scoring service",
    version="1.0.0",
    lifespan= lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    HTTP_IN_FLIGHT.inc()
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        endpoint = route.path if route else "unmatched"
        HTTP_LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - start)
        HTTP_REQUESTS.labels(request.method, endpoint, str(status)).inc()
        HTTP_IN_FLIGHT.dec()

########################################JUST FOR TESTING
import json
import time
from fastapi import Request
from fastapi.responses import Response

# =============================================================================
# DEBUG: HTTP REQUEST/RESPONSE LOGGING
# =============================================================================

DEBUG_HTTP = False                                  # set False to switch off
REDACT_KEYS = {"image", "challenge_response"}      # base64 image fields
MAX_STR_LEN = 120                                  # shorten any other long strings


def redact(obj):
    """Recursively shorten image fields and long strings so logs stay readable."""
    if isinstance(obj, dict):
        return {
            k: (f"<base64 image, {len(v)} chars>" if k in REDACT_KEYS and isinstance(v, str) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str) and len(obj) > MAX_STR_LEN:
        return obj[:MAX_STR_LEN] + f"...<{len(obj)} chars total>"
    return obj


def format_body(raw: bytes) -> str:
    if not raw:
        return "<empty>"
    try:
        return json.dumps(redact(json.loads(raw)), indent=2, default=str)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return f"<{len(raw)} bytes, not JSON>"


@app.middleware("http")
async def log_http(request: Request, call_next):
    if not DEBUG_HTTP or request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    client = request.client.host if request.client else "?"
    req_body = await request.body()

    print(f"\n{'=' * 70}", flush=True)
    print(f">>> {request.method} {request.url.path}  (from {client})", flush=True)
    if request.query_params:
        print(f">>> query: {dict(request.query_params)}", flush=True)
    print(f">>> content-type: {request.headers.get('content-type')}", flush=True)
    print(f">>> body:\n{format_body(req_body)}", flush=True)

    try:
        response = await call_next(request)
    except Exception as e:
        ms = (time.perf_counter() - start) * 1000
        print(f"!!! UNHANDLED {type(e).__name__} on {request.url.path} after {ms:.0f} ms: {e}", flush=True)
        raise

    # Read the response body so we can print it, then rebuild the response
    resp_body = b"".join([chunk async for chunk in response.body_iterator])
    ms = (time.perf_counter() - start) * 1000

    print(f"<<< {response.status_code} {request.url.path}  ({ms:.0f} ms)", flush=True)
    print(f"<<< body:\n{format_body(resp_body)}", flush=True)
    print(f"{'=' * 70}", flush=True)

    return Response(
        content=resp_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )



################## REMOVE ABOVE

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class FaceEnrollRequest(BaseModel):
    """Request model for face enrollment."""
    user_id: str
    image: str  # Base64 encoded image
    camera_consent: bool 


class FaceEnrollResponse(BaseModel):
    """Response model for face enrollment."""
    enrollment_successful: bool
    face_template_hash: str  # 64-char SHA-256 hex string
    quality_score: float  # 0.0 to 1.0
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    """Request model for face verification."""
    image: str  # Base64 encoded image
    reference_template_hash: str  # Hash from enrollment


class FaceVerifyResponse(BaseModel):
    """Response model for face verification."""
    match_passed: bool
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.70
    face_detected: bool
    current_template_hash: str

class FaceMatchRequest(BaseModel):
    """Request model for face verification."""
    image: str  # Base64 encoded image
    reference_hash: str  # Hash from enrollment


class FaceMatchResponse(BaseModel):
    """Response model for face verification."""
    match_passed: bool
    match_score: float  # 0.0 to 1.0
    face_embedding_hash: str

class LivenessRequest(BaseModel):
    """Request model for liveness check."""
    challenge_response: Union[str, Annotated[List[str], Field(min_length=1, max_length=MAX_CHALLENGE_FRAMES)]]
    challenge_type: Literal["passive", "blink", "head_turn"] = "passive"  # blink, head_turn, passive


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    liveness_passed: bool
    liveness_score: float  # 0.0 to 1.0
    liveness_threshold: float  # Default: 0.60
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]


class GeolocationData(BaseModel):
    """Geolocation data for risk assessment."""
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(ge=0, allow_inf_nan=False)


class RiskAssessRequest(BaseModel):
    """Request model for risk assessment."""
    liveness_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    face_match_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    """Response model for risk assessment."""
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    pass_threshold: bool
    risk_threshold: float  # Default: 0.50
    signal_breakdown: Dict[str, float]
    recommendations: List[str]


# =============================================================================
# HEALTH & ROOT ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "SAIV Face Recognition & Risk Service"}

@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    """List available endpoints."""
    return {
        "service": "SAIV Face Recognition & Risk Service",
        "version": "1.0.0",
        "endpoints": {
            "/health": "GET - Health check",
            "/face/enroll": "POST - Enroll a face for verification",
            "/face/verify":"POST - Verify a face against enrolled template",
            "/face/match": "POST - Legacy face matching (use /face/verify)",
            "/liveness/check":"POST - Perform liveness detection",
            "/risk/assess":"POST - Multi-signal risk assessment",
            "/metrics" : "GET - Prometheus metrics"
        }
    }


# =============================================================================
# FACE ENROLLMENT ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(request: FaceEnrollRequest):
    """
    Enroll a user's face for future verification.

    TODO: Implement the following:
    1. Validate camera_consent is True (return 400 if False)
    2. Decode base64 image to numpy array
    3. Detect face using MediaPipe FaceDetection
    4. If no face detected, return 400 with "No face detected"
    5. Extract face features/embedding
    6. Generate SHA-256 hash of embedding (64 hex chars)
    7. Calculate quality score based on:
       - Face detection confidence
       - Image resolution
       - Face size relative to image
    8. Return enrollment response

    Success Criteria:
    - Face detected with confidence >= 0.7
    - Quality score >= 0.5
    - Returns 64-char SHA-256 hex hash
    """
    if not request.camera_consent:
        ENROLL_RESULTS.labels("no_consent").inc()
        raise HTTPException(status_code=400, detail="Camera consent required!")

    try:
        result = await run_in_threadpool(process_enrollment, request.image)
    except HTTPException:
        ENROLL_RESULTS.labels("rejected").inc()
        raise
    ENROLL_RESULTS.labels("success").inc()

    return FaceEnrollResponse(
        enrollment_successful = True, 
        face_template_hash = result["face_template_hash"],
        quality_score = result["quality_score"],
        details = {
            "face_detected" : True,
            "face_detection_confidence" : result["confidence"],
            "image_quality" : result["image_quality"]
        }
    )


# =============================================================================
# FACE VERIFICATION ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/verify", response_model=FaceVerifyResponse)
async def verify_face(request: FaceVerifyRequest):
    """
    Verify a face against an enrolled template.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with face_detected=False
    4. Extract face features/embedding
    5. Generate SHA-256 hash of current face
    6. Compare hashes or embeddings (choose your approach)
    7. Calculate match_score (0.0 to 1.0)
    8. match_passed = (match_score >= 0.70)

    Note: Hash comparison alone gives binary match. For continuous
    scores, consider perceptual hashing or embedding similarity.
    """
    if not is_valid_template_hash(request.reference_template_hash):
        VERIFY_RESULTS.labels("invalid_hash").inc()
        raise HTTPException(status_code=400, detail= "Invalid reference_template_hash (expected 64 hex characters)")

    try:
        result = await run_in_threadpool(
            process_verification, request.image, request.reference_template_hash
        )
    except HTTPException:
        VERIFY_RESULTS.labels("error").inc()
        raise
    if not result["face_detected"]:
        VERIFY_RESULTS.labels("no_face").inc()
    else:
        VERIFY_RESULTS.labels("match" if result["match_passed"] else "no_match").inc()

    return FaceVerifyResponse(
        match_passed=result["match_passed"],
        match_score=result["match_score"],
        match_threshold=result["match_threshold"],
        face_detected=result["face_detected"],
        current_template_hash=result["current_template_hash"]

    )


@app.post("/face/match", response_model = FaceMatchResponse)
async def match_face(request: FaceMatchRequest):
    """
    Legacy face matching endpoint. Redirects to /face/verify.
    Kept for backwards compatibility.
    """
    verify_result = await verify_face(
        FaceVerifyRequest(
            image = request.image,
            reference_template_hash=request.reference_hash
        )
    )

    return FaceMatchResponse(
        match_passed=verify_result.match_passed,
        match_score= verify_result.match_score,
        face_embedding_hash= verify_result.current_template_hash
    )


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.post("/liveness/check", response_model=LivenessResponse)
async def check_liveness(request: LivenessRequest):
    """
    Perform liveness detection on submitted image.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with liveness_passed=False
    4. Analyze face for liveness signals:

    REQUIRED (for partial credit):
    - Basic face detection confidence
    - Image quality assessment
    - Face size validation

    BONUS (for extra credit - see API-SPECIFICATION.md):
    - MediaPipe Face Mesh 3D analysis (468 landmarks)
    - Depth cue analysis (nose_tip_z coordinate)
    - Face mesh completeness check
    - Challenge-response detection (blink, head movement)

    Challenge Types:
    - "passive": No user action required (depth/texture analysis)
    - "blink": Detect eye blink (compare eye aspect ratios)
    - "head_turn": Detect head rotation (face mesh landmarks)

    5. Calculate liveness_score (0.0 to 1.0)
    6. liveness_passed = (liveness_score >= 0.60)
    7. Generate face embedding hash

    Depth Analysis Hints (BONUS):
    - Use MediaPipe FaceMesh to get 3D landmarks
    - nose_tip_z (landmark 1, z-coordinate) indicates depth
    - Real faces: |nose_tip_z| > 0.03 (significant depth)
    - Flat images: |nose_tip_z| < 0.01 (minimal depth)
    """

    if isinstance(request.challenge_response, list):
        frames = request.challenge_response
    else:
        frames = [request.challenge_response]

    try:
        result = await run_in_threadpool(process_liveness, frames[0], request.challenge_type, frames[1:])
    except HTTPException:
        LIVENESS_RESULTS.labels(request.challenge_type, "error").inc()
        raise
    LIVENESS_RESULTS.labels(request.challenge_type, "passed" if result["liveness_passed"] else "failed").inc()

    return LivenessResponse(
        liveness_passed=result["liveness_passed"],
        liveness_score= result["liveness_score"],
        liveness_threshold= LIVENESS_THRESHOLD,
        challenge_type=request.challenge_type,
        face_embedding_hash=result["face_embedding_hash"],
        details = result["details"]
    )    


# =============================================================================
# RISK ASSESSMENT ENDPOINT (REQUIRED - 3 points in public tests)
# =============================================================================

@app.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_risk(request: RiskAssessRequest):
    """
    Perform multi-signal risk assessment.

    TODO: Implement the following:
    1. Collect all available signals from request
    2. Calculate individual signal scores (0.0 = safe, 1.0 = risky)
    3. Apply weighted fusion:
       - Liveness: 25%
       - Face match: 25%
       - Device attestation: 20%
       - Network/VPN: 15%
       - Geolocation: 15%
    4. Calculate combined risk_score
    5. Determine risk_level:
       - LOW: risk_score < 0.3
       - MEDIUM: 0.3 <= risk_score < 0.5
       - HIGH: 0.5 <= risk_score < 0.7
       - CRITICAL: risk_score >= 0.7
    6. pass_threshold = (risk_score < 0.50)
    7. Generate recommendations for low-scoring signals

    Signal Analysis:
    - Liveness: Invert score (low liveness = high risk)
    - Face match: Invert score (low match = high risk)
    - Device: Check signature validity, public key format
    - Network: Detect VPN/proxy (private IPs, Tor exit nodes)
    - Geolocation: Check accuracy, validate coordinates

    VPN/Proxy Detection Hints:
    - Private IP ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
    - Check user_agent for VPN indicators
    - High geolocation accuracy (< 10m) might be spoofed
    - Very low accuracy (> 5000m) indicates issues
    """
    # TODO: Implement risk assessment
    signals = {
        "liveness" : liveness_risk(request.liveness_score),
        "face_match" : face_match_risk(request.face_match_score),
        "device" : device_risk(request.device_signature, request.device_public_key),
        "network" : network_risk(request.ip_address, request.user_agent),
        "geolocation" : geo_risk(request.geolocation)
    }

    contributions = {}
    recommendations = []
    for name, (risk, recommendation) in signals.items():
        contributions[name] = RISK_WEIGHTS[name] * risk
        if recommendation:
            recommendations.append(recommendation)

    risk_score = round(sum(contributions.values()), 2)
    level = risk_level_readable(risk_score)
    RISK_LEVELS.labels(level).inc()
    RISK_SCORE.observe(risk_score)

    return RiskAssessResponse(
        risk_score = risk_score,
        risk_level = level,
        pass_threshold = risk_score < RISK_THRESHOLD,
        risk_threshold = RISK_THRESHOLD,
        signal_breakdown = {name: round(value, 2) for name, value in contributions.items()},
        recommendations = recommendations
    )

####Reusing mediapipe models instead of always rebuilding on every http call -> reduce latency
mediapipe_local = threading.local()

def get_face_detector():
    if not hasattr(mediapipe_local, "face_detection"):
        mediapipe_local.face_detection = mp.solutions.face_detection.FaceDetection(model_selection = 0, min_detection_confidence = 0.5)
    return mediapipe_local.face_detection

def get_face_mesh():
    if not hasattr(mediapipe_local, "face_mesh"):
        mediapipe_local.face_mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode = True, max_num_faces = 1, refine_landmarks = True, min_detection_confidence = 0.5)
    return mediapipe_local.face_mesh


# =============================================================================
# HELPER FUNCTIONS (Implement these to support your endpoints)
# =============================================================================

def decode_base64_image(base64_string: str):
    """
    Decode a base64 encoded image to a numpy array.

    TODO: Implement using:
    - base64.b64decode()
    - PIL.Image.open(BytesIO(...))
    - numpy.array()

    Handle errors gracefully (invalid base64, corrupt image, etc.)
    """
    try :
        img_bytes = base64.b64decode(base64_string)
    except Exception:
        return None
    
    if len(img_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Image too large ({len(img_bytes) / 1024 / 1024:.1f} MB, "
                f"max {MAX_IMAGE_BYTES // 1024 // 1024} MB)"
            ),
        )
    try:
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        return np.array(img)
    except Exception as e:
        return None

def detect_face(image_array):
    """
    Detect faces in an image using MediaPipe.

    TODO: Implement using:
    - mediapipe.solutions.face_detection.eDetection
      (requires mediapipe==0.10.18 as  in requirements.txt; mediapipe
      >= 0.10.30 removed `mediapipe.s` in favour of `mediapipe.tasks`)
    - Return detection results with ce scores

    Consider setting e=0.5
    """
    results = get_face_detector().process(image_array)

    if not results.detections:
        return {"detected" : False, "confidence" : 0.0}

    detection = results.detections[0]
    confidence = detection.score[0]

    return {"detected" : True, "confidence" : confidence, "bounding_box" : detection.location_data.relative_bounding_box} 


def bbox_to_pixels(bbox, width: int, height: int):
    # keep in mind bounding box can return value outside [0,1] if face runs off the edge of frame
    x0 = min(max(0, int(bbox.xmin * width)), width)
    y0 = min(max(0, int(bbox.ymin * height)), height)
    x1 = min(width, max(x0, int((bbox.xmin + bbox.width) * width)))
    y1 = min(height, max(y0, int((bbox.ymin + bbox.height) * height)))
    return x0,y0,x1,y1

def compute_quality_score(confidence: float, image_array, bbox) -> float:
    #formula and weightage
    #detection confidence (50%), image res relative to 640x480 (20%), face size relative to the frame(30%) -> if 15% or more of the frame is face size, then full marks 
    h,w = image_array.shape[:2]

    res_score = min(1.0, (w * h) / (640 * 480))
    size_score = min(1.0, (bbox.width * bbox.height) / 0.15)

    quality_score = 0.5 * confidence + 0.2 * res_score + 0.3 * size_score
    return round(min(1.0, max(0.0, quality_score)), 2)

def image_quality_label(quality_score: float) -> str:
    if quality_score >= 0.75:
        return "good"
    if quality_score >= ENROLL_MIN_QUALITY:
        return "acceptable"
    return "poor"

def crop_for_facenet(image_array, detection) -> np.ndarray:
    h,w = image_array.shape[:2]
    x0,y0,x1,y1 = bbox_to_pixels(detection["bounding_box"], w ,h)
    face_width, face_height= x1 - x0, y1 - y0

    if face_width < MIN_FACE_SIZE_PX or face_height < MIN_FACE_SIZE_PX:
        raise ValueError(f"Face too small ({face_width}x{face_height}px)")

    pad_x = int(face_width * FACE_CROP_MARGIN)
    pad_y = int(face_height * FACE_CROP_MARGIN)
    crop_left = max(0, x0 - pad_x)
    crop_top = max(0, y0 - pad_y)
    crop_right = min(w, x1 + pad_x)
    crop_bottom = min(h, y1 + pad_y)

    face_crop = image_array[crop_top:crop_bottom, crop_left:crop_right]
    if face_crop.size == 0:
        raise ValueError("Empty face crop!")

    interpolation = (
        cv2.INTER_AREA if face_crop.shape[0] > FACENET_INPUT_SIZE else cv2.INTER_LINEAR
    )

    return cv2.resize(
        face_crop, (FACENET_INPUT_SIZE, FACENET_INPUT_SIZE), interpolation = interpolation
    )

    
def extract_face_embedding(image_array, detection):
    """
    Extract face embedding/features for hashing.

    TODO: Choose your approach:
    - Simple: Crop face region, resize to standard size, flatten
    - Advanced: Use MediaPipe Face Mesh landmarks
    - Even more advanced: Use face recognition model (dlib, etc.)

    Return numpy array that can be hashed.
    """
    face = crop_for_facenet(image_array, detection)
    face = (face.astype(np.float32) - 127.5) / 128.0
    tensor = torch.from_numpy(face).permute(2, 0, 1).unsqueeze(0)

    with torch.no_grad():
        embedding = get_facenet_model()(tensor)

    return embedding[0].numpy()




def generate_face_hash(embedding) -> str:
    """
    Generate SHA-256 hash of face embedding.

    TODO: Implement using:
    - hashlib.sha256()
    - embedding.tobytes() or embedding.tostring()
    - Return 64-character hex string
    """
    embedding = np.asarray(embedding, dtype=np.float64).reshape(-1)
    if embedding.shape[0] != EMBEDDING_DIM:
        raise ValueError(f"embedding dim {embedding.shape[0]} != configured {EMBEDDING_DIM}")
    if not np.isfinite(embedding).all():
        raise ValueError(f"embedding contains NaN/inf")

    bits = (PLANES @ embedding) > 0
    return np.packbits(bits).tobytes().hex()

def process_enrollment(image_b64 : str) -> dict:
    image_array = None
    embedding = None

    try:
        image_array = decode_base64_image(image_b64)
        if image_array is None:
            raise HTTPException(status_code=400, detail="Invalid image data!")

        detection = detect_face(image_array)
        if not detection["detected"]:
            raise HTTPException(status_code=400, detail="No face detected")

        confidence = detection["confidence"]
        bbox = detection["bounding_box"]

        quality_score = compute_quality_score(confidence, image_array, bbox)
        if confidence < ENROLL_MIN_CONFIDENCE or quality_score < ENROLL_MIN_QUALITY:
            raise HTTPException(status_code=400, detail=(
                "Face image quality too low for enrollment "
                f"(confidence {confidence:.2f}, quality {quality_score:.2f})"
            ))

        try:
            embedding = extract_face_embedding(image_array, detection)
            template_hash = generate_face_hash(embedding)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Could not process face: {e}")

        return{
            "face_template_hash" : template_hash,
            "quality_score" : quality_score,
            "confidence" : round(confidence, 2),
            "image_quality" : image_quality_label(quality_score)
        }
        
    finally:
        del image_array
        del embedding

def is_valid_template_hash(template_hash: str) -> bool:
    return(
        len(template_hash) == SIMHASH_BITS / 4 and all(x in "0123456789abcdefABCDEF" for x in template_hash)
    )

def hamming_distance(hash_a: str , hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")

def hamming_to_match_score(distance: int) -> float:
    if distance <= MATCH_HAMMING_THRESHOLD:
        score = 1.0 - (1.0 - MATCH_THRESHOLD) * distance / MATCH_HAMMING_THRESHOLD
    else:
        random_level = SIMHASH_BITS / 2
        score = MATCH_THRESHOLD * (random_level - distance) / (random_level - MATCH_HAMMING_THRESHOLD)
    return round(min(1.0, max(0.0, score)), 2)

def process_verification(image_b64: str, reference_hash: str) -> dict:
    image_array = None
    embedding = None

    try:
        image_array = decode_base64_image(image_b64)
        if image_array is None:
            raise HTTPException(status_code=400, detail="Invalid image data!")

        detection = detect_face(image_array)
        if not detection["detected"]:
            return{
                "match_passed" : False,
                "match_score" : 0.0, 
                "match_threshold" : MATCH_THRESHOLD,
                "face_detected" : False,
                "current_template_hash" : "",
            }
        try:
            embedding = extract_face_embedding(image_array, detection)
            current_hash = generate_face_hash(embedding)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Could not process face: {e}")

        distance = hamming_distance(current_hash, reference_hash)
        VERIFY_HAMMING.observe(distance)
        match_score = hamming_to_match_score(distance)

        return{
                "match_passed" : match_score >= MATCH_THRESHOLD,
                "match_score" : match_score, 
                "match_threshold" : MATCH_THRESHOLD,
                "face_detected" : True,
                "current_template_hash" : current_hash,
        }
    finally:
        del image_array
        del embedding


def eye_aspect_ratio(pts: np.ndarray, idx: List[int]) -> float:
    p = pts[idx, :2]
    vertical = math.dist(p[1], p[5]) + math.dist(p[2], p[4])
    width = math.dist(p[0], p[3])
    return vertical / (2 * width)

def head_yaw_deg(pts):
    left, right = pts[FACE_EDGE_IMAGE_LEFT], pts[FACE_EDGE_IMAGE_RIGHT]
    return math.degrees(math.atan2(right[2] - left[2], right[0] - left[0]))


def analyze_face_mesh(image_array):
    """
    Analyze face using MediaPipe Face Mesh (BONUS).

    TODO: Implement using:
    - mediapipe.solutions.face_mesh.FaceMesh (mediapipe==0.10.18, see note in detect_face)
    - Extract 468 landmarks
    - Calculate depth from nose_tip_z (landmark index 1)
    - Check mesh completeness

    Return dict with:
    - face_mesh_complete: bool
    - landmark_count: int
    - nose_tip_z: float
    - depth_quality: "good" | "moderate" | "poor"
    """
    h, w = image_array.shape[:2]
    results = get_face_mesh().process(image_array)

    if not results.multi_face_landmarks:
        return{
            "found" : False,
            "face_mesh_complete" : False,
            "landmark_count" : 0,
            "in_frame_ratio" : 0.0,
            "nose_tip_z" : 0.0,
            "depth_quality" : "poor",
            "eye_aspect_ratio" : None,
            "head_yaw_deg" : None
        }

    landmarks = results.multi_face_landmarks[0].landmark
    landmark_count = len(landmarks)
    pts = np.array([[lm.x * w, lm.y * h, lm.z * w] for lm in landmarks])

    in_frame = sum(1 for landmark in landmarks if 0<= landmark.x <= 1 and 0 <= landmark.y <= 1)
    nose_tip_z = landmarks[NOSE_TIP].z

    if nose_tip_z < -DEPTH_REAL_Z:
        depth_quality = "good"
    elif abs(nose_tip_z) > DEPTH_FLAT_Z:
        depth_quality = "moderate"
    else:
        depth_quality = "poor"

    return{
            "found" : True,
            "face_mesh_complete" : landmark_count >= FACE_MESH_LANDMARKS and in_frame == landmark_count,
            "landmark_count" : landmark_count,
            "in_frame_ratio" : round(in_frame / landmark_count, 2),
            "nose_tip_z" : round(nose_tip_z, 2),
            "depth_quality" : depth_quality,
            "eye_aspect_ratio" : round((eye_aspect_ratio(pts, RIGHT_EYE_EAR) + eye_aspect_ratio(pts, LEFT_EYE_EAR)) / 2 ,3),
            "head_yaw_deg" : round(head_yaw_deg(pts), 2)
    }

def crop_face_region (image_array, detection, margin: float):
    h,w = image_array.shape[:2]
    x0,y0,x1,y1 = bbox_to_pixels(detection["bounding_box"], w ,h)
    pad_x = int((x1 - x0) * margin)
    pad_y = int((y1 - y0) * margin)
    return image_array[max(0, y0 - pad_y):min(h, y1 + pad_y), max(0, x0 - pad_x):min(w, x1 + pad_x)]

def bbox_to_xywh(bbox, width: int, height: int) -> List[int]:
    x0,y0,x1,y1 = bbox_to_pixels(bbox, width ,height)
    return(x0, y0, x1-x0, y1-y0)




def liveness_failed_result(reason:str, face_detected: bool, confidence: float, **extra) ->  dict:
    return{
        "liveness_passed" : False, 
        "liveness_score" : 0.0,
        "face_embedding_hash" : "",
        "details" : {
            "face_detected" : face_detected,
            "face_detection_confidence" : confidence,
            "face_mesh_complete" : False,
            "depth_detected" : False,
            "texture_analysis_score" : 0.0,
            "spoof_suspected" : True,
            "model" : LIVENESS_MODEL,
            "threshold" : LIVENESS_THRESHOLD,
            "reason" : reason,
            **extra
        }
    }

class FrameRejected(Exception): 
    def __init__(self, reason: str, face_detected: bool = True, confidence: float = 0.0):
        super().__init__(reason)
        self.face_detected = face_detected
        self.confidence = confidence

def scan_frame(image_b64: str, frame_no: int, quality_gate: bool) -> dict:
    image_array = None
    try:
        image_array = decode_base64_image(image_b64)
        if image_array is None:
            raise HTTPException(status_code=400, detail=f"Invalid image data in frame number {frame_no}!")
        detection = detect_face(image_array)
        if not detection["detected"]:
            raise FrameRejected(f"No face detected in frame number {frame_no}!", face_detected=False)

        confidence = round(detection["confidence"], 2)
        h,w = image_array.shape[:2]
        bbox_xywh = bbox_to_xywh(detection["bounding_box"], w, h)
        if bbox_xywh[2] < MIN_FACE_SIZE_PX or bbox_xywh[3] < MIN_FACE_SIZE_PX:
            raise FrameRejected(f"Face too small in frame {frame_no} ({bbox_xywh[2]}x{bbox_xywh[3]}px)", confidence=confidence)
        quality_score = compute_quality_score(detection["confidence"], image_array, detection["bounding_box"])
        if quality_gate and (confidence < ENROLL_MIN_CONFIDENCE or quality_score < ENROLL_MIN_QUALITY):
            raise FrameRejected(f"Face image quality too low in frame {frame_no} (confidence = {confidence:.2f}, quality = {quality_score:.2f})", confidence = confidence)

        return{
            "frame_no" : frame_no,
            "detection" : detection,
            "bbox_xywh" : bbox_xywh,
            "confidence" : confidence,
            "quality_score" : quality_score,
            "mesh" : analyze_face_mesh(crop_face_region(image_array, detection, MESH_CROP_MARGIN))
        }
    finally:
        del image_array

def verify_frame(image_b64: str, scan: dict) -> dict:
    image_array = None
    embedding = None
    try:
        image_array = decode_base64_image(image_b64)
        try:
            spoof = predict_spoof(image_array, scan["bbox_xywh"])
        except ValueError as e:
            raise FrameRejected(f"Could not analyse face in frame {scan['frame_no']} : {e}", confidence = scan["confidence"])
        embedding = extract_face_embedding(image_array, scan["detection"])
        return {
            "real_probability" : spoof["real_probability"],
            "face_hash" : generate_face_hash(embedding)
        }
    finally:
        del image_array
        del embedding

def detect_blink(frames: List[dict]) -> dict:
    eye_aspect_ratios = [frame["mesh"]["eye_aspect_ratio"] for frame in frames]
    open_level = max(eye_aspect_ratios)
    is_open = [e >= BLINK_OPEN_RATIO * open_level for e in eye_aspect_ratios]
    is_closed = [e <= BLINK_CLOSED_RATIO * open_level for e in eye_aspect_ratios]

    blink_at = None
    for i in range(len(eye_aspect_ratios)):
        if is_closed[i] and any(is_open[:i]) and any(is_open[i + 1:]):
            if blink_at is None or eye_aspect_ratios[i] < eye_aspect_ratios[blink_at]:
                blink_at = i

    completed = blink_at is not None and open_level >= EAR_MIN_OPEN
    if open_level < EAR_MIN_OPEN:
        reason = "Eyes never clearly open"
    elif completed:
        reason = f"Blink detected at frame {frames[blink_at]['frame_no']}"
    elif any(is_closed):
        reason = "Eyes closed but never open before or after blink detected"
    else:
        reason = "No blink detected"

    return{
        "challenge_completed" : completed,
        "challenge_reason" : reason,
        "event_index" : blink_at,
        "eye_aspect_ratios" : eye_aspect_ratios
    }

def check_head_turn(frames: List[dict]) -> dict:
    yaws = [frame["mesh"]["head_yaw_deg"] for frame in frames]
    span = max(yaws) - min(yaws)
    completed = span >= HEAD_TURN_MIN_DEG
    turned_at = int(np.argmax(np.abs(np.array(yaws) - yaws[0])))
    return{
        "challenge_completed" : completed,
        "challenge_reason" : f"Head turned {span:.0f} degrees" if completed else f"Head turn too small ({span:.0f} < {HEAD_TURN_MIN_DEG} degrees)",
        "event_index" : turned_at if completed else None,
        "head_yaw_degrees" : yaws,
        "head_turn_direction" : ("image_right" if yaws[turned_at] > yaws[0] else "image_left") if completed else None
    }

def pick_key_frames(n_frames: int, event_index: Optional[int]) -> List[int]:
    keys = {0}
    if event_index is not None:
        keys.add(event_index)
    if n_frames > 1:
        step = (n_frames - 1) / KEY_FRAME_SAMPLES
        keys.update(round(step * i) for i in range(1, KEY_FRAME_SAMPLES + 1))
    return sorted(keys)


def process_liveness(image_b64: str, challenge_type: str = "passive", extra_frames: Optional[List[str]] = None) -> dict:
    is_challenge = challenge_type != "passive"
    frames_b64 = [image_b64] + (list(extra_frames or []) if is_challenge else [])

    if is_challenge and len(frames_b64) < 2:
        return liveness_failed_result(
            f"'{challenge_type}' challenge needs at least 2 frames: send a list of frames in 'challenge_response'",
            face_detected=False, confidence=0.0, challenge_completed = False
        )
    usable, skipped = [],[]
    for i, frame_b64 in enumerate(frames_b64):
        try:
            scan = scan_frame(frame_b64, i, quality_gate=(i == 0))
        except FrameRejected as e:
            if i == 0:
                return liveness_failed_result(str(e), face_detected= e.face_detected, confidence=e.confidence)
            skipped.append(i)
            continue
        if is_challenge and not scan["mesh"]["found"]:
            if i == 0:
                return liveness_failed_result("Face landmarks not found in frame 0", face_detected=True, confidence=scan["confidence"], challenge_completed = False)
            skipped.append(i)
            continue
        scan["b64"] = frame_b64
        usable.append(scan)

    ref = usable[0]
    if is_challenge and len(usable) < 2:
        return liveness_failed_result(f"Not enough usable frames ({len(usable)} of {len(frames_b64)})",
                                      face_detected=True, confidence=ref["confidence"], challenge_completed = False)

    challenge = {}
    if is_challenge:
        challenge = detect_blink(usable) if challenge_type == "blink" else check_head_turn(usable)
    challenge_ok = challenge.get("challenge_completed", True)
    event_index = challenge.pop("event_index", None)

    keys = pick_key_frames(len(usable), event_index) if challenge_ok else [0]
    verified = {}
    for k in keys:
        try:
            verified[k] = verify_frame(usable[k]["b64"], usable[k])
        except FrameRejected as e:
            if k == 0:
                return liveness_failed_result(str(e), face_detected=e.face_detected, confidence=e.confidence)
            skipped.append(usable[k]["frame_no"])
    ref_check = verified[0]

    for k, v in verified.items():
        if k and hamming_distance(ref_check["face_hash"], v["face_hash"]) > SAME_PERSON_HAMMING_MAX:
            return liveness_failed_result(f"Frame {usable[k]['frame_no']} shows a different face from frame 0", face_detected=True, confidence = ref["confidence"], challenge_completed = False)

    real = [v["real_probability"] for v in verified.values()]
    passive_score = min(ref_check["real_probability"], float(np.median(real)))

    liveness_score = round(passive_score if challenge_ok else min(passive_score, CHALLENGE_FAILED_SCORE_CAP), 2)
    liveness_passed = challenge_ok and passive_score >= LIVENESS_THRESHOLD
    ref_mesh = ref["mesh"]

    frame_info = {}
    if is_challenge:
        frame_info = {
            "frames_received" : len(frames_b64),
            "frames_used" : len(usable),
            "frames_skipped" : sorted(set(skipped)),
            "key_frames" : [usable[v]["frame_no"] for v in verified]
        }
    return{
        "liveness_passed" : liveness_passed,
        "liveness_score" : liveness_score,
        "face_embedding_hash" : ref_check["face_hash"],
        "details" : {
            "face_detected" : True,
            "face_detection_confidence" : ref["confidence"],
            "quality_score" : ref["quality_score"],
            "image_quality" : image_quality_label(ref["quality_score"]),
            "face_mesh_complete" : ref_mesh["face_mesh_complete"],
            "landmark_count" : ref_mesh["landmark_count"],
            "depth_detected" : ref_mesh["depth_quality"] != "poor",
            "depth_quality" : ref_mesh["depth_quality"],
            "nose_tip_z" : ref_mesh["nose_tip_z"],
            "eye_aspect_ratio" : ref_mesh["eye_aspect_ratio"],
            "head_yaw_deg" : ref_mesh["head_yaw_deg"],
            "texture_analysis_score" : round(passive_score, 2),
            "spoof_probability" : round(1.0 - passive_score, 2),
            "frame_real_probability" : [round(r,2) for r in real],
            **frame_info,
            **challenge,
            "spoof_suspected" : passive_score < LIVENESS_THRESHOLD,
            "model" : LIVENESS_MODEL,
            "threshold" : LIVENESS_THRESHOLD
        }
    }


def detect_vpn_proxy(ip_address: str, user_agent: str) -> tuple:
    """
    Detect VPN/proxy usage.

    TODO: Check for:
    - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
    - Localhost (127.x, ::1)
    - VPN keywords in user_agent
    - Known proxy headers (not available here, but could extend)

    Return (is_vpn: bool, confidence: float)
    """
    is_vpn = False
    confidence = 0.0

    ip = parse_ip(ip_address)
    if ip is not None and ip.is_private:
        is_vpn = True
        confidence = 0.7

    if user_agent:
      words = [word.strip("():,") for word in user_agent.lower().split()]
      if any(word.startswith(kw) for word in words for kw in VPN_KEYWORDS):
          is_vpn = True
          confidence = 0.8

    return is_vpn, confidence

def parse_ip(ip_address: Optional[str]):
    if not ip_address:
        return None
    try:
        return ipaddress.ip_address(ip_address.strip())
    except ValueError:
        return None

def liveness_risk(liveness_score: Optional[float]) -> tuple:
    recommendation = None
    if liveness_score is None:
        return MISSING_SIGNAL_RISK, recommendation
    if liveness_score < LIVENESS_THRESHOLD:
        recommendation = "Improve lighting and face visibility" 
    return 1.0 - liveness_score, recommendation

def face_match_risk(face_match_score: Optional[float]) -> tuple:
    recommendation = None
    if face_match_score is None:
        return MISSING_SIGNAL_RISK, recommendation
    if face_match_score < MATCH_THRESHOLD:
        recommendation = "Re-enroll face or improve image quality"
    return 1.0 - face_match_score, recommendation

def is_pem_public_key(key: str) -> bool:
    lines = [line.strip() for line in key.strip().splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    begin, body, end  =  lines[0], lines[1:-1], lines[-1]
    if not (begin.startswith("-----BEGIN ") and begin.endswith("PUBLIC KEY-----")):
        return False
    if not (end.startswith("-----END ") and end.endswith("PUBLIC KEY-----")):
        return False    
    try:
        base64.b64decode("".join(body), validate=True)
        return True
    except ValueError:
        return False

def device_risk(device_signature: Optional[str], device_public_key: Optional[str]) -> tuple:
    has_signature = bool(device_signature and device_signature.strip())
    has_key = bool(device_public_key and device_public_key.strip())   
    recommendation = None
    if not has_signature and not has_key:
        return MISSING_SIGNAL_RISK, recommendation

    risk = 0.0
    if not has_signature:
        risk += 0.5
    if not (has_key and is_pem_public_key(device_public_key)):
        risk +=0.5

    if risk >= DEVICE_RISK_THRESHOLD:
        recommendation = "Please try again on another device"
    return risk, recommendation 

def network_risk(ip_address: Optional[str], user_agent: Optional[str]) -> tuple:
    recommendation = None
    if not ip_address and not user_agent:
        return MISSING_SIGNAL_RISK, recommendation
    is_vpn, confidence = detect_vpn_proxy(ip_address, user_agent)
    risk = 0.0

    if is_vpn == True:
        risk = confidence
        recommendation = "Disable VPN for check-in"

    if ip_address and parse_ip(ip_address) is None:
        risk = max(risk, 0.6)

    return risk, recommendation


def geo_risk(geolocation: Optional[GeolocationData]) -> tuple:
    recommendation = None
    if geolocation is None:
        return MISSING_SIGNAL_RISK, recommendation

    accuracy = geolocation.accuracy
    if geolocation.latitude == 0 and geolocation.longitude == 0:
        risk = 0.9
    elif accuracy == 0 :
        risk = 0.9
    elif accuracy < GEO_TOO_PRECISE_M:
        risk = 0.3
    elif accuracy <= GEO_RADIUS_M:
        risk = 0.0
    elif accuracy <= 1000:
        risk = 0.5
    elif accuracy <= GEO_POOR_M:
        risk = 0.8
    else:
        risk = 1.0
    if risk >= GEO_RISK_THRESHOLD:
        recommendation = "Enable precise location services"
    return risk, recommendation

def risk_level_readable(risk_score: float) -> str:
    if risk_score < 0.3:
        return "LOW"
    if risk_score < 0.5:
        return "MEDIUM"
    if risk_score < 0.7:
        return "HIGH"
    return "CRITICAL"

# =============================================================================
# PRIVACY REQUIREMENTS (IMPORTANT!)
# =============================================================================
"""
Your implementation MUST follow these privacy requirements:

1. NO RAW IMAGES STORED
   - Process images in-memory only
   - Do not write images to disk
   - Do not send images to external APIs

2. HASH-ONLY STORAGE
   - Store only SHA-256 hashes (64 hex characters)
   - Hashes are one-way - cannot reconstruct face
   - Different faces must produce different hashes

3. EPHEMERAL PROCESSING
   - Clear image data after processing
   - No caching of raw biometric data
   - Use Python's memory management (del, gc.collect)

4. CONSENT TRACKING
   - Require camera_consent=True for enrollment
   - Log consent in audit trail (backend responsibility)

5. RESPONSE HYGIENE
   - Never include base64 image data in responses
   - Only return hashes, scores, and metadata
"""
