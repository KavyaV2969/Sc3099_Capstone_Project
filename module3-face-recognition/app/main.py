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
from facenet_pytorch import InceptionResnetV1
from io import BytesIO
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool 
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Literal

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
LIVENESS_WEIGHTS = {
    "depth" : 0.30, 
    "mesh" : 0.25,
    "texture" : 0.25,
    "color" : 0.20
}

FACE_MESH_LANDMARKS = 468
MESH_CROP_MARGIN = 0.5
DEPTH_FLAT_Z = 0.01
DEPTH_REAL_Z = 0.05

TEXTURE_BLUR_VAR = 50.0
TEXTURE_SHARP_VAR = 200.0
TEXTURE_MOIRE_VAR = 1000.0
SKIN_RATIO_FULL = 0.5
SKIN_CR_STD_FLAT = 3.0
SKIN_CR_STD_FULL = 7.0
SKIN_CR_RANGE = (133,173)
SKIN_CB_RANGE = (77,127)
SPOOF_CUE_FLOOR = 0.3
SPOOF_SCORE_CAP = 0.5

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



# =============================================================================
# MODEL LOADING ON APP STARTUP
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
    yield

app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk scoring service",
    version="1.0.0",
    lifespan= lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    challenge_response: str  # Base64 encoded image
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
            "/risk/assess":"POST - Multi-signal risk assessment"
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
        raise HTTPException(status_code=400, detail="Camera consent required!")

    result = await run_in_threadpool(process_enrollment, request.image)

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
        raise HTTPException(status_code=400, detail= "Invalid reference_template_hash (expected 64 hex characters)")

    result = await run_in_threadpool(
        process_verification, request.image, request.reference_template_hash
    )

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
    if request.challenge_type != "passive":
        raise HTTPException(status_code=400, detail=f"Challenge type '{request.challenge_type}' not supported yet! Use 'passive'!")

    result = await run_in_threadpool(process_liveness, request.challenge_response)

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

    return RiskAssessResponse(
        risk_score = risk_score,
        risk_level = risk_level_readable(risk_score),
        pass_threshold = risk_score < RISK_THRESHOLD,
        risk_threshold = RISK_THRESHOLD,
        signal_breakdown = {name: round(value, 2) for name, value in contributions.items()},
        recommendations = recommendations
    )


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
    - mediapipe.solutions.face_detection.FaceDetection
      (requires mediapipe==0.10.18 as pinned in requirements.txt; mediapipe
      >= 0.10.30 removed `mediapipe.solutions` in favour of `mediapipe.tasks`)
    - Return detection results with confidence scores

    Consider setting min_detection_confidence=0.5
    """
    mp_face_detection = mp.solutions.face_detection
    with mp_face_detection.FaceDetection(model_selection = 1, min_detection_confidence = 0.5) as face_detection:
        results = face_detection.process(image_array)

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
        embedding = facenet_model(tensor)

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
    mp_face_mesh = mp.solutions.face_mesh
    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=False, min_detection_confidence = 0.5) as face_mesh:
        results = face_mesh.process(image_array)

    if not results.multi_face_landmarks:
        return{
            "face_mesh_complete" : False, 
            "landmark_count" : 0,
            "in_frame_ratio" : 0.0,
            "nose_tip_z" : 0.0,
            "depth_quality" : "poor"
        }
    landmarks = results.multi_face_landmarks[0].landmark
    landmark_count = len(landmarks)

    in_frame = sum(1 for landmark in landmarks if 0 <= landmark.x <= 1 and 0 <= landmark.y <= 1)
    in_frame_ratio = in_frame / FACE_MESH_LANDMARKS

    nose_tip_z = landmarks[1].z

    if nose_tip_z < -DEPTH_REAL_Z:
        depth_quality = "good"
    elif abs(nose_tip_z) > DEPTH_FLAT_Z:
        depth_quality = "moderate"
    else:
        depth_quality = "poor"

    return {
            "face_mesh_complete" : landmark_count >= FACE_MESH_LANDMARKS and in_frame == landmark_count,     
            "landmark_count" : landmark_count,
            "in_frame_ratio" : round(in_frame_ratio, 2),
            "nose_tip_z" : round(nose_tip_z, 2),
            "depth_quality" : depth_quality
    }

def depth_score_from_z(nose_tip_z: float) -> float:
    score = (-nose_tip_z - DEPTH_FLAT_Z) / (DEPTH_REAL_Z - DEPTH_FLAT_Z)
    return round(min(1.0, max(0.0, score)), 2)

def crop_face_region (image_array, detection, margin: float):
    h,w = image_array.shape[:2]
    x0,y0,x1,y1 = bbox_to_pixels(detection["bounding_box"], w ,h)
    pad_x = int((x1 - x0) * margin)
    pad_y = int((y1-y0) * margin)
    return image_array[max(0, y0 - pad_y):min(h, y1 + pad_y), max(0, x0 - pad_x):min(w, x1 + pad_x)]

def analyse_texture(face_crop) -> float:
    gray = cv2.cvtColor(face_crop, cv2.COLOR_RGB2GRAY)
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if variance > TEXTURE_MOIRE_VAR:
        score = 1.0 - (variance - TEXTURE_MOIRE_VAR) / TEXTURE_MOIRE_VAR
    else:
        score = (variance - TEXTURE_BLUR_VAR) / (TEXTURE_SHARP_VAR - TEXTURE_BLUR_VAR)
    return round(min(1.0, max(0.0, score)), 2)

def analyse_skin_color(face_crop) -> float:
    ycrcb = cv2.cvtColor(face_crop, cv2.COLOR_RGB2YCrCb)
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    skin = (
        (cr >= SKIN_CR_RANGE[0]) & (cr <= SKIN_CR_RANGE[1]) &
        (cb >= SKIN_CB_RANGE[0]) & (cb <= SKIN_CB_RANGE[1])
    )

    skin_ratio = float(skin.mean())
    if skin_ratio == 0:
        return 0.0

    cr_std = float(cr[skin].std())
    ratio_score = min(1.0, skin_ratio / SKIN_RATIO_FULL)
    variance_score = min(1.0, max(0.0, (cr_std - SKIN_CR_STD_FLAT) / (SKIN_CR_STD_FULL - SKIN_CR_STD_FLAT)))
    return round(0.5 * ratio_score + 0.5 * variance_score, 2)

def liveness_failed_result(reason:str, face_detected: bool, confidence: float) ->  dict:
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
            "threshold" : LIVENESS_THRESHOLD,
            "reason" : reason
        }
    }

def process_liveness(image_b64: str) -> dict:
    image_array = None
    embedding = None
    face_crop = None
    try:
        image_array = decode_base64_image(image_b64)
        if image_array is None:
            raise HTTPException(status_code=400, detail="Invalid image data!")

        detection = detect_face(image_array)
        if not detection["detected"]:
            return liveness_failed_result("No face detected", face_detected=False, confidence = 0.0)

        confidence = round(detection["confidence"], 2)
        try:
            face_crop = crop_for_facenet(image_array, detection)
        except ValueError as e:
            return liveness_failed_result(str(e), face_detected=True, confidence = confidence)

        quality_score = compute_quality_score(detection["confidence"], image_array, detection["bounding_box"])
        if confidence < ENROLL_MIN_CONFIDENCE or quality_score < ENROLL_MIN_QUALITY:
            return liveness_failed_result(f"Face image quality too low (confidence {confidence:.2f}, quality {quality_score:.2f})", face_detected=True, confidence=confidence)

        mesh = analyze_face_mesh(crop_face_region(image_array, detection, MESH_CROP_MARGIN))
        depth_score = depth_score_from_z(mesh["nose_tip_z"])
        mesh_score = mesh["in_frame_ratio"]
        texture_score = analyse_texture(face_crop)
        color_score = analyse_skin_color(face_crop)

        liveness_score = round(
            LIVENESS_WEIGHTS["depth"] * depth_score + 
            LIVENESS_WEIGHTS["mesh"] * mesh_score +
            LIVENESS_WEIGHTS["texture"] * texture_score +
            LIVENESS_WEIGHTS["color"] * color_score, 2
        )

        spoof_suspected = texture_score < SPOOF_CUE_FLOOR or color_score < SPOOF_CUE_FLOOR
        if spoof_suspected:
            liveness_score = min(liveness_score, SPOOF_SCORE_CAP)

        embedding = extract_face_embedding(image_array, detection)
        face_hash = generate_face_hash(embedding)

        return{
            "liveness_passed" : liveness_score >= LIVENESS_THRESHOLD,
            "liveness_score" : liveness_score,
            "face_embedding_hash" : face_hash,
            "details" : {
                "face_detected" : True, 
                "face_detection_confidence" : confidence,
                "quality_score" : quality_score,
                "image_quality" : image_quality_label(quality_score),
                "face_mesh_complete" : mesh["face_mesh_complete"],
                "landmark_count" : mesh["landmark_count"],
                "depth_detected" : mesh["depth_quality"] != "poor",
                "depth_quality" : mesh["depth_quality"],
                "nose_tip_z" : mesh["nose_tip_z"],
                "depth_score" : depth_score,
                "mesh_score" : mesh_score, 
                "texture_analysis_score" : texture_score,
                "color_score" : color_score,
                "spoof_suspected" : spoof_suspected,
                "threshold" : LIVENESS_THRESHOLD
            }
        }
    finally:
        del image_array
        del embedding
        del face_crop




def detect_blink(face_mesh_landmarks):
    """
    Detect eye blink from face mesh landmarks (BONUS).

    TODO: Implement using:
    - Eye landmark indices (see MediaPipe docs)
    - Calculate Eye Aspect Ratio (EAR)
    - EAR < threshold indicates closed eye
    """
    pass


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
