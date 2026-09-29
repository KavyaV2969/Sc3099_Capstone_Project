# Module 2 — Backend

The backend implements authentication, course/session/enrollment workflows,
bulk account activation, signed device proof, weighted check-in assessment,
review/appeal, retained attendance reporting/export, immutable auditing, privacy
cleanup and Prometheus metrics. See the
[completion contract](../docs/BACKEND-COMPLETION.md) and
[implementation report](../output/backend-completion-2026-09-29.md).

Backend implementation is complete for the agreed scope. Real biometric
integration remains blocked: the supplied Module 3 operations return 501 and
a functioning external implementation is required. Enabled biometric checks are
preserved; successful mocks do not certify real face-service interoperability.

## Run and configure

From the repository root, copy `.env.example` to private ignored `.env` and
replace the deliberately invalid secret placeholder. Supply separate operator,
application and optional read-only dashboard database URLs. PostgreSQL password
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
The current canonical head is `20260929_0008`. Legacy recovery first verifies
the historical `20260928_0006` destination, then applies the normal forward
completion migrations. See the [recovery runbook](../docs/F00-DATABASE-RECOVERY.md).
`/health` requires database connectivity, exact frozen schema/ORM, enabled audit
integrity objects and Redis. It does not check biometric capability.

## Implemented API and behavior

OpenAPI is available at `/docs`; all API routes use `/api/v1`.

| Area | Supported operations |
|---|---|
| Authentication | Register, login, refresh, single-use activation |
| Users | Own profile/consent, face enrollment, deletion scheduling; scoped profile reads; admin directory/update |
| Courses | Authenticated list/read, admin create/update/soft delete |
| Enrollment | Current lists/rosters, single/bulk enrollment, secure optional account creation, withdrawal |
| Sessions | Create, list/discover/read, owner/admin update, guarded deletion, documented admin override |
| Check-ins | Eligibility/verification/scoring, own/scoped history, detail, appeal, staff review |
| Devices | Register/list/update/remove, key validation/revocation, signed check-in challenges |
| Reports | Overview/session/course/student statistics; CSV/JSON exports |
| Audit/operations | Admin audit querying; immutable storage; retention worker; `/health` and `/metrics` |

HS256 access tokens last one hour and refresh tokens seven days. Passwords use
bcrypt cost 10 by default. Refresh issues another pair without revoking the old
refresh token. Ten consecutive bad passwords block login, including attempt ten;
documented admin activation resets the counter. Grading rate limits are preserved.

Instructors read/review only courses assigned to them or containing sessions they
own. Course read/review permission does not grant mutation of another instructor's
session. Administrators retain access and assigned TAs retain documented course
permissions. CourseTA provisioning uses the idempotent operator SQL in the
completion contract; no unnecessary TA-management endpoint was added.

Check-ins require active course/student/enrollment/session/window, appropriate
consents, Singapore/local IP and GPS eligibility, and one record per student/session.
Enabled face/liveness checks require valid service evidence. Missing evidence
returns 400, dependency failure 503, and changed policy/reference hash 409, with
no attendance row. Valid failed verification persists a rejected check-in (201).
Clients must inspect returned status rather than count all 201 responses as success.
Five fixed risk weights and critical rejection rules are preserved. Unsigned
devices receive unknown-device risk; registered/trusted scoring requires verified
single-use key possession proof. Impossible travel flags review. The network
user-agent hint is a heuristic, not verified VPN detection.

Attendance rates use approved eligible students / retained historical roster,
never submissions. Reports disclose 30-day coverage and unknown denominators as
null; status/submission counts remain separate. Session dates use Asia/Singapore.
CSV formulas are neutralized and exports stream bounded batches. Mutation inputs
reject unsupported fields, nonblank QR input and oversized image/request data.
QR issuance, standalone attestation, duplicate risk-signal storage, extra metadata,
email delivery, refresh rotation/logout, paid network reputation and OTLP export
are intentionally deferred. Backend request IDs, trace-context propagation and
required metrics are implemented.

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

The final report records fresh full-suite, pinned Linux image, PostgreSQL/Redis,
migration/recovery, deployment/restart, Prometheus and 10/100-user HTTP evidence.
Do not disable verification flags to make the outstanding real biometric gate pass.

## Historical evidence

The dated sections below describe earlier states; the current contract above
takes precedence.

### Live Week 3 verification (2026-09-08)

The backend was rebuilt with `docker compose up -d --build backend`. PostgreSQL
is at migration `20260908_0002`; `alembic check` reports no schema differences.
The API, PostgreSQL, and Redis health checks pass. The backend test suite passes
inside the container: **81 passed**.

The live API smoke test passed using real JWT authentication, PostgreSQL, and
Redis. With a 100 m geofence, check-ins at 0 m, 150.11 m, and 300.23 m were stored
as approved, flagged, and rejected. Consent, inactive-session rejection,
duplicate rejection, and terminal session transitions were verified. All three
test sessions were closed, and their records were confirmed directly in PostgreSQL.

To repeat this check from `module2-backend`:

```powershell
python scripts/smoke_week3.py
```

The script creates three test accounts, one course/enrollment, and three closed
sessions per run, and leaves these records for inspection. It respects the
registration rate limit. Set `TEST_BACKEND_URL` to
target another local test API.

The selected public Course/Session/Check-in tests were attempted against the live
backend and stopped at the first setup error: `test_course` omits `instructor_id`
and receives 422. Public-suite compatibility is still outstanding; no supplied
test fixtures or ownership/consent requirements were changed to bypass that error.

## Run locally

1. Copy `.env.example` to `.env` and replace `SECRET_KEY` with a random value
   of at least 32 characters.
2. Start PostgreSQL and Redis from the repository root:

   ```powershell
   docker-compose up -d postgres redis
   ```

3. From this directory, apply the migration and run the API:

   ```powershell
   alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```

4. Open `http://localhost:8000/docs`.

The Docker backend runs `alembic upgrade head` automatically before Uvicorn
starts. `/health` checks the API, PostgreSQL, and Redis without exposing
credentials.

## Security controls

- `SECRET_KEY` is environment-sourced and must be at least 32 characters.
- Registration and login are each limited to 100,000 requests/hour/IP; protected
  API calls to 1000/hour/user.
- Missing, malformed, expired, incorrectly typed, or inactive-user tokens are
  rejected.
- Password fields and hashes never appear in API responses.
- Registration accepts all four roles because the supplied API specification and
  course test fixtures require it. Restrict privileged role provisioning before
  production deployment.

## Grading clarifications (September 2026)

- Login tracks consecutive wrong passwords per account in PostgreSQL. The tenth
  failure blocks login and returns 429; later attempts also return 429, even with
  the correct password or a different client IP. A successful login before
  blocking resets the counter. Attempts are serialized with a database row lock.
- Blocks have no automatic expiry. An administrator can unblock an account using
  the existing `PATCH /admin/users/{id}/activate` endpoint, which resets the counter.
  This is the chosen minimal recovery policy because the clarification does not
  specify a lock duration. Existing sessions are not revoked by this login rule.
- Migration `20260911_0003_login_lockout.py` adds `users.failed_login_attempts`,
  defaulting to zero for existing users. Apply it before running the updated API.
- The higher IP limits preserve Redis enforcement while accommodating grading.
  The existing 1,000 requests/hour/user API limit is unchanged.
- Check-in GPS must fall in the bundled Singapore land polygons, independently
  of the session geofence. See `app/data/README.md` for boundary source, date, and
  license. The dataset is a simplified snapshot, including mainland and islands.
- Client IP uses the first `X-Forwarded-For` value when present, otherwise the
  socket address. Private, loopback, and link-local addresses are allowed without
  lookup; malformed/reserved addresses are rejected. Local IPs do not bypass GPS.
- Public IP country is checked using `https://ipwho.is/{ip}` over HTTPS. Only the
  IP is sent, not account details or GPS. Successful country lookups are cached
  in Redis for 24 hours. Non-Singapore IPs/GPS return 403. A failed lookup returns
  503 and does not create a check-in. The free provider has a daily quota; repeated
  requests for the same IP use the cache. No API key or new Python package is needed.
  Provider documentation: https://ipwhois.io/documentation
- The clarified public total is 92 points. Supplied grading tests/scoring files
  have not been modified; passing older backend tests is not a claim of 92 points.

Verified on 2026-09-11 after rebuilding the backend: **120 backend tests passed**
inside Docker and **6 selected public authentication/rate-limit tests passed**.
Migration `20260911_0003` is applied and `alembic check` reports no schema drift.
The live smoke test additionally verified rejection of Johor GPS with a local IP,
rejection of public non-Singapore IP `8.8.8.8` supplied first in `X-Forwarded-For`,
blocking after ten wrong passwords across different IPs, correct-password rejection
while blocked, and successful login after admin activation. The smoke test now
needs the public-IP lookup provider or an existing cached country result.


## Updated NTULearn starter (September 2026)

The supplied starter removes required course-level instructor fields and makes
`PUT /courses/{id}` admin-only. Course `instructor_id` remains an optional nullable
extension, explicitly allowed by the updated spec, so existing assignments are
preserved. Supplied assignments still restrict session creation to that instructor;
unassigned courses allow different instructors to create their own sessions.

Session ownership remains `sessions.instructor_id`. Instructor session lists use
that owner, and an instructor may manage enrollment/rosters for a course through
an existing session they own or the optional course assignment. Admins may enroll
students before any session exists. TA assignments retain their existing behavior.
Own-enrollment responses no longer depend on or return an instructor name.

Migration `20260911_0004_optional_course_instructor.py` only makes the existing
course FK nullable; it does not drop assignments. Before downgrading this migration,
all unassigned courses must be assigned an instructor.

The updated API/database specs are copied from the supplied starter. The regenerated
endpoint reference is retained in `app/main.py`, alongside the working routers and
health checks. Module 3 and the shared test requirements adopt the supplied
MediaPipe 0.10.18, NumPy <2 and OpenCV <4.12 constraints; Module 3 also adopts the
supplied `libgl1` Docker fix and explanatory comments. Module 1 is unchanged.

Verified after the update: 122 backend tests passed; all four public course/session
tests passed (8/8 points for that selection). Docker startup applied migration
`20260911_0004` to PostgreSQL, and `alembic check` found no schema differences.
The full public suite was not rerun for this update.


## Check-in verification repair (28 September 2026)

All new check-ins use one weighted scorer. Enabled biometrics require a nonblank
image and strict service results; valid failures persist rejected attendance,
while missing evidence or dependency failures create no check-in. Finalization
refreshes locked eligibility and returns 409 if verification policy changed.
New course risk defaults honor RISK_SCORE_THRESHOLD; existing thresholds persist.
See [verification contract and rollout](../docs/CHECKIN-VERIFICATION-REPAIR.md).

For complete PostgreSQL regression checks, set F00_POSTGRES_TEST_URL and
F00_BACKUP_MANIFEST. Set F00_POSTGRES_CONTAINER to the PostgreSQL container name
when pg_restore runs through Docker; otherwise install the PostgreSQL client tools.
Recovery tests restore the immutable dump into fresh disposable databases and do
not modify the operator's committed rehearsal.
