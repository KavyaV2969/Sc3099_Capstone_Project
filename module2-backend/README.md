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
The current canonical head is `20260929_0009`. Legacy recovery first verifies
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

HS256 access tokens last one hour and refresh tokens seven days. Passwords use
bcrypt cost 10 by default. Refresh issues another pair without revoking the old
refresh token. Ten consecutive bad passwords block login, including attempt ten;
documented admin activation resets the counter. Grading rate limits are preserved.

Instructors read all student/course data. Enrollment writes and reviews require
a teaching relationship, and session mutation still requires ownership/admin. Administrators retain access and assigned TAs retain documented course
permissions. CourseTA provisioning uses the idempotent operator SQL in the
completion contract; no unnecessary TA-management endpoint was added.

Check-ins require active course/student/enrollment/session/window, Singapore/local
IP and GPS eligibility, and one record per student/session. Coordinates authorize
only that attempt without changing stored GPS consent. Accuracy is optional/null;
unknown accuracy increases geolocation risk and skips travel inference. Liveness
runs only when requested with camera consent and a nonblank image, otherwise null
results/zero contribution. Required face matching remains strict. Missing required evidence
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
Date ranges with no retained overlap return 422. Explicit session exports use
that eligible retained session rather than the course report's default date bounds.
Administrative reactivation includes newly eligible students in known active
rosters; closed and unknown historical rosters remain intact.
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

The release report records full-suite, PostgreSQL/Redis, migration/recovery,
deployment, Prometheus and 10/100-user HTTP evidence. The selected external
backend tests recorded 66 passes and one supplied skip.
Required face checks must not be disabled to claim real biometric interoperability.
See the [current release report](../output/backend-handover-fixes-2026-09-29.md)
for the latest results and the [completion contract](../docs/BACKEND-COMPLETION.md)
for the accepted public-test behavior.
