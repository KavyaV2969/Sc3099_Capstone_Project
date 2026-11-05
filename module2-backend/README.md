# Module 2 — Backend

The backend implements authentication, course/session/enrollment workflows,
bulk account activation, signed device proof, weighted check-in assessment,
review/appeal, retained attendance reporting/export, immutable auditing, privacy
cleanup and Prometheus metrics. See the
[completion contract](../docs/BACKEND-COMPLETION.md) and
[implementation report](../output/backend-completion-2026-09-29.md).

Required face matching and evaluated biometric checks are preserved. Module 3
supports single-image and multi-frame liveness; backend HTTP-contract tests do
not certify real camera/model accuracy or inference latency.

## Run and configure

`docker compose up -d` works from a clean clone: Compose supplies local-development
defaults for every credential. For any shared deployment, copy `.env.example` to
private ignored `.env` and replace every password and the JWT secret (separate
operator, application and read-only dashboard database URLs). PostgreSQL password
changes require explicit role rotation for an existing database; changing the
container environment alone does not rotate the stored password.

```powershell
docker compose up -d --build postgres redis backend
```

The migration job applies canonical migrations and provisions restricted roles
before starting the application. The backend never receives operator credentials.
Published ports are loopback-only: backend 8000, PostgreSQL 5434, Redis 6380.
Preserve existing volumes; `REDIS_VOLUME_NAME` supports an existing data volume.
The browser build-time API base must include `http://localhost:8000/api/v1`.
Set `FACE_SERVICE_URL` to the real service when available. For host-side tooling
use explicit `127.0.0.1` database/Redis URLs to avoid Windows IPv6 fallback delays.

The production image includes the complete recovery/verification source set.
The current canonical head is `20261013_0010`. Legacy recovery first verifies
the historical `20260928_0006` destination, then applies the normal forward
completion migrations. See the [recovery runbook](../docs/F00-DATABASE-RECOVERY.md).
`/health` is a fast liveness probe (database `SELECT 1` and Redis ping); it reports
the startup schema verdict in `schema` but never fails on drift. `/health/schema`
runs the full frozen schema/ORM/audit-trigger verification and returns 503 on drift.
Neither checks biometric capability.

## Implemented API and behavior

OpenAPI is available at `/docs`; all API routes use `/api/v1`.

| Area | Supported operations |
|---|---|
| Authentication | Register, login, refresh, single-use activation |
| Users | Own profile/consent, face enrollment, deletion scheduling; instructor student-profile reads; admin directory/update |
| Courses | Public metadata list, authenticated detail, admin create/update/soft delete |
| Enrollment | Current lists/rosters, single/bulk enrollment, secure optional account creation, withdrawal |
| Sessions | Create, list/discover/read, owner/admin update, guarded deletion, documented admin override |
| Check-ins | Eligibility/verification/scoring, own/scoped history, detail, appeal, staff review |
| Devices | Register/list/update/remove, key validation/revocation, signed check-in challenges |
| Reports | Overview/session/course/student statistics; CSV/JSON exports |
| Audit/operations | Admin audit querying; immutable storage; retention worker; `/health` and `/metrics` |

Every endpoint in the school's API specification is implemented. Where behavior differs
from or extends the school documents, the reason is recorded in
[BACKEND-DEVIATIONS.md](../docs/BACKEND-DEVIATIONS.md); the coordinator's announcements are in
[GRADING-CLARIFICATIONS.md](../docs/GRADING-CLARIFICATIONS.md). In summary:

- **Authentication.** HS256 access tokens last one hour and refresh tokens seven days;
  bcrypt cost 10. Ten consecutive failed passwords return 401 and block the account;
  further attempts return 429 until an admin reactivates it. `POST /auth/logout` revokes
  the presented tokens.
- **Check-ins** require an active session within its window, an active enrollment, GPS
  inside Singapore and a Singapore or private client IP (offline APNIC data). Biometric
  failure or GPS beyond twice the geofence rejects; risk >= 0.70 rejects; risk >= the
  session threshold flags. Outside the geofence, unregistered or shared devices and
  impossible travel also flag for review. Session-requested liveness without a usable
  image counts as maximum liveness risk and is flagged. Clients must read `status` rather than treat
  every 201 as approved.
- **Roles.** Instructors and TAs read attendance for every course; session changes need
  ownership, and reviews need a teaching relationship or an admin-assigned TA
  (`PUT /admin/courses/{course_id}/tas/{ta_id}`).
- **Reports** use roster snapshots (falling back to current enrollment), cover the 30-day
  retention window and always return numeric rates. Each risk factor is also stored in
  `risk_signals`.
- **Errors** are `{"detail", "code"}`; unknown request fields are ignored; names reject
  HTML markup and prose is stored escaped.

## Multi-frame liveness

`POST /api/v1/checkins/` and `POST /api/v1/devices/{device_id}/challenge`
accept the existing check-in fields plus:

```json
{
  "liveness_challenge_response": ["<base64 frame 0>", "<base64 frame 1>"],
  "challenge_type": "blink"
}
```

- `liveness_challenge_response` remains optional and accepts the existing single
  image string, or **1–30 nonblank image strings in capture order**. Empty lists,
  lists over 30 frames, invalid frame types and oversize frames return 422 before
  calling Module 3. The existing decoded-image limit is 10 MiB per frame; the
  entire JSON request still must fit within **16 MiB** (otherwise 413).
- `challenge_type` accepts `passive`, `blink`, or `head_turn`, defaulting to
  `passive` for old clients. Invalid values return 422.
- The backend forwards the whole sequence and challenge type to Module 3's
  `/liveness/check`. Face matching sends only frame 0 to `/face/verify`.
  Passive liveness uses only frame 0 in Module 3.
- Recommended frontend capture: **blink at 8 fps for 3 seconds (24 frames)**;
  **head turn at 5 fps for 5 seconds (25 frames)**. Capture consecutive frames
  through the action, without exceeding 30; the backend cannot infer fps or
  duration from base64 images. Compress/resize frames to fit the total body limit.
- Request device proof using the same sequence and challenge type as the final
  check-in. The signature binds every frame, their order and the challenge type;
  default passive proofs retain the existing payload hash.
- A Module 3 HTTP 200 may report `liveness_passed: false`; this still rejects the
  attendance attempt. Raw frames are neither stored nor logged. Existing camera
  consent, face enrollment, session policy and risk rules still apply.

The existing `FACE_SERVICE_TIMEOUT_SECONDS` setting defaults to 5 seconds.
Measure multi-frame inference on the target hardware and configure this timeout
if necessary; valid frame counts do not guarantee inference finishes in 5 seconds.

## Automatic SC3099 database population

From the repository root:

```powershell
docker compose up -d --build
```

Docker automatically populates PostgreSQL when the backend starts, after the
existing migration service completes. No separate population command or database
import is needed. This creates `SC3099 - Capstone Project`, a demo
admin, instructor and student (`demo.admin@example.com`,
`demo.instructor@example.com`, `demo.student@example.com`), the student's
enrollment, an active lecture today and a scheduled lab tomorrow. The course
venue is NTU (1.3483, 103.6831) with a 100 m geofence. The lecture's check-in window
opens immediately and lasts about 3 hours. Dates use Singapore calendar days.

A random initial password is printed in the backend's Docker logs for newly
created accounts only. Set `SAIV_DEMO_PASSWORD` in the backend container's
environment to choose one instead (the
existing registration password rules apply). Existing passwords, consent,
enrollments and sessions are preserved. Once SC3099 exists, subsequent startups
skip population entirely: they never reopen sessions, reset passwords or insert
additional daily sessions. A pre-existing SC3099 course is also left untouched,
including its name, ownership and active status. On a database without SC3099,
a conflicting demo account aborts the transaction without partial changes.
Population uses existing tables and audit helpers; no schema migration or volume
reset is needed. Each teammate gets these records in their own PostgreSQL volume.

Both session types require face matching and liveness. Sign in as the demo
student, grant camera consent, enroll a real face and register a device through
the normal app flow. The seed never fabricates biometric hashes, consent or
verified attendance.

## Verification

From `module2-backend`, use the repository Python 3.11 virtual environment and
set private `DATABASE_URL`, `F00_POSTGRES_TEST_URL`, `REDIS_URL`, `SECRET_KEY`,
`F00_BACKUP_MANIFEST` and, for Docker restore transport, `F00_POSTGRES_CONTAINER`.
Use an operator URL only for the isolated PostgreSQL test database factory;
ordinary application tests can use the restricted role. Backups contain private
data and remain ignored. Disable the cleanup worker during the test process.

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```

Latest results (6 November 2026): all 476 backend tests passed, including
PostgreSQL and verified legacy-backup recovery. Public tests passed 81 backend
checks (77/77 points; one explicitly skipped concurrency test) and 15 face-service
checks. All 42 dashboard tests and the frontend production build also passed.
The production Module 2 client was checked against Module 3 with 24-frame blink
and 25-frame head-turn requests; static sequences correctly failed both challenges.
Required face checks must not be disabled to claim real biometric interoperability.
