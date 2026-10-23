# Backend reduced-contract implementation — 29 September 2026

**Complete under the approved revised Module 2 contract.** Both unchanged selected
public runs passed **66 cases with exactly the supplied unconditional skip**, no
failures or fixture errors. The complete backend-local suite passed **389/389**,
including **74 PostgreSQL/Redis cases**, without skips. Real biometric
interoperability remains deferred by the user because no functioning face service
is available; these results do not certify that external dependency.

This report supersedes current-status claims in the earlier audit, completion and
public reconciliation reports. Those files remain historical evidence. The
[user-approved exceptions](../docs/BACKEND-COMPLETION.md#approved-public-contract-reductions)
apply only to the identified conflicts; other written requirements still govern.
The latest authority notice also appears in Grading, Security and API documents.

## Dependency-aware execution and closure

The implementation followed the agreed order. Each group passed its checks before
the next group proceeded. Existing uncommitted compatibility work and previously
correct activation, verification, lockout, retention, reporting and deployment
repairs were preserved. No new service, dependency, configuration mode, stored
column or endpoint was introduced by this reduction work.

| Outstanding requirement / public discrepancy | Minimal implementation | Regression/completion evidence | State |
|---|---|---|---|
| Missing/null GPS accuracy blocked duplicates, history, integration and check-in performance | `CheckinCreate`/`CheckinResponse` accept null; `Checkin` stores null; `assess_risk` adds the existing 0.25 geo adjustment; travel requires both known radii | Persistence, finite/nonnegative validation, omitted/null signing digest, travel boundary tests; all affected public cases pass | Complete |
| Stored GPS consent blocked an otherwise valid submission | `_validate_eligibility` treats coordinate submission as per-attempt permission, leaves stored preference unchanged | Local API and concurrent PostgreSQL consent-change cases prove unchanged stored preference and valid attendance | Complete, approved exception |
| Session liveness flag demanded absent optional evidence | Eligibility returns the effective flag: session request AND camera consent AND nonblank image; `_prepare` freezes it, `_finalize` recomputes under locks | All 16 flag/consent/image combinations; required-face and service-failure regressions; evaluated liveness policy-change races reject with 409 | Complete, approved exception |
| Keyless/browser fixture failed registration | Optional nullable key and excluded bounded browser; omission preserves credentials, null removes key/clears trust; supplied keys still parsed | Keyless untrusted/no challenge, omit/null distinction, ownership/revocation, signed proof/replay and concurrent consumption tests; public device fixture succeeds | Complete, approved exception |
| Anonymous course-performance requests failed | `list_courses` is public metadata; instructor filter public; creation descending then ID, existing bounds | >50 courses, stable nonoverlapping pages/filters; detail and mutations still require authentication; both public latency cases pass | Complete, approved exception |
| Unrelated instructor course/student/roster reads failed | Existing helpers accept default-false `read_only`; read endpoints pass true; instructor aggregate queries use global read scope; empty student reports allowed | Unrelated profile/statistics/attendance/roster/export reads pass; unrelated enrollment/review/session writes still 403; student/TA boundaries and immediate TA removal pass | Complete; follows Security all-student read allowance |
| Flagged list had wrong shape | Existing `CheckinListResponse` envelope, count before pagination | Counts, flags/appeals, ordering, filters, offsets, TA removal/boundaries and unchanged public queue test | Complete, approved response change |
| Model/migration/readiness required nonnull accuracy | Forward `20260929_0009_nullable_checkin_accuracy.py`; head `20260929_0009`; new independently frozen schema | Fresh/0008 upgrade, exact row preservation, only-nullability delta, retained nonnegative constraint, safe downgrade/refusal, strict readiness | Complete |
| Current documentation contradicted approved reductions | Updated current API/Security/Grading notices, completion contracts and README; historical reports explicitly superseded | Accepted fields, null/signing semantics, read/write distinction, flagged envelope and exception authority documented | Complete |
| Release verification | Full suite, pinned image, two public runs, backups, migrations, roles, recovery, restart, metrics and load | Detailed fresh evidence below and linked machine-readable record | Complete for revised backend scope |

Group gates: accuracy/migrations **16 passed**; verification/device policy **189
passed**; read/catalogue/envelope contracts **148 passed**. These are overlapping
focused selections, not additional cases to add to the full-suite count.

The public selection contains exactly `test_api_functional.py`,
`test_security_basic.py`, `test_privacy_basic.py`, `test_performance.py`,
`test_observability.py` and `test_integration.py`. The excluded face/frontend/dashboard
files were not run as acceptance gates. The supplied skipped case is
`TestConcurrentUsers.test_concurrent_checkins`; its unconditional marker cites
SQLite concurrency. Backend-local PostgreSQL concurrency tests still execute.

## Original audit register R01–R13

The [23-row completion register](../docs/BACKEND-COMPLETION.md) remains the detailed
requirement register. Its required rows have no remaining Missing, Partial or
Incorrect implementation status under the approved scope. Closure here distinguishes
new reductions from earlier working fixes preserved by the full regression suite.

| Finding | Final implementation / preserved fix | Evidence |
|---|---|---|
| R01 Access and workflows | Global instructor **reads**, teaching/ownership **writes**; TA assignments and student ownership preserved | Unrelated read/write tests, shared/session-only teaching, TA removal, review races; public roster/statistics passes |
| R02 Device credentials/trust | Keyless inventory allowed; supplied keys validated, no proof-based trust without one-use proof; revocation cannot be undone by owner | Null/omission lifecycle, invalid/replaced/revoked/foreign proof, Redis consumption race |
| R03 Deployment | Existing private secrets and distinct roles preserved; complete updated image deployed with operator migration job | Restricted-role tests, verified backups, healthy startup/restart, exact row preservation |
| R04 Transactions/lifecycle | Existing conflict handling/savepoints/admin error handling and used-session deletion safeguards preserved | Registration/enrollment/review concurrency and rollback tests |
| R05 Enrollment/accounts | Existing active eligibility, bulk partial success, 24-hour single-use activation and pending-account safeguards preserved | Activation/enrollment/bulk races, expiry/replay and roster tests |
| R06 Auditing | Existing append-only PostgreSQL enforcement and redacted attempt/outcome/denial correlation preserved | Restricted-role update/delete/truncate and strict trigger/function readiness tests |
| R07 Reporting | Existing retained historical roster denominator, approved attendance, coverage, null unknown rates and safe bounded exports preserved; reads broadened | Rejected-only/absence/roster/date/retention/CSV cases; statistics/export agreement |
| R08 Privacy | Consent tracking, face-hash withdrawal, immediate deletion disable, 30-day anonymization and rounded stored GPS preserved; per-attempt GPS permission revised | Consent/deletion/retention/precision regressions and public privacy cases |
| R09 Fraud/I/O | Existing bounded dependency offloading and network hint preserved; unknown radii skip travel inference | Travel boundaries, unknown accuracy, slow dependency tests and load samples |
| R10 Validation/errors | Existing body/image/upstream bounds, safe errors, unsupported fields/QR rejection preserved; documented fields reduced | Oversize/malformed/outage/redaction tests and public input-validation cases |
| R11 Schema | One nullable-accuracy migration and frozen head; historical migrations/contracts untouched, recovery base remains 0006 | Fresh/upgrade/downgrade/drift/recovery/backup checks |
| R12 Consumer/deployment contract | Public catalogue and canonical flagged envelope documented; existing API prefix, CORS and exposed headers preserved | Public contract tests, browser/header regressions, deployed health |
| R13 Observability | Existing bounded metrics/correlation/cleanup state preserved | Metrics tests, live scrape, Prometheus target up |

## Files changed and why

Paths in this table are relative to `module2-backend` unless otherwise stated.
Existing compatibility additions from the preceding work remain in place.

| Files | Justification |
|---|---|
| `app/schemas/attendance.py` | Optional/null accuracy and device key; accepted nonpersistent bounded browser metadata |
| `app/models.py`, `app/risk.py` | Nullable existing accuracy; conservative unknown-risk adjustment with finite validation retained |
| `app/routers/checkins.py` | Per-attempt GPS permission, effective optional liveness freeze/recheck, known-radius travel guard, read scope and canonical flagged envelope |
| `app/routers/devices.py` | Optional key parsing, omitted credential preservation and explicit-null trust clearing; existing compatibility routes preserved |
| `app/services/access.py`, `app/dependencies.py` | Reuse existing helpers with explicit default-false read-only keyword; mutation scope unchanged |
| `app/routers/users.py`, `stats.py`, `enrollments.py`, `export.py` | Consistent instructor read policy; empty student reports; existing compatibility fields/export aliases retained |
| `app/routers/courses.py` | Public filtered metadata catalogue, newest-first bounded pagination; mutation/detail policy unchanged |
| `app/schema_contract.py`, `alembic/versions/20260929_0009_nullable_checkin_accuracy.py`, `app/schema_contracts/20260929_0009.json` | Only existing accuracy nullability changes; strict head readiness and lossless downgrade policy |
| `tests/test_reduced_contract.py` | 29 targeted new cases for nullable accuracy/signing, optional liveness matrix, key lifecycle, unrelated read/write separation, flagged envelope/TA boundaries and >50 catalogue pagination |
| `tests/test_completion_postgresql.py` | New 0008 upgrade/row-preservation/constraint/downgrade test |
| `tests/test_verification_postgresql.py` | Two evaluated optional-liveness race regressions; revise GPS-consent race expectation without weakening face/account/enrollment races |
| `tests/test_completion.py` | Unknown previous accuracy travel case; intentional instructor report scope expectation |
| `tests/test_verification.py` | Optional-liveness missing-image expectations; required-face cases remain strict |
| `tests/test_week3.py`, `test_f00_readiness.py`, `test_compliance_routes.py`, `test_public_compatibility.py` | Update only intentionally superseded local course/key/consent/read expectations; retain negative write/security assertions |
| Root `docs/API-SPECIFICATION.md`, `SECURITY-REQUIREMENTS.md`, `GRADING-CLARIFICATIONS.md`, `BACKEND-COMPLETION.md`; backend `README.md` | Explicit approved exceptions and exact revised consumer/schema contracts |
| Root historical audit/completion/reconciliation reports | Superseding notices, preserving historical evidence |
| Root `output/backend-reduced-contract-2026-09-29.md` and evidence JSON | Finding closure, fresh verification and release evidence |

No dependency manifests, other module implementation or deployment feature setup
needed new changes. Prior compatibility source (`audit.py`, analytics/course schemas,
local OpenAPI test) remains preserved in the working tree. No working migrations,
old contracts, activation/roster columns or safeguards were removed or rewritten.

## Fresh verification results

| Gate | Result |
|---|---|
| Complete host backend suite, real Redis/PostgreSQL | **389 passed**, 0 failed/errors/skipped; 59.69 s |
| PostgreSQL/Redis subset | **74 passed**, including the prior 71 cases and 3 new migration/policy-race cases |
| Pinned Linux test image | **315 passed**, no skips; 18.54 s; 2 existing dependency deprecation warnings |
| Selected unchanged public suite on fresh isolated data | **66 passed, 1 supplied skip**, 0 failures/errors; 14.23 s |
| Same selected suite on the same populated instance | **66 passed, 1 supplied skip**, 0 failures/errors; 16.05 s |
| Fresh migrations + 0008 upgrade | Head 0009 healthy; Alembic check clean; only accuracy nullability changed |
| Existing integration database upgrade | Verified pre-upgrade backup; exact existing row evidence preserved before startup; strict 0009 readiness |
| Restricted roles / immutable audit / strict objects | Passed full PostgreSQL regressions |
| Historical recovery rehearsal | Passed real restored-backup tests; recovery verifies 0006 before ordinary forward upgrades |
| Final populated backup/restore, including null accuracy | Restored into a separate database; data/schema/control evidence equal; strict 0009 readiness healthy |
| Updated startup / restart | Main and isolated backends healthy with database, Redis and schema healthy |
| Metrics | Required names available; existing Prometheus backend target reports up after restart |
| External tests/scoring/excluded modules | Tracked sources byte-equal to HEAD after LF normalization; hashes recorded; no changes |
| Historical migrations/contracts | All tracked historical files unchanged; new frozen inventory differs solely in accuracy nullability |
| Whitespace validation | `git diff --check` passed |

Production image identity:
`sha256:fcdd307f75dc002593382ec7f94ba1d20b7d3b8d6994d5f68bac8f5725de962d`.
Pinned regression image:
`sha256:30681f3f948fb4d0b5bb768d15b8c6326b7a833dc063a8923f8c5ca29f63c0e4`.
The main API is deployed at localhost port 8000; public verification used an
isolated database/Redis namespace at port 18000. No existing integration database
was reset. Private credentials and backup contents remain ignored local artifacts.

Normal API load used the healthy isolated production image and real HTTP, JWT,
PostgreSQL and Redis. Sessions explicitly did not request biometric checks; these
measurements cannot represent biometric latency. All **440 requests** succeeded
with no unexpected errors or pool exhaustion.

| Users | API | Requests | p95 | Maximum | Target |
|---:|---|---:|---:|---:|---|
| 10 | GET own profile | 30 | 0.038 s | 0.062 s | Pass |
| 10 | POST check-in | 10 | 0.149 s | 0.149 s | Pass |
| 100 | GET own profile | 300 | 0.435 s | 0.480 s | Pass |
| 100 | POST check-in | 100 | 1.402 s | 1.490 s | Pass |

Sampling saw transaction/tuple lock waits during same-course submissions
(10 users: 1/3 samples; 100 users: 2/4), plus bounded WAL-sync samples; there were
no request failures or observed pool exhaustion. These samples are aggregate
observations, not individual lock-duration measurements.

The first attempted full run had Docker restore transport errors while Docker
access was restricted and one superseded mandatory-key assertion. The fixture
expectation was corrected locally, Docker transport access restored, and the
fresh final full run passed all cases. No external tests were altered to fix it.

Machine-readable counts, skip reason, image IDs, load results, deployment checks
and normalized source hashes are in
[backend-reduced-contract-evidence-2026-09-29.json](backend-reduced-contract-evidence-2026-09-29.json).
Full run XML/text and private rehearsal materials remain in `tmp/` for inspection.

## Remaining work and verdict

**Backend implementation completeness:** complete under the revised approved
contract. Every selected executable Module 2 public test passes without modifying
external tests. No required implementation item from this reduction plan remains
unresolved. Normal backend API deployment and consumer contracts passed the gates.

**Real biometric interoperability:** deferred/unverified. No working external face
implementation or approved real fixture was supplied; the checked-in Module 3
operations are scaffolds returning 501. Required face matching remains enabled
when requested and fails safely on unavailable evidence. Local HTTP-boundary and
race tests prove backend handling, but cannot certify real enrollment-to-verification
interoperability. Do not describe the whole cross-module biometric system as verified.

Optional QR issuance, standalone attestation, duplicate risk storage, extra optional
metadata, email delivery, refresh rotation/logout, paid network reputation and full
OTLP export remain intentionally deferred as before. No optional functionality was
added for public-test compatibility.
