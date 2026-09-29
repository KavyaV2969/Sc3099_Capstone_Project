# Module 2 implementation completion — 29 September 2026

> **Historical evidence:** Current status and policy are superseded by the user-approved
> [reduced-contract implementation and release report](backend-reduced-contract-2026-09-29.md).
> The earlier remaining-conflict claims below describe the policy before those reductions.

**Later public-test compatibility update:** Minimal documented consumer aliases
and admin read routes have been added. Fresh backend-local verification is
**356 passed**; pinned image **285 passed**. The unchanged full public suite is
**68 passed, 12 failed, 1 fixture error, 16 skipped**. The user chose to keep the
public tests unchanged and document conflicting requirements. See the
[reconciliation report](backend-public-test-reconciliation-2026-09-29.md).
Earlier release/image/load evidence below describes the preceding completion build.

**Backend implementation: complete for the agreed required scope. Real biometric
integration: deferred by the user and not certified.** The supplied Module 3
operations return 501 and no functioning external service/approved face fixture
is currently available. Verification requirements remain enabled. No frontend
screens, Module 3 implementation or dashboard features were added.

This closes the backend work from the [original audit](backend-audit-2026-09-29.md).
The original audit remains a dated baseline, not the current status. The
[23-row requirement register and consumer contract](../docs/BACKEND-COMPLETION.md)
maps each outstanding requirement to implementation and regression evidence.
Earlier uncommitted verification/recovery repairs were preserved.

## Findings addressed

| Finding | Final backend behavior and evidence | Disposition |
|---|---|---|
| R01 — authorization | Shared taught-course scope recognizes assignment or owned sessions. Profiles, statistics, recent attendance, lists, review and export respect that scope. Shared-course read/review does not confer session mutation ownership. TA removal and admin access tested. Retained student statistics survive withdrawal. | Complete |
| R02 — device proof/lifecycle | Parse real P-256/RSA keys; clear trust on key change; preserve administrator revocation. Redis nonce challenges bind user/device/session/key/payload for 120 seconds; signatures verified and valid challenges consumed atomically. Unsigned submissions receive unknown-device risk. Invalid, expired, foreign, changed-key and cross-session proof tests create no attendance. | Complete |
| R03 — release/dependency gate | Repaired source packaged and deployed; private configuration/credential rotation; separate roles; PostgreSQL/Redis health, migrations, restart, backup/restore and load verified. Actual face interoperability cannot be exercised without the external implementation. | Backend deployment complete; real biometric gate deferred by user |
| R04 — controlled failures | Registration/enrollment protect actual flush/commit; admin IntegrityError import/savepoints retained. Used sessions cannot be deleted after reset. Locked enrollment eligibility refreshes stale ORM objects. Unexpected errors/logs sanitized, database failures 503, conflicts controlled. | Complete |
| R05 — enrollment/activation | Shared active-course/student eligibility; accurate repeated-email outcomes; partial bulk savepoints. Newly created inactive students receive private, expiring, one-use activation links; only digests stored. Activation establishes a validated password under a row lock. Creating batches serialize to avoid opposite-email deadlocks. TA operator provisioning documented. | Complete |
| R06 — audit integrity/events | PostgreSQL rejects audit update/delete/truncate; application append-only, reader read-only. Required location, manual outcomes/reviewer/reason, automatic reasons, blocked logins, available login device and security denials recorded with correlation. Rate-blocked check-in attempts retain minimized location and Retry-After. Trigger/function drift fails readiness. | Complete |
| R07 — reports/exports | Approved eligible students / retained roster; separate submission/status counts. Null unknown rates, 30-day coverage, Singapore session dates, future-window/cancellation exclusions, withdrawal/reset/legacy handling. Statistics/export agreement tested. Unicode/ASCII whitespace-hidden CSV formulas neutralized; bounded lists/exports and readable coverage headers. | Complete |
| R08 — privacy lifecycle | Authenticated deletion scheduling immediately disables access/consent, clears face hash and revokes devices; deadline is idempotent. Due accounts anonymized after 30 days. Camera withdrawal clears enrollment. Full-precision evaluation, four-decimal stored/audited locations. Audit-retention exception documented. | Complete |
| R09 — fraud/concurrency | Word-based VPN/proxy hint, private-IP exception, retained approved-location travel review flag. Sync DB/Redis/IP work offloaded; auth transaction released before waiting; no transaction across biometric await. Consistent enrollment/session/finalization ordering; real 10/100-user HTTP contention measured. IP cache/provider failures visible and bounded. | Complete, with documented heuristic/map limitations |
| R10 — resource/input limits | 16 MiB request limit including chunking; 10 MiB decoded image limit; streamed decompressed face response <=64 KiB. Unsupported mutation fields and nonblank QR explicitly rejected. Sanitized errors and correlation; image decoding/pixel enforcement remains Module 3 responsibility. | Backend complete; real image-service enforcement gate deferred |
| R11 — schema/recovery | Four necessary storage columns, forward 0007/0008 migrations, activation/revocation/counter constraints and frozen audit-object contract. Historical recovery destination remains 0006 and upgrades normally afterward. Existing useful indexes retained. Risk factors/audit contributions documented instead of duplicate signal storage. | Complete |
| R12 — browser/config | Correct frontend build-time `/api/v1` base; exact CORS validation; exposed retry, download, request and reporting headers. Private credentials, distinct identities and loopback infrastructure. Forwarded-header-overwriting ingress documented. | Complete |
| R13 — observability/reproducibility | Required Prometheus names plus bounded error/outcome/dependency/cleanup metrics. Request IDs, trace-context propagation and redacted logs. Prometheus target verified up; pinned image suite and full infrastructure regressions recorded. Current README/contracts replace stale claims. | Complete; OTLP export intentionally deferred |

All 23 originally Partial/Missing/Incorrect requirements have an implemented
backend disposition in the register. The deployment row retains the explicit
external biometric gate rather than claiming full integration readiness.

## Files changed and why

Paths below are relative to the repository unless stated otherwise. These are
completion changes; previously existing F00/verification files were retained and
adapted only where the new canonical head/contracts required it.

| Files | Requirement/defect justifying changes |
|---|---|
| `module2-backend/app/routers/auth.py`, `app/schemas/auth.py` | Flush/commit conflicts, blocked-login/device audits, activation contract and single-use locking; honest refresh semantics. |
| `app/dependencies.py`, `app/services/access.py` | Consistent teaching scope, release auth connection before I/O, deletion retry exception, ordered session mutation lookup. |
| `app/routers/enrollments.py`, `app/services/enrollments.py`, `app/routers/admin.py` | Shared eligibility/savepoints, secure creating workflow, correct counters and admin exception handling; stable historical roster and race prevention. |
| `app/routers/sessions.py` | Snapshot activation, course-before-session locking, used-session deletion guard and bounded discovery. |
| `app/routers/devices.py`, **new** `app/services/devices.py` | Existing inventory lifecycle plus necessary cryptographic challenge issuance/verification/atomic consumption; bounded inventory. Reuses installed cryptography and Redis. |
| `app/routers/checkins.py`, `app/risk.py`, `app/schemas/attendance.py` | Proof fields, bounded/offloaded phases and final revalidation, minimized attempt/outcome auditing, network/travel factors, preserve weighted scorer and existing critical rules. |
| `app/routers/stats.py`, **new** `app/services/reporting.py`, `app/schemas/analytics.py` | Replace incorrect submission-based attendance with shared retained roster semantics, nullable uncertainty and scoped bounded reporting; avoid per-student record scans. |
| `app/routers/export.py` | Matching report semantics, retained coverage headers, formula-safe CSV and bounded streaming. |
| `app/routers/users.py`, `app/services/retention.py` | Supported deletion scheduling, consent/hash clearing, locked final face persistence, expiry/anonymization, overlap protection and cleanup evidence. |
| `app/audit.py` | Consistent correlation/version metadata without biometric/token payloads. |
| `app/main.py`, **new** `app/middleware.py`, **new** `app/metrics.py` | Request/body/error/correlation boundaries, readable CORS headers, `/metrics`, sanitized logs and known database-outage responses. |
| `app/config.py`, `app/schemas/common.py`, `app/schemas/courses.py`, `app/utils/geolocation.py` | Exact origin/private config checks, forbid unsupported mutation fields, decoded-image bound, bounded observable IP-provider/cache handling. |
| `app/face_service.py` | Preserve strict existing verification evidence while bounding streamed/compressed responses and propagating correlation safely. |
| `app/models.py`, **new** `alembic/versions/20260929_0007_completion_fields.py`, **new** `20260929_0008_audit_and_constraints.py` | Only required activation, revocation and roster storage; database invariants and immutable audit objects. |
| `app/schema_contract.py`, **new** `app/schema_contracts/20260929_0008.json`, `scripts/freeze_schema_contract.py`, `scripts/reconcile_database.py` | Strict new head/object verification; preserve verified historical recovery before forward upgrades. Old migration/provenance files unchanged. |
| **new** `scripts/configure_database_roles.py` | Idempotent separate operator/application/optional reader roles without schema ownership or membership bypass. |
| `requirements.txt` | Only new runtime dependency is pinned `prometheus-client==0.19.0`; existing cryptography/Redis/SQLAlchemy reused. |
| `module2-backend/Dockerfile`, `.env.example`, root `docker-compose.yml`, **new** root `.env.example`, `.gitignore` | Separate migration/runtime identities; package complete repairs; deliberate nonusable secret examples; private local config/backup exclusion; loopback ports and preserved Redis volume. |
| `module1-frontend/Dockerfile` | Backend interface only: build-time API base argument. No screens or other frontend behavior changed. |
| `module2-backend/README.md`, `docs/API-SPECIFICATION.md`, `docs/SECURITY-REQUIREMENTS.md`, `docs/recommended_design/DATABASE-SCHEMA.md`, `INTEGRATION-GUIDE.md`, `docs/F00-DATABASE-RECOVERY.md`, **new** `docs/BACKEND-COMPLETION.md`, audit/report artifacts | Current contracts, operator procedures, exact signature/retry/report rules, source/evidence mapping and historical/current distinction. |

Private `.env` contains newly generated local deployment credentials. It and
backup/role evidence under `tmp/backend-completion-private/` are ignored and are
not part of the deliverable source. Complete previously untracked canonical/
legacy migrations, frozen contracts, readiness/backup/recovery scripts and
verification repairs are included in the tested image; none were discarded.

## Tests added or modified

- **New `tests/test_completion.py` — 47 cases:** focused API regressions for permissions,
  activation expiry/single-use/duplicates/inactive eligibility, device lifecycle
  and P-256/RSA proofs, payload/session/key/foreign substitutions, travel
  thresholds, private network hints, historic rosters/reports/CSV/coverage,
  deletion/consent/precision, TA removal/shared ownership, errors/body/upstream
  limits, retry/CORS/correlation/metrics and nonblocking slow dependencies.
- **New `tests/test_completion_postgresql.py` — 17 cases:** real concurrency for registration,
  enrollment, activation, opposite-order creating batches, snapshot/enrollment,
  review/appeal, lockout, stale locked eligibility and Redis atomic consumption;
  audit mutation/role/trigger-drift and cleanup advisory-lock checks.
- **New `tests/key_fixtures.py`:** disposable real P-256 test key; never a deployment
  identity. RSA tests generate disposable keys.
- **Modified `test_week3.py`, `test_compliance.py`, `test_compliance_routes.py`:**
  valid device keys, proof-qualified scoring expectations, approved attendance
  semantics and accepted mutation input shapes. Existing correct workflows retained.
- **Modified `test_main.py`, `test_database.py`:** required private settings and
  new canonical head/constraints while retaining migration checks.
- Existing `test_f00_postgresql.py` historical seeding uses reflected historical
  columns rather than the newer ORM, preserving meaningful old-schema recovery
  checks. Existing `test_verification_postgresql.py` expects unknown-device
  contribution for unsigned submissions. The original 54 PG cases remain intact.

Verification ran after each logical group, with regressions repaired before
continuing. Final fresh results are recorded below.

## Final verification and release evidence

- Full backend-local suite (`module2-backend/tests`) with PostgreSQL and real Redis: **349 passed in 67.83 seconds,
  zero failures, errors or skips**. Includes all original 54 PostgreSQL cases
  plus 17 new PostgreSQL cases (71 total).
  Final JUnit evidence: `tmp/backend-completion-final.xml`.
- Pinned Linux image tests: **278 passed in 19.54 seconds**. PostgreSQL suites are
  exercised by the complete host run, not hidden behind unexpected image skips.
- Fresh migrations, existing database upgrade, strict schema/object readiness,
  restricted app/reader roles and legacy recovery: verified. Existing 0006 backup
  restored in isolation, upgraded to 0008 with original-column values/primary keys
  preserved. The existing integration database was upgraded through the same
  migration job, without resetting its volume/data.
- Final 0008 backup restored into a separate database and passed strict readiness
  including audit triggers/functions. Private manifest:
  `tmp/backend-completion-private/final-backup/561011ed-d3c8-4c05-a321-2058cc2ca4dd.json`.
  Neither backups nor their private row evidence are included in public artifacts.
- Deployment: required private operator/app/reader URLs; existing operator password
  explicitly rotated; migration job completes before runtime. Backend/DB/Redis
  published only on 127.0.0.1. Existing PostgreSQL/Redis volumes preserved.
  `/health` is 200 with healthy schema/database/Redis after restart.
- Prometheus backend target: **up**, `http://backend:8000/metrics`, no scrape error.
  Logs and metric labels use generated request IDs/templates/bounded categories.
- Real HTTP load on the final image: **440 requests, all expected 200/201,
  no unexpected errors or pool exhaustion**. At 10 concurrent users, profile
  p95 was 0.067 seconds and check-in p95 0.188 seconds. At 100 concurrent users,
  profile p95 was 1.633 seconds and check-in p95 1.536 seconds. All four p95
  measurements meet the two-second target. Same-course check-in samples recorded
  transaction/tuple locks (10 users: 2/9 samples; 100 users: 4/3), without
  deadlocks or request failures. WAL synchronization waits were also observed.
- Windows HTTP-client runs were slower (100-user p95 3.11–4.95 s for profiles and
  up to 2.36 s for check-ins), while sampled server GET p95 was 0.27 s. Those
  results remain a local client/network measurement limitation; Linux HTTP
  measurements are separately reported, not substituted silently.
- One preliminary load started before readiness returned 20 connection errors;
  the readiness-gated rerun is the release measurement. Test execution switched
  host DB/Redis URLs to explicit IPv4 after loopback-only publication caused
  Windows localhost/IPv6 connection delays. Neither workaround disables backend
  validation or biometric requirements.

The final production image is
`sha256:a0290604890402e7d86abc798995dd42547065bbd1f53d38f9b3dbe2b75654c6`.
Sanitized machine-readable evidence is in
[backend-completion-evidence-2026-09-29.json](backend-completion-evidence-2026-09-29.json).
The restarted target briefly reported a refused connection during restart;
its next scrape returned up with no error. The final source diff passes the
whitespace/error check.

Normal-API load fixtures are created only in the isolated restored database,
with explicitly optional biometric flags. They measure normal backend paths and
course-lock contention, not biometric performance. No policy on existing
integration sessions was disabled. Live biometric latency cannot be reported.

### Supplied outer public tests — follow-up verification

The 349-pass result above did **not** include the repository-root `tests/public`
suite. All 97 supplied public tests collect successfully. A separate live HTTP
run of the 79 backend-facing tests (API, security, privacy, observability,
performance and frontend/dashboard API contracts) against the isolated final
image returned **43 passed, 6 failed, 29 setup errors and 1 explicitly skipped**
in 12.64 seconds. The supplied tests were not modified.

Of the setup errors, 28 originate from `tests/conftest.py` sending unsupported
course `require_device_binding`; one device fixture omits the required public
key and sends unsupported `browser`. The six failed assertions expect alternate
overview fields, a paginated flagged-checkin response instead of the documented
array, `/audit/summary`, an admin inventory at `GET /devices/`, or unauthenticated
access to courses (two cases). These discrepancies require public-test contract
reconciliation; they are not covered by the green backend-local suite.
Many downstream workflow assertions therefore never ran in this public pass.
The one skip is the supplied concurrent-checkin test's unconditional skip.
The 18 face-service/integration tests were not run in this follow-up.
JUnit evidence: `tmp/backend-public-tests-final.xml`; output:
`tmp/backend-public-tests-final.txt`. A passing public-suite score is not claimed.

## Deferrals and unresolved required verification

**User-requested deferral:** real face enrollment → persisted hash → verification
→ check-in, mismatch, real invalid images, all verification-flag combinations
against the actual provider, provider image/pixel enforcement and latency.
Exact reason: no functioning external implementation or approved fixture is
available; supplied operations return 501. Backend strict client behavior, all
flag combinations and outage handling are tested with service-boundary fixtures,
but these do not close real interoperability. Set `FACE_SERVICE_URL` and run
that gate once Module 3 is available.

**Optional work intentionally omitted:** QR issuance, standalone attestation,
duplicate risk-signals storage, extra recommended metadata, email delivery,
refresh rotation/logout, paid network reputation and OTLP export. These were
explicitly excluded by the accepted plan. Minor stale internal labels/unused
imports/helpers and unrelated cleanup remain deferred; they do not change the
implemented contract. The network hint, fixed Singapore map, and approximate
stored GPS are documented limitations rather than stronger security claims.

No other required backend implementation finding remains Missing, Partial or
Incorrect after the completion changes and verification. Credentials/backups
remain private; the tested code is packaged in the image and remains as working
tree changes for user review, without an unsolicited commit or pull request.

## Final backend checklist

- [x] Controlled transactions/conflicts, shared authorization and eligibility.
- [x] Secure bulk account activation and current/history roster semantics.
- [x] Device key lifecycle, signed one-use proof and preserved risk rules.
- [x] Correct approved attendance, retained coverage, scoped reports and safe exports.
- [x] Immutable complete audit, deletion/consent/precision and observable cleanup.
- [x] Bounded inputs/dependencies, safe errors, readable CORS and correlation/metrics.
- [x] Forward migration/recovery, separate roles, private secrets and complete image.
- [x] Real DB/Redis concurrency, backup/restore, restart and normal API load evidence.
- [ ] When available: configure the real face service/approved fixture and pass
  the deferred biometric/pixel/latency gate before declaring real integration ready.
