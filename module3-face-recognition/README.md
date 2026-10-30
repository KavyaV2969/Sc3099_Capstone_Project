# Module 3 — Face Recognition & Risk Service

FastAPI service for the SC3099 attendance system (Group 4). It handles face enrollment, 1:1 face verification, liveness detection (anti-spoofing + blink / head-turn challenges) and multi-signal risk scoring.

- **Port:** `8001`
- **Run (from `app/`):** `uvicorn main:app --host 0.0.0.0 --port 8001`
- **Models (loaded once at startup):** MediaPipe Face Detection + Face Mesh, FaceNet `InceptionResnetV1` (vggface2) for embeddings, MiniFASNetV2 (uniface) for anti-spoofing
- **Privacy:** images are decoded and processed in memory only and deleted after each request. Nothing is written to disk. Faces are stored only as a 256-bit **SimHash** of the FaceNet embedding (64 hex chars), never as images or raw embeddings.

> The first request after startup can be slower while the models warm up.

---

## Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/` | Lists endpoints |
| POST | `/face/enroll` | Enroll a face and return its template hash |
| POST | `/face/verify` | Compare a face to an enrolled template hash |
| POST | `/face/match` | Legacy alias of `/face/verify` |
| POST | `/liveness/check` | Liveness detection (passive / blink / head_turn) — **see the detailed section below** |
| POST | `/risk/assess` | Weighted risk score from liveness, match, device, network and geolocation |
| GET | `/metrics` | Prometheus metrics |

All images are **base64-encoded strings**, either plain base64 or the bytes of a JPEG/PNG. Max decoded size is **10 MB**.

---

## `POST /liveness/check`

### Request

```json
{
  "challenge_response": "<base64 image>"  or  ["<frame 0>", "<frame 1>", ...],
  "challenge_type": "passive" | "blink" | "head_turn"
}
```

| Field | Type | Notes |
|---|---|---|
| `challenge_response` | string **or** list of strings | One image, or a list of **1–30** frames in capture order. |
| `challenge_type` | `"passive"` (default), `"blink"`, `"head_turn"` | Anything else returns **422**. |

- **`passive`** uses only the first image. Extra frames are ignored.
- **`blink` / `head_turn`** with **2+ usable frames** use **multi-frame mode**: the service looks for the actual movement across the sequence.
- **`blink` / `head_turn`** with **only 1 usable frame**, whether one image was sent or the other frames were unusable, use **single-frame mode**: that one frame is checked with fixed thresholds (see below).

The frontend currently captures about 24 frames over about 5 seconds (~5 fps).

### How the result is decided

Two checks are combined:

1. **Anti-spoof model (MiniFASNetV2).** Every key frame gets a probability of being a real face. Printed photos and screen replays score low.
   `passive_score = min(real probability of frame 0, median real probability of all key frames)`
2. **Challenge**, for blink / head_turn only. Did the user actually blink or turn their head?

```
liveness_passed = challenge_completed AND passive_score >= 0.60
liveness_score  = passive_score                     if the challenge was completed (or passive)
                = min(passive_score, 0.30)          if the challenge failed
```

So a **failed challenge always gives a score of at most 0.30**, even for a real face, and `liveness_passed` is `false`.

**Key frames.** The anti-spoof model and FaceNet don't run on every frame (that would be slow). They run on frame 0, the frame where the blink or turn happened, and 4 evenly spaced frames. Each key frame's face hash is compared to frame 0. If one differs by more than 80 of 256 bits, the request fails as **a different face**, which stops someone swapping people mid-sequence. If the challenge fails, only frame 0 is analysed.

### Challenge rules

#### Blink — multi-frame

The thresholds are **relative to the user's own eyes**, so people with narrow or wide eyes are treated fairly.

| Step | Rule |
|---|---|
| Baseline | `open_level` = highest EAR (eye aspect ratio) in the sequence |
| Eyes open | Frame EAR ≥ **0.80 × open_level** |
| Eyes closed | Frame EAR ≤ **0.60 × open_level** |
| Blink | A **closed** frame with at least one **open** frame before it **and** after it (open → closed → open) |
| Sanity check | `open_level` must be ≥ **0.15**, otherwise "Eyes never clearly open" (sunglasses, squinting, etc.) |

Example: if the most-open frame is 0.313, a frame counts as closed at EAR ≤ 0.188.

#### Head turn — multi-frame

| Rule | Value |
|---|---|
| Turn detected when the yaw range across frames (max yaw − min yaw) is | ≥ **20°** |
| `head_turn_direction` | Direction of the largest turn relative to frame 0: `image_right` or `image_left` (image orientation, not the user's left/right) |

#### Single-frame mode (blink / head_turn with only 1 usable frame)

One frame can't show movement, so the frame itself must **show the action**. This is controlled by `SINGLE_FRAME_REQUIRE_ACTION = True`.

| Challenge | Passes the challenge when | Typical values |
|---|---|---|
| blink | EAR **< 0.18** (eyes closed) | Open eyes measured 0.19–0.35 on test faces |
| head_turn | \|yaw\| **≥ 20°** (head turned) | Frontal faces measured within ±13° |

So an ordinary frontal photo with open eyes **fails** a single-frame blink or head_turn: the challenge isn't completed and the score is capped at 0.30. If `SINGLE_FRAME_REQUIRE_ACTION` is set to `False`, any single frame passes the challenge and the anti-spoof model alone decides.

### Response

```json
{
  "liveness_passed": true,
  "liveness_score": 0.94,
  "liveness_threshold": 0.6,
  "challenge_type": "blink",
  "face_embedding_hash": "6fa38084da41...b4d7a3a5",
  "details": { ... }
}
```

#### Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `liveness_passed` | bool | **The field to gate on.** `true` only if the challenge (if any) was completed **and** the anti-spoof score ≥ 0.60. |
| `liveness_score` | float 0–1 | Confidence that this is a live person. Capped at 0.30 if the challenge failed, and `0.0` on early failures (no face, etc.). Pass this into `/risk/assess` as `liveness_score`. |
| `liveness_threshold` | float | Always `0.6`. |
| `challenge_type` | string | Echo of the request. |
| `face_embedding_hash` | string | 64-hex SimHash of the face in frame 0, same format as the enrollment `face_template_hash`. Empty string `""` on early failures. |
| `details` | object | Diagnostics, described below. Which keys appear depends on the mode. |

#### `details` — always present on a completed analysis

| Field | Type | Meaning |
|---|---|---|
| `face_detected` | bool | A face was found in frame 0. |
| `face_detection_confidence` | float | MediaPipe detection confidence for frame 0. Must be ≥ 0.70. |
| `quality_score` | float 0–1 | `0.5×confidence + 0.2×resolution (vs 640×480) + 0.3×face size (full marks at ≥15% of frame)`. Must be ≥ 0.50 for frame 0. |
| `image_quality` | string | `good` (≥ 0.75), `acceptable` (≥ 0.50), `poor` |
| `face_mesh_complete` | bool | All face-mesh landmarks found and inside the frame. |
| `landmark_count` | int | Usually **478** (468 face landmarks + 10 iris landmarks). |
| `depth_detected` | bool | `depth_quality != "poor"`. **Informational only, not used in pass/fail.** |
| `depth_quality` | string | From `nose_tip_z`: `good` (< −0.05), `moderate` (\|z\| > 0.01), `poor` (flat) |
| `nose_tip_z` | float | MediaPipe relative depth of the nose tip. More negative means more 3-D. |
| `eye_aspect_ratio` | float | EAR of frame 0 (average of both eyes). Open eyes are about 0.2–0.35, closed below about 0.15. |
| `head_yaw_deg` | float | Head yaw of frame 0 in degrees. About 0 means facing the camera. |
| `texture_analysis_score` | float | The anti-spoof `passive_score` (named this for the spec). |
| `spoof_probability` | float | `1 − passive_score` |
| `frame_real_probability` | list[float] | Anti-spoof "real" probability for each key frame, in key-frame order. |
| `spoof_suspected` | bool | `passive_score < 0.60`. If this is `true`, the anti-spoof model is why it failed. |
| `model` | string | `"MiniFASNetV2 (uniface)"` |
| `threshold` | float | `0.6` |

#### `details` — extra fields for blink / head_turn

| Field | Type | Meaning |
|---|---|---|
| `challenge_mode` | string | `"multi_frame"` or `"single_frame"` |
| `challenge_completed` | bool | Whether the blink or turn was detected. If `false`, the challenge is why it failed. |
| `challenge_reason` | string | Human-readable explanation (see the table below). |
| `frames_received` | int | Frames in the request. |
| `frames_used` | int | Frames where a face and landmarks were found. |
| `frames_skipped` | list[int] | Frame indices dropped (no face, face too small, no landmarks, or failed anti-spoof preprocessing). |
| `key_frames` | list[int] | Frame indices the anti-spoof and FaceNet checks ran on. |
| **blink only:** `eye_aspect_ratios` | list[float] | EAR per usable frame. The blink shows up as a dip. |
| **blink, single-frame only:** `eye_state` | string | `"open"` or `"closed"` |
| **head_turn only:** `head_yaw_degrees` | list[float] | Yaw per usable frame. |
| **head_turn only:** `head_turn_direction` | string \| null | `image_right` / `image_left`, or `null` if no turn. |
| **head_turn, single-frame only:** `head_pose` | string | `"frontal"` or `"turned"` |

#### `details` — early failures

If the request fails before the analysis finishes (no face in frame 0, low quality, different face in a key frame), the response is still **HTTP 200** with:

```json
{
  "liveness_passed": false,
  "liveness_score": 0.0,
  "face_embedding_hash": "",
  "details": {
    "face_detected": false,
    "face_detection_confidence": 0.0,
    "face_mesh_complete": false,
    "depth_detected": false,
    "texture_analysis_score": 0.0,
    "spoof_suspected": true,
    "model": "MiniFASNetV2 (uniface)",
    "threshold": 0.6,
    "reason": "No face detected in frame number 0!"
  }
}
```

Note: early failures use **`reason`**, while a completed challenge uses **`challenge_reason`**. `spoof_suspected: true` here is a safe default and doesn't mean the anti-spoof model ran.

### Reason strings

| Message | Where | Meaning / what to do |
|---|---|---|
| `Blink detected at frame N` | challenge_reason | Pass (if the anti-spoof score is also ≥ 0.6) |
| `No blink detected` | challenge_reason | No open → closed → open pattern. Usually the blink was too fast or too partial for the frame rate. Retry. |
| `Eyes closed but never open before or after blink detected` | challenge_reason | Blinked at the very start or end of the capture. Retry. |
| `Eyes never clearly open` | challenge_reason | Highest EAR < 0.15 (glasses glare, squinting, eyes occluded) |
| `Head turned X degrees` | challenge_reason | Pass (if the anti-spoof score is also ≥ 0.6) |
| `Head turn too small (X < 20 degrees)` | challenge_reason | Ask the user to turn further |
| `Single frame: eyes closed (...), blink captured` | challenge_reason | Single-frame blink pass |
| `Single frame: eyes open (...), no blink captured` | challenge_reason | Single-frame blink fail |
| `Single frame: head turned (...), head turn captured` | challenge_reason | Single-frame head turn pass |
| `Single frame: head frontal (...), no head turn captured` | challenge_reason | Single-frame head turn fail |
| `No face detected in frame number 0!` | reason | First frame has no face |
| `Face too small in frame 0 (WxHpx)` | reason | Face under 40 px. Move closer. |
| `Face image quality too low in frame 0 (...)` | reason | Confidence < 0.70 or quality < 0.50. Improve lighting or framing. |
| `Face landmarks not found in frame 0` | reason | Face mesh failed on the first frame |
| `Frame N shows a different face from frame 0` | reason | A different person appeared mid-sequence. Treat as suspicious. |

### HTTP errors

| Status | When |
|---|---|
| 200 | Normal result, **including failed liveness**. Always check `liveness_passed`. |
| 400 | `Invalid image data in frame number N!` (bad base64 / not an image, in **any** frame) or `Image too large` (> 10 MB) |
| 422 | Validation: unknown `challenge_type`, empty list, or more than 30 frames |

### Examples

**Multi-frame blink — pass** (24 frames, blinks at frames 5, 12 and 19):

```json
{
  "liveness_passed": true,
  "liveness_score": 0.94,
  "liveness_threshold": 0.6,
  "challenge_type": "blink",
  "face_embedding_hash": "6fa38084da419660343930116f59721871d9c1a7a1ee392a6ef69b47b4d7a3a5",
  "details": {
    "face_detected": true,
    "face_detection_confidence": 0.95,
    "quality_score": 0.87,
    "image_quality": "good",
    "face_mesh_complete": true,
    "landmark_count": 478,
    "depth_detected": true,
    "depth_quality": "good",
    "nose_tip_z": -0.11,
    "eye_aspect_ratio": 0.298,
    "head_yaw_deg": 3.01,
    "texture_analysis_score": 0.94,
    "spoof_probability": 0.06,
    "frame_real_probability": [1.0, 0.99, 0.94, 0.91, 0.92],
    "frames_received": 24,
    "frames_used": 24,
    "frames_skipped": [],
    "key_frames": [0, 6, 12, 17, 23],
    "challenge_completed": true,
    "challenge_reason": "Blink detected at frame 12",
    "eye_aspect_ratios": [0.298, 0.305, 0.298, 0.313, 0.306, 0.183, 0.204, 0.252, "...", 0.288],
    "challenge_mode": "multi_frame",
    "spoof_suspected": false,
    "model": "MiniFASNetV2 (uniface)",
    "threshold": 0.6
  }
}
```

**Single-frame blink — pass** (one image, eyes closed):

```json
"details": {
  "eye_aspect_ratio": 0.177,
  "frame_real_probability": [0.94],
  "frames_received": 1,
  "frames_used": 1,
  "key_frames": [0],
  "challenge_completed": true,
  "challenge_reason": "Single frame: eyes closed (EAR 0.177, closed_below 0.18), blink captured",
  "challenge_mode": "single_frame",
  "eye_aspect_ratios": [0.177],
  "eye_state": "closed"
}
```

**Real face, challenge failed** (`liveness_passed: false`, score capped at 0.3 even though the anti-spoof model says real):

```json
{
  "liveness_passed": false,
  "liveness_score": 0.3,
  "details": {
    "frame_real_probability": [1.0],
    "spoof_suspected": false,
    "challenge_completed": false,
    "challenge_reason": "No blink detected",
    "challenge_mode": "multi_frame"
  }
}
```

**Printed photo / screen** (`spoof_suspected: true`, low score whatever the challenge result):

```json
{
  "liveness_passed": false,
  "liveness_score": 0.11,
  "details": {
    "texture_analysis_score": 0.11,
    "spoof_probability": 0.89,
    "spoof_suspected": true
  }
}
```

### Reading a failure quickly

1. `reason` present → failed early (no face, quality, different face). Read the message.
2. `challenge_completed: false` → the user didn't blink or turn enough. Check `eye_aspect_ratios` / `head_yaw_degrees`.
3. `spoof_suspected: true` → the anti-spoof model thinks it's a photo or screen.

### Liveness configuration (`main.py`)

| Constant | Value | Used for |
|---|---|---|
| `LIVENESS_THRESHOLD` | 0.6 | Minimum anti-spoof score to pass |
| `CHALLENGE_FAILED_SCORE_CAP` | 0.3 | Max score when a challenge fails |
| `MAX_CHALLENGE_FRAMES` | 30 | Max frames per request |
| `KEY_FRAME_SAMPLES` | 4 | Evenly spaced key frames (plus frame 0 and the event frame) |
| `BLINK_OPEN_RATIO` | 0.8 | Multi-frame: open if EAR ≥ 0.8 × max EAR |
| `BLINK_CLOSED_RATIO` | 0.6 | Multi-frame: closed if EAR ≤ 0.6 × max EAR |
| `EAR_MIN_OPEN` | 0.15 | Multi-frame: max EAR must reach this |
| `HEAD_TURN_MIN_DEG` | 20 | Multi-frame: yaw range needed |
| `SINGLE_FRAME_REQUIRE_ACTION` | True | Single frame must show closed eyes / turned head |
| `SINGLE_FRAME_EAR_CLOSED` | 0.18 | Single frame: closed if EAR < this |
| `SINGLE_FRAME_TURN_DEG` | 20 | Single frame: turned if \|yaw\| ≥ this |
| `SAME_PERSON_HAMMING_MAX` | 80 | Max hash-bit difference between key frames and frame 0 |
| `ENROLL_MIN_CONFIDENCE` / `ENROLL_MIN_QUALITY` | 0.7 / 0.5 | Quality gate on frame 0 |
| `MIN_FACE_SIZE_PX` | 40 | Minimum face width and height |

---

## Other endpoints (summary)

### `POST /face/enroll` → 201

```json
{ "user_id": "U123", "image": "<base64>", "camera_consent": true }
```

Response: `enrollment_successful`, `face_template_hash` (64 hex chars, **store this**), `quality_score`, and `details` (`face_detected`, `face_detection_confidence`, `image_quality`).
**400** for: no consent, invalid image, no face, confidence < 0.7 or quality < 0.5, face too small.

### `POST /face/verify` → 200

```json
{ "image": "<base64>", "reference_template_hash": "<64 hex from enrollment>" }
```

Response: `match_passed`, `match_score` (0–1), `match_threshold` (0.7), `face_detected`, `current_template_hash`.
The score comes from the Hamming distance between the two SimHashes: ≤ 60 differing bits maps to ≥ 0.70 (match), and about 128 bits (random faces) maps to 0.
No face found → 200 with `face_detected: false`, `match_score: 0`. **400** for a malformed reference hash or invalid image.

`POST /face/match` is a legacy alias: request `{image, reference_hash}`, response `{match_passed, match_score, face_embedding_hash}`.

### `POST /risk/assess` → 200

All fields are optional: `liveness_score`, `face_match_score`, `device_signature`, `device_public_key` (PEM), `ip_address`, `user_agent`, `geolocation {latitude, longitude, accuracy}`.

| Signal | Weight | Risk (0 safe – 1 risky) |
|---|---|---|
| liveness | 0.25 | `1 − liveness_score` |
| face_match | 0.25 | `1 − face_match_score` |
| device | 0.20 | +0.5 if no signature, +0.5 if the key is missing or not a valid PEM public key |
| network | 0.15 | 0.7 private IP, 0.8 VPN/proxy/tunnel/tor in the user agent, 0.6 invalid IP |
| geolocation | 0.15 | 0 at 10–100 m accuracy, 0.3 if < 10 m (suspiciously precise), 0.5 up to 1 km, 0.8 up to 5 km, 1.0 beyond; 0.9 for (0,0) or accuracy 0 |

Any missing signal counts as **0.5 risk**. `signal_breakdown` shows each signal's **weighted** contribution, so the values add up to `risk_score`.
Levels: `LOW` < 0.3 ≤ `MEDIUM` < 0.5 ≤ `HIGH` < 0.7 ≤ `CRITICAL`. `pass_threshold = risk_score < 0.5`.

---

## Notes for backend integration

- **Gate on `liveness_passed`, not on the HTTP status.** Liveness failures return 200.
- Forward `liveness_score` and `match_score` into `/risk/assess`.
- Store only `face_template_hash` from enrollment. The service never returns images.
- Log `details.challenge_reason` / `details.reason` for debugging. They contain no biometric data.
