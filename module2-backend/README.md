# Module 2 — Backend

The backend implements authentication, course/session/enrollment workflows,
bulk account activation, signed device proof, weighted check-in assessment,
review/appeal, retained attendance reporting/export, immutable auditing, privacy
cleanup and Prometheus metrics. See the
[completion contract](../docs/BACKEND-COMPLETION.md) and
[implementation report](../output/backend-completion-2026-09-29.md).

Backend implementation is complete for the agreed scope. Real biometric
integration remains blocked: the supplied Module 3 operations return 501 and
a functioning external implementation is required. Required face matching and evaluated biometric checks are
preserved; successful mocks do not certify real face-service interoperability.

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

Latest results (13 October 2026): 426 backend tests passed including PostgreSQL;
school public suite 77/77 backend points; 100 concurrent students checked in with
p95 latency under 1.4 s.
Required face checks must not be disabled to claim real biometric interoperability.
