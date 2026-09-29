# SC3099 Module 2: Backend audit

**Completion update — 29 September 2026:** The required backend portions of
R01–R13 and all 23 outstanding requirement rows have been implemented and
verified. This document preserves the original audit baseline below. See the
[completion report](backend-completion-2026-09-29.md) and
[requirement register](../docs/BACKEND-COMPLETION.md) for current status.
Real biometric integration is deferred by the user because the required
external service is unavailable; real integration readiness is not certified.

**Audit date:** 29 September 2026. **Planning context:** Recess Week, between Weeks 7 and 8.

**Verdict:** The backend has a substantial implemented core and all 50 documented backend HTTP operations, but it is **not yet ready for unrestricted integration or a claim of backend completion**. The recent database and verification repairs materially improve it. Remaining work concerns access consistency, device trust, failure handling, privacy/auditing, dashboard correctness, operational configuration, and real-service verification.

This is an audit of the current working tree, including uncommitted repairs. Application files, specifications, existing tests, services, and live data were not changed. Audit artifacts and synthetic probes were added separately. Other modules were inspected only at the interfaces that directly affect backend integration.

## Evidence and interpretation

Sources reviewed:

- [Briefing.pdf][BRIEF]: all 47 pages; backend responsibilities especially pp.20, 23-29, 33-39. Page references mean PDF page numbers.
- [Module2-Backend-Design.pdf][PDF2]: all 7 pages; authentication, schema, rate limiting, and error handling.
- All seven documents under `docs/`: [grading clarifications][GRADE], [security requirements][SEC], [API specification][API], [database design][DBSPEC], [integration guide][INTEGRATION], [database recovery][RECOVERY], and [verification repair][REPAIR].
- Backend routers, schemas, models, services, settings, migration histories/contracts, recovery tooling, Docker setup, backend tests, and backend-facing public tests.

Authority: **grading clarifications > Security Requirements > API Specification > recommended design > PDFs**. The repair/runbook documents describe current decisions and evidence; their explicit remaining-work lists are not treated as waivers of higher-level requirements. Public tests and older README prose do not override `docs/`.

Important resolutions:

- Login/registration limits are **100,000/hour/IP**, general authenticated requests **1,000/hour/user**, and check-ins **10/minute/user**. Ten consecutive bad passwords cause account login lockout. The lower PDF limits are superseded.
- Singapore GPS and public-IP restrictions are mandatory; the first forwarded address and private/local exception are explicitly required. They are not evidence of VPN or GPS-spoofing detection.
- Self-registration with all four roles is intentional in the course contract; it is not scored here as an accidental privilege-escalation defect. Shared deployment must nevertheless be treated as a trusted course/test environment.
- TLS is explicitly not required. Its absence is not a completion blocker.
- Liveness is a bonus capability, but **an enabled liveness requirement must be enforced**. Face matching cannot silently disappear when its flag is enabled.
- Local weighted scoring, disabled-signal zero contributions, and the current network-detection limitation are now documented. Do not restore the old GPS-only scoring policy or require a `/risk/assess` call merely because an older example used one.
- Specific endpoint array/object examples take precedence over the API's contradictory blanket pagination statement. Several public tests also expect older analytics names. These are contract-reconciliation items, not reasons to weaken authorization or verification.

### Verification performed

| Evidence | Result and limitation |
|---|---|
| Current OpenAPI inventory | **50 operations under `/api/v1`**. This proves route presence, not correctness. `/metrics` is absent. |
| Backend suite with an audit-only, per-test in-memory Redis double | **231 passed, 54 skipped in 21.31 seconds**. SQLite, HTTP MockTransport fixtures, and the existing test doubles were used. The 54 skipped cases require real PostgreSQL. This does not validate Redis Lua atomicity, live services, or PostgreSQL concurrency. |
| Ordinary backend-suite run | **139 passed, 92 failed, 54 skipped in 424.36 seconds**. Failures are 63 verification and 29 week-three cases, caused by unavailable Redis blocking check-in with 503 before the behavior under test. [Raw run evidence][RAWTESTS]. |
| Additional synthetic probes | Reproduced 16 observations, including access inconsistencies, device trust restoration, statistics disagreement, mutable audit rows, and unhandled error branches. [Probe results][PROBES]. Fault-injected uniqueness conflicts are identified as such; they are not claimed as real concurrent PostgreSQL runs. |
| Runtime/dependencies | Docker daemon unavailable. Local bcrypt is **4.1.2**, whereas backend requirements pin **4.0.1**; passlib emits its version warning. `pip check` finds no broken installed dependency requirements, but this environment is not an exact reproduction of the image. |
| Prior repair evidence | The repair document records **285 passed including 54 PostgreSQL tests** on 28 September. This is historical evidence, not a fresh live run by this audit. |

No live public-suite score, current database health, real face-service success, or production latency is claimed.

The Redis-double run changes only the external cache fixture, without editing the supplied tests or application. Its [separate test evidence][STUBTESTS] isolates code behavior from the environment failure. Both results matter: the ordinary run is not green in this environment, and the isolated green run does not replace real-infrastructure validation.

## 1. Overall Backend Status

### Current completion

**Feature surface: broadly implemented. Correctness and integration assurance: incomplete.** A percentage would be misleading: all 50 routes can exist while a supported enrollment option fails, permissions disagree, and biometric dependencies cannot complete the real workflow.

The normal course → enrollment → session → check-in → review/export path exists. The backend has moved beyond an early scaffold. Its main strengths are typed API contracts, database uniqueness/check constraints, role enforcement, geofencing, strict biometric response validation, a single weighted scorer, and unusually thorough recent migration/recovery work.

### What is now genuinely repaired

- **Database compatibility/readiness:** canonical head `20260928_0006`, frozen schema comparison, migration locking, separate legacy reconciliation, verified backup/rehearsal tooling, and schema-aware `/health` exist. Do not repeat the older claim that health only checks connectivity or that the canonical migration head is missing. Live readiness still needs rechecking when infrastructure is available.
- **Required biometric evidence:** blank/missing evidence fails; malformed, unavailable, inconsistent, or wrong-threshold service results fail closed. Valid failed verification persists a rejected check-in. Enrollment requires a valid hash and sufficient detection/quality evidence.
- **Scoring:** one `weighted-v1` policy handles known/unknown devices, location accuracy, explicit zero thresholds, critical biometric failures, distance >2×radius, and the score ≥0.70 rejection ceiling.
- **Post-service finalization:** immutable policy snapshot; no ORM transaction held across biometric awaits; refreshed locks and eligibility rechecks; changed flags/reference hash return 409; attendance/device counters/outcome audit commit together.
- **Configuration:** newly created course risk defaults honor `RISK_SCORE_THRESHOLD`; stored values remain unchanged.

### Major gaps

1. Session-based teaching relationships are not recognized consistently.
2. Device trust can survive owner-controlled key replacement and reactivation after administrative deactivation; cryptographic binding/replay protection is missing.
3. Several uniqueness/FK failure paths raise uncaught exceptions; one handler references an unimported exception class.
4. Audit records are not database-enforced append-only; deletion requests cannot schedule the existing cleanup logic.
5. Statistics and exports disagree about attendance; date defaults and historical denominators need correction.
6. Documented bulk account creation is deliberately rejected; QR support is only superficial.
7. Browser URL/header configuration and backend observability interfaces are incomplete.
8. Real face-service integration, current PostgreSQL/Redis operation, release deployment, and load performance are unverified.

**Integration decision:** development against stable contracts and controlled fixtures can proceed. Treat real attendance ingestion, trusted-device use, and gradebook/dashboard data as blocked until the relevant release gates in sections 5-7 pass.

## 2. Requirement-by-Requirement Audit

“Complete” applies to the named behavior, not to every property of the surrounding subsystem. “Partial” means a useful implementation exists but has a material gap. “Incorrect” means reproducible behavior contradicts its contract or internal consistency. Recommended-schema items are identified separately from mandatory HTTP features.

| Requirement and source | Expected behavior | Current implementation / relevant files or routes | Status | Required fixes |
|---|---|---|---|---|
| Registration; Security authentication, API `/auth/register` | Normalize valid email; ≥8-character password; bcrypt ≥10; supported roles; duplicate 400 | [auth.register][AUTH] and [auth schemas][AUTHSCHEMA] implement normal path, byte bound, and sequential duplicate detection. Initial flush is outside exception handler. | Partial | Catch uniqueness failures around the actual flush and transaction. |
| Login/JWT; Security authentication | HS256; 1h access; 7d refresh; correct token types; disabled-account checks | [security.py][TOKENS], `auth.login`, `get_current_user` use current DB activity/role and validated token claims | Complete | Retain regression coverage; hardening around revocation is separate. |
| Graded account lockout; Grading | Tenth consecutive failure and later correct password return 429; success before threshold resets; admin can unblock | `auth.login` locks account row; admin activation resets failures | Complete | Real PostgreSQL concurrent-login verification still required; complete blocked-attempt auditing. |
| Refresh; API `/auth/refresh` | Validate refresh token and active account; return pair | `auth.refresh` works, but old refresh token remains reusable despite “rotate” docstring | Complete | Correct wording or implement genuine rotation as a separate hardening feature. |
| Profile/consent/admin user management; API Users | Own profile update; bounded admin list/update; instructors see enrolled students | [users.py][USERS] implements routes; session-only instructor gets 403 from relationship helper | Partial | R01: unify teaching relationship checks. |
| Face enrollment; API Users and face contract | Consent; call service; persist only valid 64-hex hash; safe errors | `users.enroll_my_face`, [face_service.py][FACE] validate success evidence and recheck consent/activity after await | Complete | Backend contract logic verified with fixtures; R03 real-service release gate remains. |
| Course CRUD; API Courses | Admin create/update/soft delete; authenticated read/filter; optional instructor extension | [courses.py][COURSES] implements contract, validation, duplicate handling | Complete | Test deletion races; align broader workflow behavior for inactive courses. |
| Session creation/lifecycle; API Sessions | Inherit defaults; future start; valid schedule/window; owner updates; forward transitions; scheduled-only deletion | [sessions.py][SESSIONS] implements ordinary workflow and active-window filtering | Partial | R04: guard deletion when admin-reset scheduled session still has check-ins; clarify administrator ownership in unassigned courses. |
| Enrollment/rosters; API Enrollments | Active students; course access; unique enrollments; owner/TA roster | [enrollments.py][ENROLL] and [shared service][ENROLLSERVICE] work sequentially; pre-handler flush breaks race handling | Partial | R04: catch conflicts centrally; consistent inactive-course policy; preserve history if required by chosen attendance denominator. |
| Bulk enrollment; API `/enrollments/bulk` | Per-email results; optional account creation | Existing-user branch works; `create_accounts=true` returns 422; inactive course accepted | Partial | R05: implement documented creation securely; unify eligibility and per-row conflict handling. |
| Admin setup endpoints; API Admin | Activate/deactivate; bulk users; status override; admin enrollment | All five operations exist; bulk user exception handler lacks `IntegrityError` import | Partial | R04: fix handler and race paths; retain documented test-state override safely. |
| Check-in prerequisites; API Check-ins, Grading | Student, active course/enrollment/session/window, consents, unique attendance, SG GPS/IP | [checkins.create_checkin][CHECKINS] checks initial and final state; DB uniqueness protects one row | Complete | Keep these invariants in real-service and concurrency tests. |
| Required verification/errors; API revised contract | 400 for missing/invalid input; 503 for bad/unavailable dependency; 409 on changed policy; valid failures stored rejected | Strict endpoint-specific models, score/boolean consistency, operation/status checks | Complete | R03: validate actual Module 3 interoperability and client retry semantics. |
| Weighted score/thresholds; Security Risk Scoring, revised API | Five fixed weights; effective threshold; critical rejection; disabled checks contribute zero | [risk.assess_risk][RISK] implements documented local policy and four-decimal rounding | Complete | Do not equate mathematically correct weighting with implemented device/network detection. |
| Venue geofence and Singapore rules; Grading | Haversine; reject >2×radius; SG boundary/public-IP check; private/local exception | [geolocation.py][GEO], local polygons, cached country lookup, controlled lookup failure | Complete | R09: asynchronous/bounded IP lookup and boundary/provider operational validation. |
| Cryptographic device binding / replay resistance; Briefing pp.26,39, Security device signal | Proof of device key possession; freshness if claiming replay resistance | Check-in accepts fingerprint but no signature/nonce/timestamp; public key is unused for proof | Missing | R02: agree signed challenge format with frontend; expiry and one-time consumption. Optional `/device/attest` itself is not a mandatory backend endpoint. |
| Device management/trust; API Devices | Owner scope; admin-only trust; unique fingerprint; nonblank key | [devices.py][DEVICES] meets inventory contract; re-registration replaces key/reactivates while preserving trust | Incorrect | R02: validate key, invalidate trust on change, enforce revocation policy. |
| Network/impossible-travel/behavioral fraud; Security weights, Briefing pp.26,39 | Consume meaningful network/location-history/freshness signals | Route passes `local_network=True`; no VPN/proxy detector, impossible-travel or replay cache | Missing | R09: add backend-relevant signals or explicitly retain limitation; SG-country lookup is not equivalent. |
| Check-in lists/detail/review/appeal; API Check-ins | Own student history; scoped staff access; one appeal within 7 days; guarded review | All routes exist; record locking and transition checks implemented | Partial | R01 scope consistency; R06 required manual outcome events; expand boundary/race tests. |
| Dashboard statistics; API Statistics | Four endpoints, scoped data, trustworthy counts/rates/date bounds | [stats.py][STATS] has SQL aggregates but relationship denial and inconsistent metric semantics | Partial | R01/R07: fix relationship, define scopes/numerators/denominators, honor default date range. |
| Attendance export; API Export | Course/session CSV/JSON, permissions, audit, trustworthy attendance | [export.py][EXPORT] works; CSV formula strings unescaped; JSON rate differs from stats | Partial | R07: correct semantics and formula protection; bounded generation; browser headers. |
| Audit querying; API Audit | Admin-only filtered/paginated read | [audit router][AUDITROUTER] implements query contract | Complete | Normalize emitted actions/details so useful filters work. |
| Audit immutability; Security Audit Logging | Existing events cannot be updated/deleted | [AuditLog model][MODELS] has no updated_at and no mutation API, but no DB append-only restriction | Incorrect | R06: enforced append-only privileges/triggers and PostgreSQL tests; coordinate frozen schema contract. |
| Audit event completeness; Security required events | Login/device data; attempts with location; manual outcome/reviewer/reason; security violations | [audit helper][AUDITHELPER] and routers emit many events, but required fields/outcomes are missing | Partial | R06: complete redacted event schema and coverage. |
| Check-in retention; Security Data Retention | Delete check-ins after 30 days; scheduled execution | [retention service][RETENTION], model defaults, backfill migration, lifespan worker exist | Complete | Operational assurance still partial: worker success/failure visibility and multiworker scheduling. |
| User deletion/PII lifecycle; Security retention, Briefing pp.27-28 | Request deletion; schedule removal/anonymization after 30 days | Cleanup anonymizes due users, but no supported route/workflow sets the deadline | Partial | R08: add authorized scheduling, document audit-PII exception and anonymization policy. |
| Raw biometric data minimization; Security Data Protection | No stored images/raw embeddings; hash-only | Image is transient; user hash only; response/error validation avoids echoing payloads | Complete | Keep request/error logs redacted; real-service storage lies beyond backend proof. |
| Limited-precision location; Briefing p.28 | Store only precision necessary for purpose | Checkin stores submitted floats without a reduction policy | Partial | R08: calculate accurately, persist justified precision, document choice. |
| Input validation; Security Validation | UUIDv4 paths, bounded enums/coordinates, safe SQL/output | Typed schemas, finite numbers, parameterized queries and safe JSON; HTTP body/upstream sizes not bounded | Partial | R10: request-byte/decoded-image/service-response limits; explicit unknown/unsupported fields; generic errors. |
| Database models/migrations; recommended schema | Constraints/indexes; documented entities; safe upgrades | Eight application tables, including `course_tas` instead of `risk_signals`; robust repair tooling | Partial | R11: document/adopt recommended differences; add necessary DB checks/indexes; maintain verified migrations. |
| QR; API example/recommended schema | If required, generate/expire/verify token | `qr_code` accepted but unused; response always `qr_code_enabled=false`; no persistence/issuer | Missing | Implement only if supported scope requires it; otherwise explicitly document/reject unsupported input. |
| CORS/browser integration; Security CORS, Integration Guide | Exact allowed origins; browser can read retry/download headers | Preflights work; no exposed headers; configuration accepts wildcard origin | Partial | R12: expose `Retry-After`/`Content-Disposition`; validate origin values and public API URL. |
| Error response/log correlation; API Error Responses, PDF2 p.7 | JSON detail on errors; safe diagnosis and request correlation | Validation/HTTP errors handled; uncaught exceptions use default non-JSON 500; no request ID | Partial | R04/R10: JSON 500 handler, controlled DB errors, sanitized correlated server logs. API does not require PDF's extra `code` field. |
| Backend metrics/tracing; Integration Guide, Briefing p.6 | Backend feeds configured observability consumers | `/metrics` missing; OTLP variable unused; no instrumentation dependencies | Missing | R13: produce required request/check-in/dependency/retention metrics; tracing if dashboard contract needs it. |
| Deployment/configuration; Briefing Docker deliverable, Security secrets | Repeatable migrated image, private configuration, ready dependencies | Docker builds/migrates/healthchecks; Compose hardcodes known credentials; latest repairs uncommitted | Partial | R03/R12/R13: release complete source set, use environment secrets, verify target infrastructure and capabilities. |

## 3. Backend Architecture Audit

### API structure and technical debt

The separation into routers, Pydantic schemas, shared access/enrollment/check-in helpers, and a strict face client is sensible. Joined check-in projections and SQL aggregation avoid the obvious per-row lookup pattern. The score implementation is centralized; the old duplicate GPS-only scorer is gone.

Remaining duplication is consequential: instructor relationships are encoded in `can_manage_course`, `instructor_has_student_relationship`, route-specific SQL filters, and `require_session_owner`; enrollment eligibility/error handling is split across three entry points. These differences already produce observable behavior, not just stylistic concerns.

Low-impact debt includes stale “Week 2/3” labels, unused imports and response/helper classes (`Pagination`, `ExportSummary`), and ordinary-course-list fallback instructor lookups. These should not displace the correctness fixes. Preserve `alembic_legacy`: it is intentional recovery history, not dead code to delete.

### R01 - High/blocking for dashboard integration: inconsistent teaching relationships

In [services/access.py:75][ACCESS], `instructor_has_student_relationship` considers the optional course instructor or TA assignment, but never sessions owned by the instructor. `can_manage_course` at line 40 does consider session ownership.

**Reproduced:** an unassigned course with an instructor-owned session permits roster access (200), while the same instructor gets **403** for the enrolled student's profile and student statistics. This affects the documented, supported per-session instructor design.

Also reproduced: an instructor who qualifies through one course receives the student's other course in `stats.student_statistics`, because its later queries are not constrained by instructor course/session scope. The security summary's broad “all student data” wording and detailed enrolled-student access wording leave this scope ambiguous: classify it as **exposure requiring an explicit policy**, rather than asserting a definitively prohibited disclosure without clarification.

Same-course review rights may legitimately be course-wide: the review endpoint explicitly says “for the session's course.” Do not blindly replace every check with session ownership. Define separate course-read/review and session-mutation rules, share them, and test both directions. Provide an admin-supported TA assignment mechanism or seed workflow; the table currently has no management API.

### R02 - Critical before relying on device trust: trust restoration and missing proof

[devices.register_device:19][DEVICES] replaces `public_key`, sets `is_active=True`, and keeps existing `is_trusted`/`trust_score`. `update_device` also lets owners update activity. A nonblank arbitrary string passes key validation.

**Reproduced:** register with an invalid key → admin trusts it → admin deactivates it → owner re-registers with a different invalid key → **201, active=true, trusted=true**. Admin trust should not carry over to an unverified replacement credential.

Check-in submission has no key signature, server challenge, timestamp, nonce, or one-time consumption. Fingerprint lookup is inventory matching, not proof. The unique `(student_id, session_id)` constraint blocks duplicate attendance in one session but does not stop replay across sessions or stolen evidence.

Fix key parsing/proof, revoke trust on replacement, distinguish owner deactivation from administrative revocation, and define an atomic expiring challenge bound to user/device/session/payload. Preserve the two documented legacy null keys until their owners supply real keys. The optional Module 3 attestation endpoint need not be implemented just to achieve this backend boundary.

### R03 - Critical release gate: live dependencies and repaired-code rollout

The backend's strict face boundary is correct in fixtures. The checked-in Module 3 implementations of `/face/enroll`, `/face/verify`, and `/liveness/check` raise **501**. This is recorded solely as a backend dependency blocker; its internal implementation is outside this audit. The backend correctly converts that to 503.

The repair document also explicitly says real-service verification/restart remain open and records 65 active/scheduled liveness-required sessions in its **historical** inventory. Do not assume that count is current. Inventory the intended integration database again. Explicitly disable optional liveness only where the owner chooses that policy; do not silently skip it. Face matching still requires a functioning verification service.

Docker is unavailable here. Rerun readiness, canonical migration verification, real Redis limits, and HTTP smoke tests on the intended deployment. Preserve existing data and use the recovery runbook where applicable; there is no reason to repeat an already-completed recovery or reset the database.

### R04 - Critical robustness fix: transaction/error paths

- [auth.register:47][AUTH]: `database.flush()` occurs before the `try` around commit. A concurrent duplicate escapes as `IntegrityError`.
- [services/enrollments.py:34][ENROLLSERVICE]: flush occurs inside the helper, before the ordinary route's later error handler. Bulk catches `HTTPException`, not this database error; admin path is also unprotected.
- [admin.bulk_create_users:99][ADMIN]: `except IntegrityError` references an unimported name. The synthetic unique-conflict branch produces **NameError**.
- [sessions.delete_session:171][SESSIONS]: an admin can reset a previously used session to `scheduled`; deletion then violates the existing check-in FK. Reproduced an uncaught **IntegrityError**. The admin status override is a documented setup tool, so protect deletion rather than simply removing the override.

Wrap the actual mutation/flush/commit boundaries, preserve rollback, use savepoints for per-item bulk failures, and return controlled documented errors. Add a safe JSON 500 boundary for unexpected failures; it must not substitute for fixing known errors. Fault-injection proves these branches today; real PostgreSQL simultaneous requests remain necessary regression coverage.

### R05 - High: incomplete enrollment capability and inconsistent eligibility

`create_accounts=true` is part of the authoritative API. [enrollments.bulk_enroll:76][ENROLL] rejects it with a clear explanation about absent secure credential recovery. That is an honest limitation, but the feature remains incomplete. Implement a defined invitation/credential-establishment flow, or obtain a documented scope change; do not invent insecure default passwords.

The shared enrollment service does not check course activity. Ordinary enrollment does; bulk/admin entry points do not. **Reproduced:** bulk enrollment into a soft-deleted course succeeds. Align eligibility in the shared service; explicitly document any admin test-only exception. Duplicate unknown emails are also classified as `already_enrolled` after the first occurrence even when no enrollment was created; return accurate per-row outcomes.

### R06 - High, required for completion: audit integrity and completeness

There is no update/delete API and no `updated_at`, but those facts do not enforce immutability. Synthetic ORM update and deletion of an audit event both succeeded. Canonical migrations contain no append-only privilege or trigger setup. Compose uses the same powerful database account for application and dashboard access.

Use a separate migration/operator role and restricted application/dashboard roles. Enforce append-only audit writes in PostgreSQL and verify attempted updates/deletes fail for the application identity. **Coordinate with `schema_contract.differences`: it currently rejects every non-internal public trigger**, so adding a trigger without updating the schema-readiness design would make the application unhealthy. Keep canonical head/contracts/tests synchronized.

Required event gaps:

- `checkin_attempted` has student/session identifiers but lacks the Security-required location details.
- Manual review emits `checkin_reviewed` only. Security's higher-priority event table calls for approved/rejected outcomes including reviewer/reason.
- Auto-rejection audit contributions exist, but a clear reason/critical-signal summary is not explicit; the risk audit is nevertheless much stronger than before repair.
- Attempts against an already-blocked account return before `login_failed` is written; auth/authorization/rate-limit denials have no consistent `security_violation` trail.
- Login success generally lacks device identity; profile updates use `profile_updated` while the API action catalogue says `user_updated`; administrative enrollments use another action name.
- No logout endpoint/event path exists, although logout is listed in the action catalogue. A new logout endpoint is an API design choice, not an already-specified required route.

Add structured, versioned event details with request correlation. Do not log passwords, images, templates, bearer tokens, or raw upstream payloads. Retention failures already log exceptions; expose failure/last-success state so operators do not have to infer it from logs.

### R07 - High before gradebook use: statistics and exports

**Reproduced:** one enrolled student with one rejected check-in yields session `attendance_rate=1.0`, but JSON export reports `attendance_rate=0.0` for the same session. [stats.py][STATS] counts all check-in rows; [export.py:88][EXPORT] divides approved rows by submitted check-ins. The latter is an approval fraction, not attendance over the roster.

The docs do not fully define whether pending/flagged attendance counts. Settle that explicitly; distinguish submissions, approved attendance, pending review, rejected attempts, and absences. Then use the same denominators everywhere.

Other defects/limitations:

- Course stats/export do not apply the documented default end date of today. Stats can include future/cancelled sessions in denominators.
- Rates use the current active roster, not enrollment at session time. Hard deletion/re-enrollment changes historical rates and can produce rates above 1.0; account for roster history or define a deliberate current-roster metric.
- Retention removes the underlying attendance after 30 days, while course statistics can span a semester. Define the supported reporting window and an approved aggregate/archive policy rather than silently showing a semester as missing attendance.
- Overview uses UTC day boundaries and groups counts by check-in date while denominators use session date. Early check-ins across midnight can misalign. The docs do not prescribe Singapore business-day buckets; define them before dashboard implementation relies on them.
- Exports contain only actual check-ins; absence rows are not generated. If the gradebook needs absences, agree and implement that projection.
- CSV uses raw user-controlled cells. The probe preserved `=1+1` as a student name. Neutralize spreadsheet formula prefixes in cell values, not just filenames.
- CSV is fully buffered despite `StreamingResponse`; exports, rosters, and some list/statistics queries are unbounded. Bound or stream large datasets.

### R08 - High: privacy lifecycle is not reachable end to end

`cleanup_expired_records` correctly deletes due check-ins and anonymizes manually scheduled users, removing devices and face hash. But no route or supported administrative operation assigns `User.scheduled_deletion_at`. Deactivation alone does not start the 30-day clock.

Add an authorized deletion-request/scheduling flow with immediate access policy and a 30-day deadline. Document how immutable audit logs retain required historical identifiers/emails/IPs: blanket PII deletion and indefinite audit retention need an explicit minimization policy. Do not simply delete audit evidence to satisfy cleanup.

The backend stores full submitted GPS precision. Briefing p.28 asks for limited precision; define a suitable stored precision after full-precision geofence calculation. Camera consent withdrawal prevents future enabled-biometric verification but does not itself erase an enrolled hash; define the intended withdrawal/deletion behavior.

### R09 - High: abuse prevention and performance limits

The Singapore boundary and venue distance code have useful tests, including island/boundary/IP behavior. The bundled map is a simplified **2016 land-boundary snapshot** according to its local README; do not treat it as live territorial coverage. Test actual integration venues and expected border behavior.

`ip_is_in_singapore` uses synchronous HTTP (3s timeout) and Redis from inside asynchronous `create_checkin`, before releasing the initial database transaction. The same async handler performs synchronous ORM operations; the face-enrollment handler does too. This can block the event loop under slow I/O. Each check-in finally takes an exclusive course-row lock, serializing finalization for students in the same course. Measure realistic contention before declaring 100-user readiness.

Use bounded offloading or an async data-access path; make IP-provider availability/cache behavior visible. Provider outage correctly returns 503 without attendance. No live-provider quota/reliability or latency measurement was performed here.

The first-forwarded-IP behavior is explicitly required for grading. On an exposed deployment a client can supply a private first address unless a trusted ingress overwrites the header. Preserve the required application contract while controlling the network boundary; do not claim forwarded GPS/IP fields are tamper-proof.

### R10 - High: input/error/resource hardening

Strong existing controls include UUIDv4 path parameters, enumerated roles/statuses, finite bounded numeric fields, password byte-length limits, ORM query parameters, and validation errors stripped of input/context payloads.

The image string limit is 14,000,000 characters, applied after request JSON parsing. There is no total request-body byte limit, decoded image-size/pixel limit at this boundary, or streamed/decompressed upstream-response cap. Image decoding is explicitly delegated to the service; document and test that responsibility rather than making both sides decode without purpose. Reject oversized requests early and bound service responses.

Pydantic's default extra-field handling silently ignores unsupported fields. This is visible in QR support and can hide client mistakes. Use explicit compatibility policy for input extras. JSON Unicode escapes protect wire representation, but decode back to ordinary strings; they are not a substitute for safe client text rendering.

### R11 - Medium, with feature-dependent priorities: database/design differences

The ORM contains users, courses, enrollments, sessions, checkins, devices, audit_logs, and course_tas. Eight tables do **not** mean the eight recommended tables are implemented: `risk_signals` is absent. JSON-in-TEXT `Checkin.risk_factors` and outcome-audit contributions provide an alternative representation, but cannot satisfy a direct SQL consumer expecting `risk_signals`.

Other recommended columns absent: course description/require-face/require-device flags; enrollment `dropped_at`; session description/actual start/end/updated_at/QR secret+expiry; device browser/OS/app/key timestamps/attestation/revocation metadata; check-in challenge type/hash/QR verification. Session coordinates/radius/threshold are materialized and required rather than nullable live overrides. These are design differences, not automatically required API failures: document equivalents and implement only the agreed interface requirements.

Existing positive constraints cover role/status/type, coordinate/risk/radius ranges, schedule/window ordering, globally unique device fingerprints, and enrollment/check-in uniqueness. Suggested additional DB guarantees include biometric score ranges, hash-format/face-enrolled consistency, nonnegative counters, and retained key lifecycle invariants. Recommended check-in-window and audit-IP indexes are absent; add indexes based on actual queries. Enrollment's composite unique index already starts with student_id, so do not claim it has no useful student index merely because a separately named one is absent.

Preserve canonical/legacy migration separation, checksums, advisory locking and backup evidence. Frozen schema readiness is intentionally strict: future legitimate tables/indexes/triggers/views require a new matching contract/head. Also benchmark `/health`, which does full catalog/metadata comparison on each call and has per-operation rather than one overall request deadline.

### R12 - Critical frontend connection issue; High browser/configuration work

Backend routes are `/api/v1/...`. Frontend interface calls `/auth/login`, `/auth/register`, and `/auth/refresh` relative to its base. Compose sets `NEXT_PUBLIC_API_URL=http://localhost:8000`, omitting `/api/v1`; the frontend README has the correct prefixed value. Its Docker build runs before that Compose runtime variable is provided. Freeze the correct **build-time browser base URL** with the frontend owner. This is a connection configuration finding, not a review of frontend quality.

The backend's CORS middleware allows both intended local origins, but does not expose `Retry-After` or `Content-Disposition` to browser JavaScript. Probe confirmed the missing expose-header response. Add both and test rate-limit/download behavior from the allowed origin. `CORS_ORIGINS` parsing accepts `*`, despite Security's exact-origin rule; validate it.

Compose hardcodes a known JWT secret, DB password, and shared database identity. A minimum length check does not make that JWT secret secret. Replace with required deployment configuration; restrict host exposure and direct database access. A dashboard choosing the recommended direct SQL route needs an actual read-only account, not the same credential as the backend.

### R13 - High for operational completion: observability and reproducibility

Prometheus is configured to scrape the backend's `/metrics`; no such route exists. `OTEL_EXPORTER_OTLP_ENDPOINT` is supplied but unused. Backend request latency/error/check-in metrics and trace propagation are absent. Add only the backend outputs required by the integration contract; implementing dashboard screens is out of scope.

The Dockerfile has useful staged test/production targets, startup migration, and schema-aware healthcheck. Remaining deployment work includes a verified image built from the repaired tree, reproducible environment/dependency setup, service availability/capability checks, backup/restore rehearsal, retention visibility, and dependency health ordering. Backend readiness currently measures DB/schema/Redis, not face capability: keep liveness/readiness semantics explicit and expose biometric dependency capability separately if necessary.

The large dirty/untracked working tree is a release risk: recovery migrations/contracts/scripts and verification repairs must travel together. Commit/package the complete tested set. The backend README still claims bcrypt 12 (configured default is 10), old distance-band scoring, unimplemented verification, and deferred routes that now exist. Rewrite the current-state sections. Historical evidence belongs in clearly dated sections, not contradictory startup guidance.

## 4. Testing Audit

### Existing coverage

- Security/schema tests: password hashing, TTL/token type/expiry, registration validation, consent updates, CORS, typed identifiers.
- `test_week3.py`: course/session/enrollment workflow, ownership/TA checks, session windows, duplicate constraints, GPS boundaries, account lockout/reset and SG-IP rules.
- `test_compliance*.py`: route presence, seeded stats, review/appeal, devices, exports, user visibility, retention and hash-only enrollment.
- `test_verification.py`: all verification-flag combinations; actual production HTTP client exercised against MockTransport; invalid JSON/fields/types/thresholds/statuses/transport; exact scoring boundaries and device/default behavior.
- Migration/readiness suites: SQLite migration upgrade/downgrade/backfill and PostgreSQL SQL generation; frozen-schema/readiness checks.
- **54 real PostgreSQL tests exist:** 35 migration/recovery/schema/device cases and 19 finalization/enrollment race cases. They were skipped here, not missing from the repository.

### Why green tests do not establish completion

The 231-pass run used a Redis double and existing auth/database/face fixtures. Some ordinary backend tests require real Redis without declaring that requirement clearly, producing failure cascades when it is absent. The production Lua branch is bypassed by the lightweight fake's lack of `eval`.

Some tests reflect existing behavior rather than validate semantics: seeded stats assert a flagged attendance record counts as full attendance; route inventory checks paths, not all methods/permissions/errors. Several compliance tests replace `get_current_user` directly and use SQLite without enabled FK enforcement. The stronger week-three fixture enables FKs, but disables commit expiry; real PostgreSQL race tests compensate only for their covered scenarios.

Public tests are useful but incomplete: privacy checks sometimes assert only when check-in returns 201, retention tests largely inspect response shape, and the public login limiter test accepts 401 even without limiting. Some tests omit `location_accuracy_meters`; observability tests request field names not in the authoritative API; a performance test requests authenticated course data without a token. Record these conflicts rather than changing requirements to manufacture a score.

No measured statement/branch coverage percentage, live HTTP public-suite result, load benchmark, or current full-service end-to-end pass was obtained.

### Tests required before integration

| Gate | Necessary verification |
|---|---|
| Correct access | Session-only instructor can read enrolled-student data; unrelated users denied; shared-course review/mutation scopes distinct; cross-course student statistics policy enforced; TA assignment/removal. |
| Failure paths | Concurrent registration/enrollment/bulk conflicts on PostgreSQL; partial bulk success rollback; no NameError; used-session delete guarded; JSON errors with no SQL/credential leakage. |
| Device security | Invalid key rejected; key replacement drops trust; admin revocation cannot be undone by owner; challenge expiry/replay/payload substitution/cross-session reuse fail. |
| Actual verification | Real enrollment → persisted hash → verify → check-in; mismatch rejected; malformed image/service outage produce no row; 400/409/503 client retry rules; all four flag combinations. |
| Privacy/audit | App DB role cannot update/delete audit events; required events/details appear exactly as intended; no image/token leakage; deletion request schedules cleanup; retained/review-linked rows and devices handled on PostgreSQL. |
| Dashboard/exports | Known roster with absent/approved/flagged/rejected students; consistent denominators; date boundaries/timezone; future/cancelled sessions; roster changes and >30-day reports; formula-safe CSV and CORS filename/retry headers. |
| Infrastructure | Fresh PostgreSQL migrate + existing DB readiness; 54 PG tests no unexpected skips; real Redis limits/TTL/Lua concurrency/outage; restart/backup/restore; image capability configuration. |
| Performance | Real HTTP 10-user baseline and at least the brief's 100-user stress target; slow face/IP/Redis/DB behavior; same-course lock contention; bounded large requests/exports; measure latency, errors and pool exhaustion. |

## 5. Integration Readiness

| Consumer/dependency | Usable now | Exact remaining blocker / release condition |
|---|---|---|
| Frontend | Login/register/refresh/profile/session discovery and check-in schemas | Correct `/api/v1` build-time base; expose browser headers; finalize device proof; handle 201 rejected separately from 400/409/503; deploy available verification capabilities. |
| Face recognition | Strict backend enrollment/verify/liveness adapter with safe failures | Actual provider at configured URL must implement the required success/status/threshold contract. Checked-in counterpart returns 501. Prove real enrollment and verification; explicitly decide optional liveness flags. |
| Dashboard | Session management, rosters, reviews, stats, exports, admin audit query | Fix session-based relationship denial, settle student/course scopes and rate semantics, formula-safe CSV, stable response shape; backend `/metrics` if monitoring used; read-only identity for optional direct DB access. |
| PostgreSQL/Redis | Migrations, recovery tooling, schema-aware health, atomic limiter implementation | Running intended infrastructure, correct URLs/credentials, fresh health/migration/race/Redis evidence, complete tested release source set. Current host Docker unavailable. |

The backend can integrate against fixtures today. **Safe real integration requires R01-R04 and R12's connection/secret fixes, plus the relevant audit/data-correctness gates for the intended use.** Backend completion additionally requires the documented missing features and privacy/auditing work; connection success alone is insufficient.

## 6. Prioritised Completion Plan

### Critical: before integration sign-off

1. **Establish a reproducible integration environment.** Start the intended PostgreSQL/Redis and deploy all repaired backend files; verify schema/head/readiness without resetting data. Replace shared known JWT secret. Confirm real face capability and explicitly selected verification flags. Exit: working real enrollment/check-in with failure cases.
2. **Repair access consistency (R01).** Centralize relationship rules; fix session-only instructor denial; choose/document cross-course scope. Exit: positive and negative API tests for unassigned/shared courses and TAs.
3. **Fix transaction failures (R04).** Import the exception, catch actual flush failures, safeguard session deletion, standardize JSON failures. Exit: PostgreSQL race/failure tests return controlled responses with correct rollback.
4. **Fix device trust and agree binding (R02).** Do not integrate a “trusted device” flow that can restore revoked trust by re-registering. Exit: key/revocation/proof/replay tests and agreed frontend payload.
5. **Freeze consumer contracts (R12/R07).** Correct browser base URL/build config; expose headers; agree arrays/envelopes, error/retry rules and attendance definitions before clients depend on them.

### High priority: complete during Recess Week

- R05: documented bulk account creation and consistent enrollment eligibility.
- R06/R08: DB-enforced immutable audit, complete events, deletion scheduling, observable cleanup and explicit PII/location policy.
- R07: reliable attendance/date/roster semantics, CSV safety and report retention behavior.
- R09/R10: replay/location-history/network baseline, bounded I/O/payloads, remove event-loop blocking hot paths, test real load.
- R13: backend metrics needed by Module 4, release/deployment evidence and current documentation.

### Medium priority: important, not universally connection-blocking

- Implement or formally document alternatives to recommended `risk_signals` and optional metadata/QR fields; elevate any item required by a chosen consumer.
- Add useful DB checks/indexes, controlled TA provisioning, predictable pagination and bounded exports.
- True refresh-token rotation/revocation and a logout design if required by the security posture. Existing refresh behavior satisfies the basic documented route.
- Improve capability reporting, connection reuse, retention scheduling across workers, and tracing beyond the agreed integration minimum.

### Low priority / cleanup

- Remove unused imports/classes, simplify compatibility wrappers, align names and action catalogues.
- Replace stale Week 2/3 descriptions; separate historical test evidence from current release instructions.
- Add nonbreaking aliases only where an agreed consumer needs them; do not rewrite authoritative fields to match old public tests.

### Suggested execution order

**Days 1-2:** environment/release baseline, R01 access, R04 failure paths, API contract freeze. **Days 3-4:** R02 device trust/proof, real face-service flow, R05 enrollment. **Days 5-6:** audit/deletion, dashboard/export semantics, limits/metrics. **Final day:** full PostgreSQL/Redis/API integration and load rehearsal, documentation and clean release evidence.

This is a sequence, not a promise that missing anti-fraud features fit a fixed number of hours. If time is tight, explicitly record deferred optional functionality; do not mark required missing behavior complete.

## 7. Final Backend Completion Checklist

- [ ] Ship a complete versioned backend tree; fresh PostgreSQL migration and existing-database schema/readiness pass without data loss.
- [ ] Use private JWT/DB configuration; real Redis limits and account lockout pass, including concurrency and outages.
- [ ] Fix session-only instructor access; test shared-course, unrelated-course and TA permissions consistently.
- [ ] Fix registration/enrollment/bulk conflict handling, missing exception import, used-session deletion, and JSON error responses.
- [ ] Implement documented bulk account creation and one shared enrollment eligibility policy.
- [ ] Validate device keys; invalidate trust on key changes; enforce administrative revocation; verify signed fresh check-in evidence and replay rejection.
- [ ] Demonstrate real face enrollment/matching through the backend; explicitly configure optional liveness; retain safe 400/409/503 and stored-rejection behavior.
- [ ] Add DB-enforced audit immutability and required redacted events; keep schema contracts compatible with the enforcement mechanism.
- [ ] Provide deletion scheduling and test 30-day cleanup, audit retention, consent withdrawal policy and appropriate GPS precision.
- [ ] Make statistics and exports agree on attendance, dates, absences, roster changes and the 30-day reporting limit; neutralize CSV formulas.
- [ ] Correct the frontend-facing API base/build configuration, CORS exposed headers, and consumer payload/status contracts.
- [ ] Bound request/service-response sizes and slow dependency I/O; implement the agreed backend anti-fraud baseline.
- [ ] Expose required backend metrics and cleanup/dependency diagnostics; verify Docker startup, health, restart and backup recovery.
- [ ] Run all backend tests with real dependencies, including the 54 PostgreSQL cases; add regressions for this audit's probes and real-service/browser/API workflows.
- [ ] Complete realistic concurrent-load checks; resolve/document public-test specification conflicts; publish current run instructions and remaining optional scope.

Completion means these invariants are demonstrated on the intended release environment, not simply that all routes respond or a fixture-only suite is green.

[BRIEF]: C:/Users/Lenovo/Desktop/Study/SC3099/Briefing.pdf
[PDF2]: C:/Users/Lenovo/Desktop/Study/SC3099/Module2-Backend-Design.pdf
[GRADE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/GRADING-CLARIFICATIONS.md
[SEC]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/SECURITY-REQUIREMENTS.md
[API]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/API-SPECIFICATION.md
[DBSPEC]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/recommended_design/DATABASE-SCHEMA.md
[INTEGRATION]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/recommended_design/INTEGRATION-GUIDE.md
[RECOVERY]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/F00-DATABASE-RECOVERY.md
[REPAIR]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/CHECKIN-VERIFICATION-REPAIR.md
[AUTH]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/auth.py:29
[AUTHSCHEMA]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/schemas/auth.py
[TOKENS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/security.py
[USERS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/users.py
[FACE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/face_service.py
[COURSES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/courses.py
[SESSIONS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/sessions.py
[ENROLL]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/enrollments.py
[ENROLLSERVICE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/enrollments.py
[ADMIN]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/admin.py
[CHECKINS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/checkins.py
[RISK]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/risk.py
[GEO]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/utils/geolocation.py
[DEVICES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/devices.py
[STATS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/stats.py
[EXPORT]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/export.py
[AUDITROUTER]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/audit.py
[AUDITHELPER]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/audit.py
[MODELS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/models.py
[RETENTION]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/retention.py
[ACCESS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/access.py:75
[PROBES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit-2026-09-29/probe-results.json
[RAWTESTS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit-2026-09-29/backend-tests.xml
[STUBTESTS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit-2026-09-29/backend-tests-redis-double.xml
# Completion update — 29 September 2026

The audit below is the original implementation baseline. Current findings and
all 23 outstanding requirement dispositions are in the
[completion report](backend-completion-2026-09-29.md) and
[requirement register/contracts](../docs/BACKEND-COMPLETION.md).
R01, R02 and R04–R13 backend work is complete. R03's backend deployment/recovery/
load portion is implemented and verified; real biometric interoperability is
explicitly deferred by the user because no functioning service/approved fixture
exists. The backend must not be called fully integration-ready until that gate
passes. Optional exclusions remain separate from required work.

