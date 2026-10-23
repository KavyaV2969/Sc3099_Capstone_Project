# SC3099 Module 2: Backend audit

> **F00 resolution update (28 September 2026):** The existing PostgreSQL database
> has since been reconciled to `20260928_0006`, with every original record preserved
> and one recovery audit event appended. All 173 backend tests passed, including
> 35 PostgreSQL tests; ORM check-in reads, Alembic validation and schema-aware
> health now pass. See the [recovery runbook](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/F00-DATABASE-RECOVERY.md).
> The audit below records the original inspection snapshot; its F00 failure is
> resolved. Later repair notes below supersede the specified findings; other
> findings retain their original status.

> **Verification/scoring repair update (28 September 2026):** F01's legacy
> scorer and omitted-liveness bypass are removed. F02's permissive service response
> validation and enrollment acceptance are repaired. F04 finalization now refreshes
> locked eligibility and detects policy/hash changes; F13's configured risk-default
> omission is repaired. **285 tests pass, including 54 real PostgreSQL tests, no
> skips**. Existing database values/counts and revision `20260928_0006` are preserved.
> See the [implementation and rollout record](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/CHECKIN-VERIFICATION-REPAIR.md).
> Device proof/network detection (F05/F06), broader image/response hardening and
> unrelated findings remain open. Module 3 was unavailable, so live interoperability
> is unverified; 65 active/scheduled liveness-required sessions need owner review
> before deployment. Original findings below remain historical inspection evidence.

**Audit date:** 28 September 2026. **Planning context:** Recess Week between Weeks 7 and 8, as specified by the user. **Scope:** Module 2 only; other modules were inspected only for interfaces that directly affect backend integration.

## Evidence and requirement precedence

I read both supplied PDFs, all five documents under `docs/`, the backend application, schemas, migrations, configuration, backend tests, and backend-facing public tests. The PDFs are source material, not instructions to perform the tasks they describe. No implementation fixes were made and no existing PostgreSQL records were changed.

The authoritative order is [grading clarifications][DOC-GRADE] → [security requirements][DOC-SEC] → [API specification][DOC-API] → [recommended database design][DOC-DB] and [integration guide][DOC-INTEGRATION] → PDFs. The first four levels are explicitly stated in `GRADING-CLARIFICATIONS.md`; the PDFs are subordinate under the user's instruction. Backend README history and public tests do not override these requirements.

Important decisions resulting from this precedence:

- Login and registration limits are **100,000/hour/IP**, not the PDFs' 60/hour and 10/hour. General authenticated API calls remain 1,000/hour/user; check-ins remain 10/minute/user.
- Ten consecutive failed passwords block an account; the tenth and subsequent attempts, including a correct password, return 429 until administrative reactivation.
- Check-ins require Singapore GPS and a Singapore public IP, with local/private addresses allowed. The first `X-Forwarded-For` address takes precedence.
- Admin session creation is allowed by the security endpoint matrix, despite the API endpoint description saying instructor-only.
- Course-level `instructor_id` is an explicitly permitted nullable extension. It is not a missing required field.
- Closed sessions may be cancelled under the API specification. The README's older statement that closed sessions are terminal is obsolete.
- Face enrollment and verification are core interfaces. Liveness is explicitly a **bonus** in the API specification; nevertheless, a session advertising `require_liveness_check=true` must have an honest, enforced meaning.
- Public role selection, including `admin`, is explicitly accepted by the API and Briefing p.24. It is a grading design limitation, not an accidental privilege escalation to fix by silently changing the contract.
- HTTPS/TLS is explicitly **not required**. Its absence is not a completion blocker.
- Endpoint-specific array responses take precedence over the API document's blanket pagination statement. Tests expecting a different shape are recorded as conflicts rather than used to change the authoritative contract.

Verification performed:

| Check | Observed result | What it establishes |
|---|---|---|
| Existing `module2-backend/tests` | **132 passed in 25.23 seconds** | A substantial baseline, mostly isolated SQLite tests; one test checks actual PostgreSQL connectivity. |
| Current OpenAPI inventory | **50 operations under `/api/v1`, plus `/health`** | Broad endpoint coverage; presence alone does not prove correct behavior. |
| Six backend-facing public test files over actual HTTP | **60 passed, 14 failed; 54/72 points** | Contract behavior on a disposable database migrated through the checkout's head. This is a selected-suite result, not a full-project grade. |
| Isolated negative/edge probes | **18 recorded scenarios** | Reproduced bypasses, races, inconsistent ownership, broken error paths, and device-trust issues. |
| Local PostgreSQL migration status/schema check | **Both fail: missing revision `20260911_0007`** | The actual database does not correspond to this checkout's migration history. |
| Read-only PostgreSQL schema comparison | Multiple differences; ordinary `Checkin` ORM read fails | This is actual schema incompatibility, not merely an unusual version label. |

The public HTTP run used unmodified supplied tests and backend application code, a freshly migrated disposable SQLite database, and real Redis with a unique audit key namespace. Retention was disabled for this temporary server. It did not use or alter the existing PostgreSQL data. Face-service calls were mocked only in separate diagnostic probes. The temporary HTTP server was stopped after testing.

Evidence files: [public HTTP output][E-PUBLIC], [public JUnit result][E-XML], [isolated probe results][E-PROBES], and [database inspection][E-DB]. These distinguish executed results from findings established by code inspection. No comprehensive dependency scan, real face-service integration run, production PostgreSQL concurrency run, or percentage coverage measurement was performed.

# 1. Overall Backend Status

**Verdict: substantial implementation, but not complete and not safely integration-ready.**

The backend is much further along than its Week 3 README suggests. It already contains authentication, courses, enrollments, sessions, check-ins, review/appeals, devices, four statistics routes, exports, audit querying, face-service wrappers, and a retention worker. Its main problem is correctness across these features, not lack of route skeletons. An exact completion percentage would be misleading: endpoint count substantially overstates security and deployment readiness.

### Major strengths

- Clear FastAPI router/domain organization, Pydantic request/response models, and reusable access/enrollment/query helpers.
- HS256 access/refresh JWTs with correct default lifetimes and token-type enforcement; bcrypt hashing and password byte-length checks; sensitive password fields omitted from responses.
- Real database-backed ten-failure account lockout with a PostgreSQL row lock and administrative recovery.
- Atomic Redis rate-limit implementation in the production Lua branch; exact clarified limits and `Retry-After` handling.
- Functional course → enrollment → session → check-in flow with active-enrollment, consent, status, time-window, coordinate, and Singapore checks.
- Database uniqueness constraints for student/course enrollment and student/session check-in, not merely pre-insert checks.
- Migrations through `20260915_0005`, including existing-record retention backfill, with isolated migration tests.
- No raw face-image/embedding storage in backend models. Face enrollment persists only a validated 64-character hash.
- Review and appeal workflows are implemented, including a seven-day appeal window, one appeal, and review-state guards.

### Major gaps

1. **The live database is incompatible with the current checkout.** It reports `20260911_0007`, absent from the repository, and lacks current check-in columns.
2. **Biometric enforcement is permissive.** Omitted liveness and empty upstream result objects can lead to approved attendance.
3. **Two incompatible risk policies coexist.** An undocumented legacy branch bypasses the configured threshold, device risk, and GPS-accuracy risk.
4. **Final check-in validation is stale.** Session closure, account deactivation, or policy changes during biometric work can be missed.
5. **Device registration is not cryptographic binding.** Trust survives key replacement/removal and owner reactivation of a device deactivated by an admin.
6. **Ownership is inconsistent.** Session owners of unassigned courses can manage rosters but cannot retrieve enrolled-student profiles/statistics.
7. **Compliance and operations are incomplete.** Audit immutability is not enforced in PostgreSQL; deletion cannot be scheduled through a supported workflow; metrics/tracing and schema-aware readiness are absent.

The existing native test result does not contradict these findings. Much of that suite asserts the older GPS-only behavior, and the PostgreSQL health test checks `SELECT 1`, not model/schema compatibility.

# 2. Requirement-by-Requirement Audit

**Status meaning:** Complete = implementation satisfies the named requirement within the stated scope; Partial = useful implementation with material omissions; Missing = no implementation of the named behavior; Incorrect = observed behavior contradicts the governing requirement or a necessary invariant. A Complete code feature still cannot be deployed against the currently incompatible database.

All routes below are relative to `/api/v1` unless stated otherwise. Requirements refer to the named sections in [API][DOC-API], [Security][DOC-SEC], [Clarifications][DOC-GRADE], [Schema][DOC-DB], and [Integration][DOC-INTEGRATION]. Finding IDs refer to section 3.

| Requirement / expected behavior | Current implementation and relevant files/routes | Status | Required fixes |
|---|---|---|---|
| Registration: valid email, ≥8-character password, four roles, bcrypt ≥10, duplicate rejection. Security Authentication; API `/auth/register`. | [Auth router][AUTH], [auth schemas][AUTH-SCHEMA], [security helpers][SECURITY]. Defaults to bcrypt 10; normalizes email; bounds UTF-8 bytes to 72; returns 201. Sequential duplicates return 400. A concurrent duplicate may fail at an unprotected `flush()`. | Partial | Catch constraint errors around both flush and commit; F09. Role selection itself follows the contract. |
| Login: correct credentials return access+refresh+user; disabled account denied. | `auth.login()` validates bcrypt, account state, writes login events. API/public authentication tests pass. | Complete | Preserve this behavior; improve logging of attempts on already-blocked accounts under F11. |
| JWT algorithm/lifetimes/type/signature/expiry checks; protected requests check current database user. | `security.py`, [dependencies][DEPENDENCIES]. 1-hour access, 7-day refresh, HS256 allowlist, required claims, inactive-user denial. RBAC uses database role rather than trusting an old token role. | Complete | Protect the signing secret in deployment; do not mistake token issuance for server-side revocation. |
| Ten-failure account lockout and administrative reset. Clarifications Account lockout. | `auth.login()`, `admin._set_account_status()`, migration `0003`; counter persisted, row locked, tenth/later requests 429, successful pre-block login resets. | Complete | Add real concurrent PostgreSQL proof and blocked-attempt audit events. Existing access/refresh sessions are not revoked; the clarification does not require that. |
| Refresh validates refresh type and active account, returns token pair. | `auth.refresh()` and token helpers work; no token registry, nonce, consumed-token tracking, or true refresh-token rotation. | Complete for documented refresh; Partial for the code's claimed rotation | Correct the docstring or add rotation/replay detection as hardening; F15. |
| Own profile read/update and explicit consent flags. API `/users/me`. | [Users router][USERS], `UserProfileUpdate`: rejects empty/null updates; consent stored; no role/password mass assignment. | Complete | Add withdrawal-policy tests; distinguish withdrawing consent from deleting data. |
| Admin user list/update and instructor access to enrolled-student details. | `users.list_users()` / `update_user()` implemented. `get_user()` depends on an incomplete relationship helper. | Partial | Unify course/session teaching relationship; F03. |
| Face enrollment through backend with camera consent and hash-only persistence. API `/users/me/face/enroll`, `/face/enroll`. | `users.enroll_my_face()`, [face client][FACE]. Consent and hash format checked; upstream success accepted even at quality 0.1; malformed responses can raise uncaught `ValidationError`. | Partial | Endpoint-specific strict response models, required fields, consistent errors, enrollment quality sanity checks; F02. |
| Course CRUD/filtering, admin mutations, soft deletion. Optional instructor extension permitted. | [Courses router][COURSES], `CourseCreate/Update`; updates validate fields, code unique, optional assignment validated; deletion deactivates course. | Complete for core API | Add/document course security defaults absent from the recommended model; F12. Honor global risk-default setting; F13. |
| Enrollment creation validates student/course; rosters restricted to course staff/admin; duplicate prevention. | [Enrollment router][ENROLL], [enrollment service][ENROLL-SERVICE]. Normal route blocks inactive course; service lacks that guard, so admin/bulk paths can enroll into inactive courses. | Partial | Put domain validation in the shared service; handle concurrent uniqueness violations consistently; F09. |
| Own enrollments and enrollment removal. API enrollment endpoints. | Own list filters active enrollment/course; delete removes row; history of check-ins remains. Hard deletion is allowed by the API's remove contract, although the recommended schema includes `dropped_at`. | Complete for core API | Document historical-roster implications; optional soft-drop history under F12/F14. |
| Bulk enrollment supports known emails and `create_accounts=true` for unknown emails. API `/enrollments/bulk`. | Known-email path exists. `create_accounts=true` always returns 422 by deliberate code policy. Inactive-course validation and race handling are incomplete. | Partial; account-creation subfeature Missing | Implement secure credential activation/recovery for created accounts, or obtain a documented requirement revision. Code's rationale does not override the API; F09/F12. |
| Session create/list/detail/update/delete, schedule ordering, inherited defaults and time windows. | [Session router][SESSIONS], [attendance schemas][ATT-SCHEMA]. Defaults −15/+30 minutes; validates future creation and resulting partial-update ordering; filters and ownership implemented; scheduled-only deletion. | Complete for ordinary workflow | Resolve deletion when the admin test endpoint reschedules a session with check-ins; F09. |
| Session status transitions and administrative status setup. | Ordinary transitions scheduled→active→closed and closed→cancelled align with the API. Admin endpoint deliberately allows arbitrary statuses for test setup. | Complete for status-setting contract | Preserve required admin setup behavior while preventing invalid downstream deletion and making overrides explicit/audited. |
| Public active-session discovery and personalized sessions. | `/sessions/active` filters status/window/active course; `/my-sessions` scopes enrolled student, own instructor sessions, assigned TA. Session detail is readable by any authenticated user, as the API permits. | Complete | Do not invent an enrollment requirement for the general detail route; review unnecessary public metadata separately. |
| Check-in must require student role, active session/course/enrollment, valid window, proper consent, and uniqueness. | [Check-in router][CHECKINS] enforces these at initial submission and tries to revalidate after upstream calls. Cached state makes final validation unsafe; current user activity/role is not rechecked. | Partial / Incorrect under concurrent change | Reload and lock fresh eligibility/policy state at finalization; F04. |
| Singapore GPS and client-IP enforcement. Clarifications Singapore-only check-ins. | [Geolocation][GEO], `rate_limit.client_ip()`: bundled land polygons, first forwarded address, local allowlist, public country lookup cached 24h; lookup failure returns 503. | Complete for implemented clarified policy | Real-provider deployment test, boundary caveat and trusted-edge configuration; F07. GPS country checking is not proof against spoofed GPS. |
| Haversine distance and critical rejection beyond 2× geofence. | `haversine_distance()` correct; coordinate/finite-number validation; both scoring paths reject beyond 2× radius. Existing tests cover exact boundaries. | Complete | Preserve unconditional critical rejection when consolidating scoring. |
| Weighted risk, configured threshold, accuracy/device/network inputs, critical biometric failure. Security Risk Scoring; API Check-in Status Logic. | [Risk engine][RISK] has correct five weights, but check-in legacy branch bypasses it; missing evidence gives zero biometric risk; `local_network=True` is hardcoded. | Incorrect | Use one documented policy and explicit missing-signal treatment, real network/device evidence, consistent factors; F01/F06. |
| Face-required sessions perform verification against enrolled hash and cannot approve missing verification. | `_biometrics()` calls `/face/verify` with correct field names and requires an image/enrolled hash. Empty `{}` result accepted as all-null; approval can follow. | Incorrect | Require usable verification results; enforce 0.7 contract consistency; fail closed on malformed required evidence; F02. |
| Liveness-required session behavior, without confusing bonus availability with enforced policy. | `_biometrics()` skips liveness when no image. Such requests can be approved while requirement is true. | Incorrect | Require evidence when enabled; explicitly set false when bonus is disabled; enforce usable 0.6-consistent result; F01/F02. |
| Check-in lists/history/detail/flagged queue and staff visibility. | All routes implemented using joined queries and serializer. Instructor list filters and resource-access helper use different definitions of teaching relationship. Endpoint-specific arrays match API text. | Partial | Share one explicit access-scope policy across lists/details/analytics; F03. Keep written shapes unless amended. |
| One owner appeal within 7 days; only flagged/rejected; review flagged/appealed by course staff. | `appeal_checkin()` / `review_checkin()` implement conditions, locks, review metadata and `verified_at`. Positive route tests pass. | Complete for sequential workflow | Add denial/boundary/concurrent tests and required outcome audit events; F11. |
| Register/list/update/deactivate own devices, admin-only trust changes. | [Device router][DEVICES] implements routes and ownership; owner cannot PATCH trust. Owner can re-register an admin-deactivated device and keep trust while replacing/removing its key. | Partial / Incorrect trust lifecycle | Invalidate trust on key change/revocation; distinguish admin revocation; flush before registration audit; F05/F11. |
| Device binding and replay resistance. Briefing p.26 and p.39; Security device-attestation weight; recommended device design. | Fingerprint lookup only. No check-in signature, challenge nonce, proof of key possession, expiry, or replay cache. Public keys are arbitrary optional text. | Missing binding/proof; Partial device inventory | Implement a signed, time-limited check-in challenge if claiming binding/replay resistance; F05/F06. Module 3's optional `/device/attest` endpoint is not independently a mandatory backend route. |
| Dashboard statistics: four documented routes, zero-safe aggregates and scope. | [Statistics router][STATS] implements all four and API-shaped payloads. Session-owner/student relationship bug; default course end bound ignored; cross-course exposure policy unclear. | Partial | F03/F14; distinguish required API contract from older public-test field names. |
| Course/session CSV/JSON exports with permissions and audit. | [Export router][EXPORT] implements both. CSV formatting/download headers correct. JSON session rate uses approved/check-in-records, not enrolled students; CSV cells are not protected against spreadsheet formulas. | Partial | Fix denominator and gradebook semantics; CSV formula neutralization; browser header exposure; F08/F14. |
| Audit log read/filter/pagination, all required security events and append-only behavior. | [Audit router][AUDIT] exists; no mutation API. No database immutability protection; missing/misaligned event details and incomplete failed-attempt coverage. | Partial | Database append-only restrictions, event completeness and safe payloads; F10/F11. |
| Thirty-day check-in retention. Security Data Retention. | [Retention service][RETENTION] deletes due rows; check-ins schedule +30 days; migration backfills old rows; lifespan worker enabled by default. | Complete cleanup logic; Partial operational assurance | Reconcile database, observe last cleanup/failure, test real FK behavior and restart recovery; F10/F13. |
| User PII removal 30 days after deletion; right-to-deletion. Security Data Retention; Briefing pp.27–28. | Cleanup anonymizes a manually scheduled user and removes devices; no route or supported administrative workflow sets `scheduled_deletion_at`. Deactivation does not schedule deletion. | Partial cleanup; Missing request/scheduling workflow | Implement/document deletion scheduling, safe anonymization and retention policy; F10. Keep required indefinite audit logs. |
| Recommended database `risk_signals` and metadata fields. | [Models][MODELS] has eight tables, but one is `course_tas`; `risk_signals` is absent. Several recommended columns absent; factors are JSON-in-TEXT on check-ins. | Partial recommended design | Adopt missing needed fields/table or document an approved equivalent; F12. Eight-table count alone does not mean recommended schema coverage. |
| Input validation/SQL injection resistance/XSS. Security Input Validation. | Typed UUIDv4 paths, bounded enums/coordinates, parameterized ORM, sanitized JSON wire characters; validation errors omit raw input/ctx. Large image string accepted without base64/image validation. | Partial | Image/body validation and limits, consistent error handling, CSV safety; F02/F08/F09. JSON escapes decode back to original strings, so clients must still render text safely. |
| CORS exact origins and browser-readable error/download headers. | [App assembly][MAIN] uses exact local origins/config override; both preflight tests pass. No `expose_headers`; wildcard values are not rejected by settings. | Partial for browser integration | Expose `Retry-After` and `Content-Disposition`; validate allowed origin configuration; F08/F13. |
| Docker/configuration/schema readiness and safe error responses. | [Dockerfile][DOCKER], Compose, settings and `/health` exist; startup migrates. Current DB fails migration resolution; health can still say healthy. HTTP 500 JSON handler/request correlation missing. | Incorrect current environment; Partial setup | F00/F09/F13. Do not stamp or delete the existing database as a shortcut. |
| Backend metrics and distributed tracing interface. Integration metrics/env; Briefing p.6. | No `/metrics`, Prometheus instrumentation, OpenTelemetry setup, or OTLP configuration consumption. Dependencies include neither instrumentation library. | Missing | Implement backend metrics/tracing needed by Module 4; F13. This audits backend outputs, not dashboard implementation. |
| Test-only `/audit/summary`, `GET /devices/`, legacy analytics/queue/export shapes. | These extra routes/shapes are absent. Backend native test explicitly expects no `/audit/summary`. Public HTTP tests fail on them. | Missing test-only extensions; written-contract differences | Reconcile with course authority or add harmless compatibility extensions. Do not describe these as missing requirements in the current API document. |

# 3. Backend Architecture Audit

### F00 — Critical: migration history and actual database disagree

The checkout's Alembic head is `20260915_0005`. The database version is `20260911_0007`; no file defines that revision. Both `alembic current` and `alembic check` fail with “Can't locate revision identified by '20260911_0007'”. Read-only schema inspection confirms missing `checkins.verified_at`, reviewer/appeal metadata and `scheduled_deletion_at`, missing expected indexes, and incompatible device constraints/types. An ordinary `select(Checkin).limit(1)` raises `ProgrammingError: column checkins.verified_at does not exist`.

This breaks check-in reads/writes, review/appeal flows, retention and normal startup. `/health` still returns healthy because [health_check()][HEALTH] tests database connectivity and Redis rather than schema readiness. The native connectivity test therefore passes against a schema the application cannot use. At inspection, PostgreSQL and Redis were running; the backend container was not running.

**Fix:** identify and recover the migration history responsible for `0007`, back up the database, compare its schema with the intended model, and create a reviewed reconciliation migration. Separately prove this checkout can bootstrap an empty PostgreSQL database. Never blindly stamp to `0005`, reset the version, or remove the volume: that conceals incompatibility and risks the existing records. The inspected database contains 403 users, 99 courses, 77 sessions, and 9 check-ins.

### F01 — Critical: bypassable, duplicated risk/check-in policy

**Current status:** repaired by weighted-v1 and required-image enforcement; old reproductions below describe the original snapshot.

[create_checkin()][CHECKINS] lines 106–124 chooses the old GPS-only policy whenever no active registered device is found and all biometric fields are null. Inside the radius it returns approved/risk 0 with no factors. That path ignores `session.risk_threshold`, GPS accuracy, unknown-device risk, and missing required liveness. It has no explicit documented feature flag or mode.

Executed reproductions:

- `require_liveness_check=true`, omitted image, unknown device, GPS accuracy **10,000 m**, threshold **0**: **201 approved**, risk **0**, `liveness_passed=null`, empty factors. The API's score `>= threshold` rule should not auto-approve at threshold zero.
- Approximately **150 m** from a **100 m** venue: unknown device uses the legacy branch and flags at **0.5**; registering the same fingerprint with an untrusted arbitrary key switches to weighted scoring and approves at **0.25**. The inconsistency comes from selecting a different policy, not from cryptographic proof or improved location evidence.

**Fix:** remove the hidden fallback, or replace it with an explicitly specified optional mode that still respects threshold, required evidence and critical rejection. Keep one deterministic signal pipeline. Update Week 3 tests that currently lock in null-liveness approvals and 0/0.5/1 scoring. Those older tests do not override Security Risk Scoring or the current API.

### F02 — Critical: weak face-service result validation; Partial integration

**Current status:** endpoint response validation, controlled failures and enrollment quality/confidence checks repaired. Broader image/body/decompressed-response hardening and live-service integration remain open.

[FaceResult][FACE] makes all pass booleans and scores optional and defaults enrollment quality to zero. The same model serves three different upstream operations. Consequently, `{}` is valid for verification/liveness. A face-required, liveness-required session with an enrolled student and image was **approved with both results null** when the service returned `{}`.

Other reproduced weaknesses:

- A response with an invalid hash raises uncaught Pydantic `ValidationError` outside `_post()`'s exception conversion. Over HTTP this becomes an ordinary server error rather than the documented 400/503 behavior.
- Enrollment reporting success and quality **0.1** is accepted and persists `face_enrolled=true`. This contradicts the upstream contract's success criterion of quality ≥0.5; the backend does not reject this inconsistent service response.

The happy-path interface is correct: `/face/enroll` sends user ID/image/consent; `/face/verify` sends image/reference hash; `/liveness/check` uses the documented passive challenge. Network timeout/HTTP errors are converted to service errors, and no raw image is written to backend persistence. There is no real-service interoperability evidence from this audit.

**Fix:** separate required enrollment/verification/liveness response schemas; reject missing fields, invalid scores and inconsistent pass/threshold claims; convert response-schema failures to controlled 502/503 responses; ensure required verification never disappears into nulls. Validate base64/image content or establish and test a strict upstream validation boundary. Add body/decompressed-response limits and service-call telemetry. A missing optional liveness capability may be disabled explicitly; enabling it and approving omission is unsafe.

The lower-priority integration guide demonstrates proceeding after a liveness timeout. Treat that as an example requiring an explicit optional-verification policy, not a basis for silently satisfying a required verification flag.

### F03 — High: access-policy definitions diverge

[can_manage_course()][ACCESS] recognizes either optional course assignment or ownership of an existing session. [instructor_has_student_relationship()][RELATIONSHIP] recognizes optional course assignment/TA assignment only, omitting session ownership. Therefore an instructor who creates a session on an unassigned course receives **200** for that course's roster but **403** for an enrolled student's profile and statistics. This affects the documented common case where courses have no assigned instructor.

Instructor list/flagged queries filter optional course assignment or current session ownership, while session/check-in detail authorization grants course-level access through any owned session. Course-level check-in access is explicitly allowed by the API; it is not automatically unauthorized just because another instructor owns that session. The defect is inconsistency and the absence of a clearly shared scope definition.

`student_statistics()` also returns a student's other enrolled courses/recent check-ins once any relationship is found. A probe returned both `SC3099` and an unrelated `OTHER` course. The specification returns a course list and Security's role summary broadly mentions student data, so this is **an authorization/privacy policy ambiguity**, not an asserted unambiguous violation. Decide and document whether cross-course student analytics are intended; default to least exposure for integration.

**Fix:** centralize an explicit teaching/TA relationship and reuse it for user profiles, statistics, lists, reviews and exports. Test unassigned and shared courses, unrelated users, and the chosen cross-course policy. Provide a repeatable TA-assignment seed/admin workflow: `course_tas` is currently writable only through direct database seeding, although no TA-management API is specified.

### F04 — Critical: stale finalization after asynchronous biometrics

**Current status:** repaired; 19 PostgreSQL tests cover eligibility/policy races, fresh settings, duplicate finalization and enrollment consent/activity races.

The route commits the initial attempt, awaits biometrics, then calls `get_session(..., lock=True)` and `_validate_eligibility()` again. A locking SQLAlchemy SELECT does **not** automatically overwrite an already-loaded entity's attributes. [get_session()][ACCESS] has no `populate_existing`/explicit refresh. `_validate_eligibility()` also does not recheck current user activity or student role.

Separate transactions during mocked biometric work reproduced all three cases with **production-style `expire_on_commit=True`**:

- Close the session → check-in still **201 approved**.
- Deactivate the account → check-in still **201 approved**.
- Enable required face matching after the initial policy read → check-in still **201 approved** with no face result.

These are isolated SQLite state-change simulations, not a PostgreSQL lock benchmark; they demonstrate the ORM freshness/policy problem. PostgreSQL concurrency tests are still required.

**Fix:** obtain fresh locked user/session/course/enrollment state at finalization, explicitly refresh identity-map entities, and compare the verification-policy version with the version used upstream. Reject/reverify when requirements change. Keep slow network work outside long-lived write locks. Protect course/enrollment deactivation races as well as session closure. Document transaction ordering to avoid deadlocks. Session-row locking currently serializes all final check-ins for the same session, so benchmark contention after correctness is fixed.

### F05 — Critical for security readiness: device inventory does not enforce binding

[Device registration][DEVICES] accepts an optional arbitrary public-key string; check-in accepts only a client-supplied fingerprint and never verifies a signature. Possession of a trusted fingerprint therefore substitutes for possession of the device's private key.

Executed lifecycle reproduction: register `invalid-key` → admin trusts it → admin deactivates it → owner re-registers same fingerprint with `public_key=null`. Result: **active=true, trusted=true, public_key=null**. Registration overwrites the key and reactivates the row without invalidating trust; deactivation does not revoke trust.

**Fix:** parse supported key formats, prove private-key possession, reset trust on key replacement/removal, record revocation source/reason, and prevent ordinary registration from undoing administrative revocation. Bind check-in proof to user, session, coordinates/payload digest, nonce and expiry, and atomically consume the nonce. If full platform attestation is deferred, clearly distinguish it from this basic binding requirement. The separate Module 3 `/device/attest` API is explicitly optional.

### F06 — High: anti-fraud inputs are incomplete

[assess_risk()][RISK] uses the documented five weights, but [check-in invocation][CHECKINS] hardcodes `local_network=True`, so the network contribution is always zero. A Singapore-country IP is not proof that it is local or free from VPN/proxy use. Device contribution uses existence/admin trust rather than signature validity. Missing biometric evidence contributes zero. No impossible-travel, rapid-succession, replay, or coordinate plausibility history is implemented in the backend; those responsibilities appear in Briefing pp.26 and 39 and the recommended risk-signal design.

There is no call to Module 3 `/risk/assess`, although [API Backend Integration][DOC-BACKEND-INTEGRATION] recommends such a wrapper. Local risk computation is a legitimate architectural alternative only if documented and behaviorally equivalent; here it omits required signal evidence and duplicates a second legacy decision policy. This finding does not assess Module 3's risk implementation.

**Fix:** choose one authoritative scorer and ownership of each signal; pass real IP/user-agent, verified device evidence, accuracy and biometric outcomes; enforce Singapore checks independently of the risk score. Record recognized factor types and confidence/contribution. Implement baseline replay and impossible-travel handling, or document explicit non-core scope for optional advanced detectors. Private/local addresses must remain allowed under the grading clarification.

### F07 — High operational dependency: geofencing and IP-country checks

The Haversine implementation and Singapore polygon/local-IP policy are sound for their stated input model. Public country results use Redis caching and a three-second HTTPS call to `ipwho.is`; provider/cache errors fail closed with 503. The dataset is a documented simplified **2016 land-boundary snapshot**; it is not a precise current coastline or territorial-water model. Close-to-boundary venue cases need tests.

The public IP lookup and synchronous Redis/SQL calls run inside the asynchronous check-in route, which can block its event loop. Cold IP lookup alone can take three seconds, beyond the public check-in latency goal of two seconds. [Integration service timeouts][DOC-INTEGRATION] and live performance need reconciliation through caching, asynchronous I/O or a bounded worker strategy.

The required first forwarded address is accepted from any request. This matches the grading contract but is spoofable if the backend is directly exposed. **Preserve the specified parsing rule**, and have a trusted edge strip/rebuild untrusted forwarded headers before real deployment. Do not reject local addresses merely to simulate VPN detection.

### F08 — High: export and browser-integration safety

[Export CSV][EXPORT] quotes fields via `csv.DictWriter`, but quotation does not stop spreadsheet formula execution. Names, session names and notes can contain `=`, `+`, `-` or `@` prefixes. Neutralize formula-leading text fields before producing gradebook CSVs.

`CORSMiddleware` does not expose `Retry-After` or `Content-Disposition`; cross-origin browser JavaScript cannot read these headers even though the server sends them. This directly affects the integration guide's rate-limit handling and downloading/naming exports. Add explicit exposed headers and browser tests.

The JSON renderer escapes HTML-significant characters at the wire level, which helps avoid unsafe embedding of raw JSON. JSON decoding restores those characters, so it is not a universal HTML sanitization guarantee for downstream consumers. Keep response contracts and require safe text rendering; do not blindly HTML-escape stored values and corrupt names.

### F09 — High: exception paths, concurrency and lifecycle inconsistencies

- **Confirmed bug:** [admin.bulk_create_users()][ADMIN] catches `IntegrityError` without importing it. A simulated concurrent uniqueness conflict raises **NameError**, defeating its per-item error handling.
- **Registration race:** `auth.register()` calls `database.flush()` before its `try/except IntegrityError`. Concurrent email registration can produce an unhandled 500 rather than duplicate-email 400.
- **Enrollment race:** the shared enrollment service flushes before the normal router's protective try; bulk catches `HTTPException`, not database uniqueness errors. Concurrent inserts can defeat the intended duplicate response.
- **Inactive course:** the normal enrollment route rejects it, but admin/bulk call a shared service without this guard. Admin enrollment into a soft-deleted course returned **201**. The admin specification bypasses ownership, not all domain invariants.
- **Session deletion after admin override:** active session with check-ins → admin changes to scheduled → owner deletes. The delete route attempts to remove a referenced row and raises **IntegrityError**. The admin status route is required for edge-case setup; add a record-existence guard and a controlled error rather than prohibiting the required endpoint.
- **Errors:** the app only has a request-validation handler. Unhandled DB/service errors become generic plain HTTP 500 responses, not the API document's JSON `{detail: ...}` form. There is no request-ID correlation. The PDFs' additional `code` field is an example, not mandatory over the API's `detail` contract.
- Partial time updates correctly validate retained fields, but changing `scheduled_start` does not recalculate inherited check-in windows. That behavior needs an explicit contract/test; automatically changing an intentionally customized window would also be wrong.

**Fix:** catch constraint errors at the operation that flushes, preserve transaction/savepoint semantics, add safe JSON 500 handling and sanitized server-side correlation logs, and consolidate domain invariants in services. Avoid mislabeling every IntegrityError as a duplicate when it could be an FK/check violation.

### F10 — High: audit immutability and user deletion are incomplete

Audit routes are read-only and the model has no `updated_at`, which satisfies part of the append-only pattern. It does not make records immutable. No migration creates an UPDATE/DELETE prevention trigger or separate restricted runtime grants; actual PostgreSQL inspection found **no audit triggers**, and the configured `saiv` role is a **superuser**. Module 4's documented read-only database access also uses the same superuser connection string in Compose; a read-only client convention is not a database permission.

Check-in cleanup and scheduled-user anonymization exist and are tested. No supported operation schedules a deletion, so ordinary requests/deactivations cannot start the documented 30-day PII-removal lifecycle. Anonymization preserves user IDs and relationship rows; active enrollments/course assignments remain, which can distort statistics unless explicitly accounted for. The worker runs inside every application process, has no cleanup-health state, and startup continues after cleanup failure. Logging exists in `run_retention_once()`, so failures are not wholly silent, but readiness does not expose them.

**Fix:** separate migration/runtime/dashboard DB roles, enforce append-only audit permissions, and test rejected mutation attempts using the runtime role. Add a consent-aware deletion request/scheduling mechanism, safe due-date handling, account deactivation, device cleanup and anonymization tests on PostgreSQL. Document whether anonymization is the approved equivalent of hard deletion. Retain audit logs indefinitely as required; reconcile retained log email/IP details with the deletion policy rather than deleting logs indiscriminately. Add cleanup status, retry/backlog observability and single-job coordination.

### F11 — High: audit-event completeness and identity gaps

- New device registration writes audit IDs **before flush assigns `device.id`**. The initial event had `resource_id=null` and `device_id=null` in the probe.
- `checkin_attempted` lacks the location and device required by Security Required Events; it references the session before the check-in exists. Record enough minimized information to trace the attempt without storing image payloads.
- Repeated attempts on already-blocked accounts return before `login_failed` is logged. Rate-limit/auth-denial/missing-session failures do not produce `security_violation`/complete attempt events.
- Manual reviews log `checkin_reviewed`, as the API action list specifies, but Security's higher-priority required-event table also expects approved/rejected events for manual outcomes. Add the outcome event or an explicitly approved equivalent.
- Profile/admin enrollment actions use inconsistent labels (`profile_updated` versus documented `user_updated`; `student_enrolled` versus `enrollment_added`). They work but can break consumers filtering documented event names.
- Raw image bodies are not currently written to backend audit storage. Preserve that property when adding request/error logs. The login requirement explicitly logs failed-email information; do not casually add more PII to other events.

**Fix:** define a typed event taxonomy, flush IDs before logging, separate attempts/outcomes/denials, and validate events with database assertions. Include request correlation and reviewer/device identifiers where required.

### F12 — Medium/High: differences from recommended schema and undocumented behavior

The model and migrations are internally consistent on a fresh isolated database, but diverge from [recommended schema][DOC-DB]:

| Entity | Missing/different design |
|---|---|
| Course | No `description`, `require_face_recognition`, or `require_device_binding`. Requests carrying these extra fields are ignored by default Pydantic behavior. Nullable `instructor_id` is allowed and is not a defect. |
| Enrollment | No `dropped_at`; removal hard-deletes the relationship rather than retaining drop history. |
| Session | No descriptions, actual start/end, `updated_at`, QR secret/expiry or real QR enablement; owner FK non-null and venue/settings eagerly copied instead of nullable overrides. Eager copying is workable if documented. |
| Device | Fingerprint is VARCHAR(255) unique **per user**, instead of recommended VARCHAR(64) globally unique; key optional; no key lifecycle/attestation/revocation metadata. Platform/key metadata are simplified. Per-user uniqueness needs an explicit explanation because it permits a shared fingerprint across accounts. |
| Check-in | No liveness challenge type, face hash or QR verification field; device ID is persisted but omitted from `CheckinResponse`; precise coordinates stored without the Briefing p.28 minimization step. |
| Risk signal | No `risk_signals` table/model/migration; generic factors stored as JSON text on check-in. This can be a deliberate alternative, but currently lacks documented equivalence and the recommended signal vocabulary/details. |
| Audit/indexes | Missing recommended audit IP index, session-window composite index, and some reverse-FK indexes; model/migration tests do not establish query-plan sufficiency. |

`qr_code` is accepted on check-in and ignored; `qr_code_enabled` always returns false. There is no enabled QR workflow, so optional QR is not a core blocker, but silently accepting the field misrepresents behavior. Return a documented unsupported error or implement it before advertising it.

These are **recommended-design differences**, not an instruction to add every optional field during recess week. Prioritize fields required by the approved integration/security contract. Schema evolution needs new migrations, not edits to already applied migration files. Migration `0005` downgrade is not tested with actual `appealed` rows; reverting to the old status constraint can fail unless data is handled explicitly.

### F13 — High: configuration, deployment, monitoring and documentation

Positives: database pooling is configured at 10+20, connections are pre-pinged, credentials use settings, `.env` is excluded from the backend image, and Docker runs migrations before Uvicorn. Exact development CORS origins and token-unit aliases are implemented.

Remaining issues:

- Compose embeds a predictable JWT signing key and database password; key-length validation alone accepts the placeholder. Use a generated environment-provided signing key. Keep course-compatible role registration isolated to its authorized environment.
- PostgreSQL/Redis bind host ports broadly; Redis has no authentication in the supplied setup. Limit exposure for shared integration and use separate restricted DB credentials.
- **Resolved in the verification/scoring repair:** `RISK_SCORE_THRESHOLD` now controls new course/ORM defaults, with explicit session/course values taking precedence. Original finding: `RISK_SCORE_THRESHOLD` is parsed but never used to set course/session defaults; schemas/models hardcode 0.5. The documented environment option therefore does not affect the default risk policy.
- `.env.example` omits face-service timeout/URL and retention controls. CORS settings allow any supplied origin string, including `*`, despite the documented exact-origin policy.
- No backend Docker `HEALTHCHECK`/Compose health check, application restart policy, readiness/schema check, backup/recovery guide, migration reconciliation guide or automated CI configuration was found.
- No `/metrics` or OpenTelemetry instrumentation. The direct integration configuration [Prometheus scrape target][PROMETHEUS] expects `backend:8000/metrics`, and Compose supplies `OTEL_EXPORTER_OTLP_ENDPOINT`, which the backend ignores.
- Backend README is materially stale: lists implemented devices/reviews/face integration/statistics/exports as deferred; claims bcrypt 12 while default is 10; describes closed sessions as terminal; omits migration `0005` and current surface. Historical 81/120/122-pass observations are not current completion evidence.
- `.gitignore` ignores `docs/*` except the grading clarification. Existing authoritative docs are tracked, so they are not missing, but new internal documentation can be accidentally excluded.
- Dependency pins are old. In particular, `python-jose==3.3.0` precedes the maintainer's fixes for CVE-2024-33663 and CVE-2024-33664 in [release 3.4.0](https://github.com/mpdavis/python-jose/releases/tag/3.4.0). This identifies dependency debt, **not proof those attacks are reachable here**: this backend restricts JWT verification to HS256 with a shared secret and does not use JWE. Perform a complete dependency scan and a tested upgrade.
- The local test environment has bcrypt **4.1.2**, despite the file pin of **4.0.1**, producing the trapped Passlib version warning. Therefore 132 passing local tests are not proof of an exactly reproducible pinned Docker build.

### F14 — High for dashboard correctness: analytics and export semantics

Statistics use joined/aggregate queries rather than obvious per-check-in N+1 loading, and zero-denominator handling is implemented. Nevertheless:

- Course statistics ignores the documented default end date of **today**, including future/cancelled sessions in denominators when dates are omitted. Enrollment denominators use the **current** roster rather than enrollment-at-session history. The lack of drop history makes historical attendance unstable.
- Session JSON export calculates `attendance_rate = approved / number_of_checkin_records`. If 10 students are enrolled and one approved record exists, it reports 100%; session statistics uses checked-in/enrolled, so the outputs disagree.
- Do not label all inclusion of rejected records an automatic specification violation: the API's session-statistics example explicitly gives 45 checked-ins, including one rejected, divided by 50 enrolled. It is an attempt-based session metric. Gradebook accepted-attendance semantics still need a distinct, documented definition.
- Daily overview groups check-ins by check-in date and enrollment slots by session date; sessions near midnight can misalign numerator/denominator. UTC is the implemented day boundary, whereas the project operates in Singapore; the desired reporting timezone is not specified.
- Course/session rates can exceed 1 after roster reduction because historical check-ins remain while denominator shrinks. Empty days are omitted from trends. These behaviors need documented policy/tests rather than hidden assumptions.

**Fix:** define metrics clearly, apply documented default date bounds, distinguish attendance attempts from accepted attendance, use stable denominators, and test enrollment changes, cancellations, midnight boundaries and zero data. Add public-test aliases only as explicit compatibility support; the existing written stats schemas remain authoritative.

### F15 — Medium/cleanup: remaining debt and limits

- Refresh tokens remain reusable until expiry; “rotate” currently means issue another token, not consume the previous token. Tokens lack `jti`/session identity, and equivalent claims issued in the same second can produce identical strings. True rotation/revocation is hardening beyond the stated basic refresh requirement.
- No logout API exists, despite `logout` being listed as an audit action. The API does not specify a logout route, so this is a design gap to resolve rather than an invented required endpoint.
- `Pagination` and `ExportSummary` appear unused; wildcard schema exports pull in incidental imported names. Remove genuinely unused helpers/imports and prefer deliberate schema exports.
- `JSONText` returns raw strings on malformed JSON, which can later violate a typed `risk_factors` response. Add controlled compatibility/validation instead of letting response serialization fail.
- Endpoint-specific arrays are intentionally documented, but course/session paginated limits allow 200 where the generic pagination section says max 100. Audit's explicit max 1000 is a valid documented exception. Standardize actual max values and tie-break ordering.
- Unbounded roster/session check-in reads and exports materialize all records in memory; the CSV `StreamingResponse` wraps an already-built buffer. Add limits/paging/true streaming where actual integration volumes justify it.
- Geolocation precision minimization from Briefing p.28 is absent. Calculate distance from full precision, then document and apply suitable persisted precision if required; do not alter boundary validation with premature rounding.
- Optional QR issuance, platform attestation, sophisticated anomaly models and extra test-only admin summary routes may be deferred if explicitly recorded as optional and no client relies on them.

# 4. Testing Audit

### Existing coverage

The 132 native cases include parameterized tests in `test_security.py`, `test_schemas.py`, `test_main.py`, `test_rate_limit.py`, `test_geolocation.py`, `test_database.py`, `test_migrations.py`, `test_week3.py`, `test_compliance.py`, and `test_compliance_routes.py`.

They meaningfully cover password/JWT helpers, malformed/expired token types, configured CORS preflights, rate-limit values via lightweight Redis doubles, GPS geometry/local-IP/country-lookup behavior, course/session/enrollment ownership, consent, schedule/window boundaries, uniqueness constraints, login lockout/reset, optional course assignments, appeal/review happy paths, exports/statistics happy paths, and migration upgrade/downgrade/backfill on SQLite. PostgreSQL SQL generation is tested. `test_week3.py` uses real JWTs and SQLite foreign keys; the newer compliance fixture overrides the authentication dependency and does not enable SQLite FK enforcement.

Limitations matter:

- Only connectivity is checked against the actual PostgreSQL database; migrations, triggers and ordinary ORM reads are not checked there.
- PostgreSQL row locks/concurrent writes are not exercised by SQLite.
- Redis production Lua atomicity is not proved by the test doubles. The isolated public run did exercise real Lua for normal traffic, not saturation or outage recovery.
- An OpenAPI-path existence assertion does not validate behavior.
- Week 3 tests expect null liveness/legacy scores, preserving the current unsafe fallback.
- The retention test manually seeds a deletion deadline; it does not prove a user can request deletion.
- The public privacy suite passes, but its tests do not prove real cleanup, audit immutability, or encryption. Public security passing also does not prove device signatures/replay protection.

### Executed public results and requirement conflicts

| Public file | Observed score | Interpretation |
|---|---:|---|
| `test_api_functional.py` | 20/28 | Three check-in/history failures: absent consent setup, missing required accuracy, resulting empty history. |
| `test_security_basic.py` | 12/12 | Basic security cases pass; not certification of complete security policy. |
| `test_privacy_basic.py` | 8/8 | Basic response/consent checks pass; retention/immutability assurance is inadequate. |
| `test_frontend_dashboard.py` | 7/8 | One check-in request fails without consent setup. |
| `test_observability.py` | 5/12 | Payload names/shapes and fixture ownership differ; additional unscored summary/device-list tests fail. |
| `test_integration.py` | 2/4 | Login latency/concurrent login pass; end-to-end flow omits required accuracy and fails 422. |
| **Selected total** | **54/72** | **74 executed tests: 60 pass, 14 fail.** No full-suite/module grade is claimed. |

The 14 failing tests include unscored tests, hence failure counts and point counts differ. The grading clarification's historical 92-point full-suite total is not the denominator for this selected run. No face-recognition test category was run.

Specific conflicts to resolve without weakening the backend:

- Successful check-in tests must explicitly set consent. Required consent is supported by Security and the PDFs; bypassing it to pass fixtures is not a correct fix.
- Duplicate and end-to-end tests omit `location_accuracy_meters`, which the API request schema includes as a required field. Ask the course authority to resolve fixture drift or publish an explicit safe compatibility policy.
- Stats tests expect `today_checkins`/`flagged_pending`, `checked_in_count`/`approved_count`, and other fields, while the API defines `total_checkins_today`, `flagged_pending_review`, `checked_in`, and `by_status`. Additive aliases may be harmless, but they must be deliberate.
- The flagged queue test expects `{items,total}` while API `/checkins/flagged` says an array. Retain the authoritative contract unless revised or version an alternate endpoint.
- Session JSON export tests expect top-level `session_id`, `records`, and `summary.total_enrolled`; API text leaves the exact session export object unspecified. The current payload can be extended while fixing attendance semantics.
- `/audit/summary` and `GET /devices/` are expected only by extra public tests, not by the current API specification. Treat them as test-compatibility work, not core missing routes.
- Some course roster/statistics tests create an unassigned course and use an instructor who has not established a teaching relationship. Keep ownership checks; correct setup or obtain a clear ownership rule.

### Tests required before integration

| Test group | Required scenarios / pass condition |
|---|---|
| Real PostgreSQL setup | Empty DB upgrades to head; current DB follows reviewed reconciliation; ORM reads work; schema comparison clean; retention/status/FK constraints valid. |
| Required biometric checks | Missing image, empty object, missing boolean/score, invalid hash/score, inconsistent threshold claims, timeout/4xx/5xx/non-JSON; no required-verification failure may approve. |
| Risk decision matrix | Threshold 0/0.5/1 and exact cutoff; all five weights; unknown/trusted device; poor accuracy; missing signals; explicit false face/liveness; >2× geofence; no hidden fallback. |
| Concurrent finalization | Session close/cancel, course deactivation, enrollment removal, user deactivation/role/consent change, biometric-policy change, duplicate concurrent submission and competing device updates. Test on PostgreSQL. |
| Complete authorization matrix | Student/TA/instructor/admin across own/unrelated/shared/unassigned courses; all list/detail/review/export/stats routes; denied attempts cannot mutate state. |
| Device lifecycle and replay | Invalid key; proof mismatch; wrong account/session; expired/reused nonce; admin revocation; owner re-registration; key replacement resets trust; active trusted device always has usable key. |
| Registration/enrollment/bulk races | Same email or same student/course inserted simultaneously; controlled duplicates; no NameError/500; savepoints preserve successful bulk items. |
| Review/appeal | Seven-day exact boundary, repeated appeal, invalid state, other owner/course, simultaneous reviews, metadata/outcome events. |
| Audit/privacy | Runtime UPDATE/DELETE denied; events complete and correlated; no image/password payload in DB/logs; deletion scheduling → +30-day anonymization; consent withdrawal; cleanup failure visible. |
| Statistics/export | Current vs historical enrollment, default end date, cancellations/future sessions, gradebook denominator, UTC/Singapore boundaries, empty/zero data, CSV formula prefixes. |
| Redis/IP/provider | Real Redis 10/min and 1000/hour, TTL/concurrent Lua behavior, outage/recovery; local IP no provider call; first forwarded address; public SG/non-SG; provider timeout/cache expiry. |
| HTTP/browser contract | Canonical request/response shapes, safe JSON 500 errors, exposed response headers, allowed/denied CORS origin, actual frontend authentication URLs. |
| Performance | Warm/cold lookup latency, required face verification, concurrent same-session check-ins, 10-user baseline and larger stress target, DB pool exhaustion and bounded exports. |
| Reproducible deployment | Pinned Docker build, startup with schema checks, restart/retention recovery, migration failure surfaced, backend metrics scrape and trace propagation. |

# 5. Integration Readiness

### Frontend integration — authentication usable; check-in integration blocked

Backend auth/profile contracts and development CORS are implemented. There is a concrete URL mismatch at the interface: [frontend API base configuration][FRONT-API] and Compose use `http://localhost:8000`, while login/register call `/auth/login` and `/auth/register`, and refresh calls `${BASE_URL}/auth/refresh`. Backend routes are under `/api/v1`. Agree on `http://localhost:8000/api/v1` as the client base, or have callers include the prefix. This observation is limited to interface compatibility; it is not a frontend implementation audit.

Before connecting check-in screens, freeze required accuracy/consent fields, device-proof format, image encoding, verification flags, status/error semantics and retry rules. Arrays versus paginated objects must be deliberate. Missing required verification must never be handled as success. Browser response headers need exposing. Resolve F00/F01/F02/F04/F05 and the URL mismatch first.

### Face-recognition integration — wrappers exist; safe contract validation blocked

The three required/optional upstream paths and payload field names match the source API. Backend privacy persistence is appropriate. Blockers are permissive response models, required-evidence omission, stale state after awaits, undefined risk-service ownership, and absence of a real-service end-to-end test. Confirm successful enrollment hash retrieval and same/different-person verification through backend with approved fixtures. Test unavailable/invalid service behavior before connecting real students.

Do not make completion depend on implementing a bonus liveness algorithm in Module 3. Backend must either disable the optional capability explicitly or enforce the selected enabled policy correctly.

### Dashboard integration — substantial API support; contracts and data correctness blocked

Session management, roster/check-in reads, review/appeals, four stats routes, audit query and exports exist. Blockers are F00, the unassigned-course student relationship bug, unresolved analytics/export semantics, event incompleteness, and any payload differences the dashboard actually relies on. Metrics scraping cannot work against the current backend because `/metrics` is missing. If direct DB reads are used, provide a read-only role and reconcile the schema before granting access; do not share the superuser credential as the read-only interface.

### Database/environment dependencies

- PostgreSQL schema/history must be reconciled; connectivity alone is insufficient.
- Redis must be available; rate limiting intentionally fails with 503 when it is unavailable.
- Backend needs a generated `SECRET_KEY`, correct PostgreSQL/Redis URLs, face-service URL, exact CORS origins and a published retention policy.
- Public-IP country checks need provider availability/outbound connectivity or a tested compliant local alternative/cache policy.
- Face-required check-ins depend on successful upstream verification. Schema-aware readiness and face capability reporting must make failures understandable.
- TA assignments and staff/course relationships need reproducible seed/setup steps.

### Exact blockers to clear first

1. Recover/reconcile unknown database revision and missing model columns; prove clean PostgreSQL startup.
2. Consolidate risk decisions; stop approving omitted/malformed required evidence.
3. Reload and revalidate final eligibility/policy under concurrency.
4. Repair trust/key/revocation handling and provide real device proof if security binding is claimed.
5. Correct instructor/student relationship handling for unassigned courses; freeze authorization scopes.
6. Align consumer URL prefixes, canonical payloads and browser-accessible headers.
7. Fix registration/bulk/enrollment constraint-error paths and deletion-with-check-ins handling.
8. Prove complete PostgreSQL/Redis/backend/face-service workflow with successful and rejected outcomes and recoverable dependency failures.

The current backend can support controlled contract development against a disposable correctly migrated environment, but should not be declared a completed integration baseline.

# 6. Prioritised Completion Plan

### Critical — must be completed before integration

| Order | Work | Acceptance criterion |
|---|---|---|
| 1 | F00 database reconciliation and reproducible schema | Backup preserved; migration history resolvable; empty and existing test DB upgrades pass; current ORM queries work; schema-aware readiness catches drift. |
| 2 | F01/F02 one risk pipeline and strict verification | No legacy bypass; required missing/malformed/failed face/liveness evidence cannot approve; risk threshold and accuracy/device signals behave consistently. |
| 3 | F04 final eligibility transaction | Real PostgreSQL race tests reject changes occurring during verification; no stale object decisions or duplicate rows. |
| 4 | F05 trust/revocation correctness and binding interface | Changed/removed keys invalidate trust; admin revocation cannot be undone by ordinary registration; agreed signed challenge resists replay. |
| 5 | F03 access consistency and interface freeze | Unassigned/shared courses work; unrelated resource access denied under documented policy; frontend URL/payload and dashboard shapes agreed. |
| 6 | F09 predictable failures | No NameError/uncaught uniqueness/FK errors in tested races; JSON error responses; rejected failures do not leave partial state. |
| 7 | Integrated acceptance run | Backend + PostgreSQL + Redis + real face contract tested; both approved and rejected flows, review and exports work. |

### High priority — complete during recess week

- F10/F11: database-backed audit immutability, complete events, deletion scheduling, and observable retention.
- F06/F07: genuine device/network risk inputs, replay and impossible-travel baseline, provider outage handling and asynchronous/bounded I/O.
- F08/F14: safe CSV, browser exposed headers, correct export denominator/default date bounds, documented accepted-attendance metrics.
- F13: usable secret/environment configuration, tested dependency updates, health/readiness, backend metrics and tracing, a reproducible pinned Docker run.
- Resolve public-test conflicts against written requirements. Add compatible fields/extensions where safe; document unresolved conflicting fixtures for the course authority. Preserve consent/ownership/security rules.
- Expand meaningful negative/concurrency tests rather than adding path-existence assertions.

### Medium priority — important but not automatically integration-blocking

- Implement documented `create_accounts=true` securely; it is required for full contract completion even if the team does not use it for initial integration.
- Complete or explicitly approve equivalents for recommended `risk_signals`, course security settings and historical enrollment data.
- Define cross-course student-statistics visibility and reporting timezone; make historical denominator behavior stable.
- Add real refresh-token rotation/revocation if required by the final security policy; fix misleading rotation claims now.
- Add a TA-management endpoint only if needed; otherwise provide validated repeatable seeding.
- Test migration downgrade with populated edge states and dependency recovery.

### Low priority / cleanup — can be deferred with an explicit record

- Remove unused schemas/imports and wildcard exports; update Week 2/3 module comments and stale README history.
- Optional QR flow, platform-specific attestation, advanced anomaly models, and unneeded test-only summary/list conveniences.
- Optimize unbounded queries/exports beyond measured integration volumes.
- Improve optional descriptions/actual session timestamps/extra metadata once the frozen contract is satisfied.

### Practical recess-week sequence

**Days 1–2:** reconcile database and lock API/security contracts; repair risk/biometric validation and finalization races. **Days 3–4:** device proof/trust, consistent access, deterministic errors and real-service integration tests. **Days 5–6:** audit/retention, statistics/export semantics, metrics/configuration and real concurrency/performance checks. **Day 7:** pinned deployment rehearsal, backend-facing regression run, resolve documented fixture conflicts, and publish integration examples/checklist.

This is a dependency-based sequence, not a guaranteed effort estimate. Device binding and migration recovery can expand if prior migration history or team interface decisions are unavailable. Start with those immediately.

# 7. Final Backend Completion Checklist

### Database and deployment foundation

- [ ] Identify/recover revision `20260911_0007` and preserve a backup of existing PostgreSQL data.
- [ ] Reconcile existing schema with reviewed migrations; do not blindly stamp/reset/drop data.
- [ ] Upgrade an empty PostgreSQL database to head and verify ORM/schema consistency.
- [ ] Verify current check-in, device, review, appeal, retention columns/FKs/constraints/indexes.
- [ ] Add readiness that detects schema/migration incompatibility, independently of connectivity.
- [ ] Generate environment-provided JWT signing secret; publish complete environment examples.
- [ ] Separate migration/runtime/read-only dashboard roles and restrict infrastructure exposure.
- [ ] Rebuild and run the pinned backend Docker image; demonstrate safe migration-failure/startup/restart behavior.

### Authentication, access and workflows

- [ ] Preserve correct JWT TTL/type/signature checks, bcrypt ≥10 and four-role grading contract.
- [ ] Prove ten-failure lockout/reset with concurrent PostgreSQL attempts and required audit events.
- [ ] Handle simultaneous duplicate registration without 500.
- [ ] Fix missing `IntegrityError` import and prove bulk savepoint behavior.
- [ ] Use one teaching/TA relationship policy across users, rosters, checks, review, analytics and exports.
- [ ] Verify unassigned/shared-course instructors and assigned/unassigned TAs.
- [ ] Document/seed TA assignments and staff/course relationships reproducibly.
- [ ] Validate inactive courses consistently in ordinary/admin/bulk enrollment paths.
- [ ] Handle duplicate enrollment races and deliberate account creation/recovery for bulk creation.
- [ ] Handle admin-rescheduled sessions with existing attendance safely on deletion.
- [ ] Document and test schedule-update/window inheritance semantics.

### Check-in and security correctness

- [ ] Remove the hidden GPS-only scoring bypass or replace it with an approved explicit policy.
- [ ] Enforce configured risk threshold, accuracy and all agreed signal weights consistently.
- [ ] Reject missing/invalid required face evidence; test failed verification and non-JSON/malformed service responses.
- [ ] Make liveness disabled/enabled behavior explicit; enabled required evidence cannot be omitted.
- [ ] Validate enrolled hashes and upstream result scores/pass criteria; retain hash-only persistence.
- [ ] Reload locked user/session/course/enrollment/policy state after asynchronous work.
- [ ] Prove closure/deactivation/removal/consent/role/policy races cannot produce an invalid approval.
- [ ] Prove simultaneous student/session submissions cannot create duplicates.
- [ ] Enforce Singapore GPS/IP rules, first forwarded address and private/local allowance.
- [ ] Test provider timeout/cache/Redis failure and boundary cases without accidental approval.
- [ ] Validate public keys, reset trust on key changes and preserve administrative revocation.
- [ ] Implement agreed signed, expiring one-time check-in proof; reject wrong/reused/expired proofs.
- [ ] Record real network/device evidence and baseline replay/impossible-travel handling.

### Privacy, audit and observability

- [ ] Confirm no raw images/embeddings/password bodies enter database, audit events or application logs.
- [ ] Add a supported deletion-request/scheduling workflow and verify +30-day cleanup/anonymization.
- [ ] Make retention failures/backlog/last success observable; test real PostgreSQL FKs and restart catch-up.
- [ ] Enforce audit append-only permissions and prove runtime UPDATE/DELETE cannot succeed.
- [ ] Flush resource IDs before auditing; log required attempt/decision/review/denial/export events consistently.
- [ ] Add safe JSON server errors and sanitized request-ID-correlated logs.
- [ ] Expose backend metrics and trace propagation expected by the integration setup.
- [ ] Document retained audit PII and location precision policy without deleting required indefinite audit history.

### Dashboard/frontend integration and release evidence

- [ ] Agree `/api/v1` base URL; validate login/register/refresh calls through the actual client interface.
- [ ] Freeze canonical payloads, required consent/accuracy/device/image fields, error/status meanings and pagination.
- [ ] Expose `Retry-After` and `Content-Disposition`; verify real browser CORS handling.
- [ ] Fix session export attendance denominator and distinguish attempt rate from accepted gradebook attendance.
- [ ] Apply documented analytics date defaults and test changing rosters/cancelled/future sessions/timezone boundaries.
- [ ] Neutralize CSV formula-leading text fields before gradebook downloads.
- [ ] Verify appeal/review ownership, boundaries, competing updates and resulting metadata/events.
- [ ] Run existing backend regression suite and new meaningful security/concurrency tests.
- [ ] Run backend-facing public tests; record resolved/unresolved written-spec conflicts and actual selected points.
- [ ] Run real backend/PostgreSQL/Redis/face-service successful/rejected end-to-end flows plus dependency failures.
- [ ] Measure warm/cold request latency and concurrent same-session check-ins on the deployment stack.
- [ ] Update backend README/contract examples to current behavior, migration head, environment variables and optional features.
- [ ] Publish a reproducible backend setup, seed, migration, integration and recovery procedure with passing evidence.

**Reasonable completion gate:** all critical fixes and high-priority security/privacy/operational checks pass on the actual PostgreSQL/Redis deployment, core face matching is verified through the backend, canonical client contracts are agreed, and any deferred optional work is explicitly documented. Fifty exposed API operations and 132 passing native tests alone do not meet this gate.

[DOC-GRADE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/GRADING-CLARIFICATIONS.md:7
[DOC-SEC]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/SECURITY-REQUIREMENTS.md
[DOC-API]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/API-SPECIFICATION.md
[DOC-DB]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/recommended_design/DATABASE-SCHEMA.md
[DOC-INTEGRATION]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/recommended_design/INTEGRATION-GUIDE.md
[DOC-BACKEND-INTEGRATION]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/API-SPECIFICATION.md:1905
[AUTH]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/auth.py:28
[AUTH-SCHEMA]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/schemas/auth.py:12
[ATT-SCHEMA]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/schemas/attendance.py:11
[SECURITY]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/security.py:16
[DEPENDENCIES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/dependencies.py:18
[USERS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/users.py:27
[COURSES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/courses.py:35
[ENROLL]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/enrollments.py:55
[ENROLL-SERVICE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/enrollments.py:10
[SESSIONS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/sessions.py:17
[CHECKINS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/checkins.py:72
[FACE]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/face_service.py:10
[RISK]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/risk.py:13
[ACCESS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/access.py:20
[RELATIONSHIP]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/access.py:75
[DEVICES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/devices.py:19
[STATS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/stats.py:25
[EXPORT]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/export.py:31
[AUDIT]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/audit.py:18
[RETENTION]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/retention.py:19
[ADMIN]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/admin.py:73
[MODELS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/models.py
[MAIN]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/main.py:22
[HEALTH]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/main.py:74
[GEO]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/utils/geolocation.py:50
[DOCKER]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/Dockerfile
[PROMETHEUS]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module4-observability/prometheus.yml:6
[FRONT-API]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module1-frontend/lib/api.ts:7
[E-PUBLIC]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit/public-http-output.txt
[E-XML]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit/public-http-results.xml
[E-PROBES]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit/probe-results.json
[E-DB]: C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/tmp/backend-audit/database-inspection.txt

