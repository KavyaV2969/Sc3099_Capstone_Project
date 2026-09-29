# Backend completion register

Implementation baseline: 29 September 2026; current working tree includes the
earlier database/verification repairs. No existing integration data is reset.
Authority remains Grading > Security > API > recommended design > PDFs.

Every outstanding audit requirement is mapped below before implementation.
All required backend implementation rows are now complete. The deployment row's
real biometric integration gate is deferred by the user because no functioning
external dependency is available. Detailed evidence is in the [final report](../output/backend-completion-2026-09-29.md).

| Outstanding requirement | Finding | Implementation | Required regression evidence | State |
|---|---|---|---|---|
| Registration conflicts | R04 | Protect flush/commit | duplicate race and rollback | Complete |
| Profile/student permissions | R01 | Shared taught-course scope | session-only and unrelated course | Complete |
| Session lifecycle | R04 | Guard used-session deletion | admin reset with attendance | Complete |
| Enrollment/rosters | R04/R05 | Shared eligibility and savepoints | races/inactive course | Complete |
| Bulk enrollment/accounts | R05 | Single-use activation | creation/expiry/replay/partial success | Complete |
| Admin setup | R04 | Exception import/conflict handling | bulk conflict and enrollment | Complete |
| Device binding/replay | R02 | Signed Redis challenge | expiry/replay/substitution/concurrency | Complete |
| Device lifecycle/trust | R02 | Parsed keys, trust reset, revocation | replacement/revocation/legacy | Complete |
| Fraud signals | R09 | Network hint and impossible travel | private-IP exception/travel boundaries | Complete |
| Lists/review/appeal | R01/R06 | Scope and outcome audits | permissions/review race/audit | Complete |
| Statistics | R07 | Approved/retained/snapshotted rates | roster/date/retention/scopes | Complete |
| Exports | R07 | Same rates, safe CSV, bounded stream | formulas/coverage/browser headers | Complete |
| Audit immutability | R06 | PostgreSQL triggers/restricted roles | update/delete/truncate refused | Complete |
| Audit completeness | R06 | Required redacted correlated events | outcomes/denials/no secrets | Complete |
| Deletion lifecycle | R08 | Scheduling/consent/hash cleanup | immediate disable/30-day cleanup | Complete |
| Location precision | R08 | Full precision assessment, rounded storage | geofence/storage/audit | Complete |
| Input/resource validation | R10 | Body/image/response bounds and extras | chunked/oversized/malformed/QR | Complete |
| Schema/migrations | R11 | Forward migration/frozen object contract | fresh/upgrade/recovery/drift | Complete |
| QR | R10/R11 | Explicit unsupported input | nonblank rejected, disabled output | Complete |
| CORS/browser | R12 | Exact origins/exposed headers/build base | wildcard refusal/preflight/header | Complete |
| Errors/correlation | R04/R10 | Safe JSON and request ID | no SQL/image/token leakage | Complete |
| Metrics | R13 | Prometheus integration names | scrape/counts/bounded labels | Complete |
| Deployment/release | R03/R12/R13 | Private config/roles/image/rehearsal | healthy image, migrations/recovery, restricted roles, 10/100-user HTTP | Backend complete; real face gate deferred by user |

## Agreed defaults

Instructors see taught courses only. Activation expires in 24 hours, device
challenges in 120 seconds. Unsigned attendance remains supported with unknown
device risk. Approved attendance uses a retained historical roster. Detail is
limited to 30 days; unknown history is never silently classified as absence.
Impossible travel flags (not rejects) after >=1 km displacement and >100 m/s
after subtracting both accuracy radii. GPS storage precision is four decimals.

## External gate and optional work

Real face-service interoperability requires an actual Module 3 implementation;
the checked-in operations return 501. The user has deferred this unavailable
dependency; mock tests cannot certify real integration readiness.
Optional QR issuance, standalone attestation, duplicate risk_signals storage,
extra recommended metadata, email delivery, refresh rotation/logout, paid network
reputation, and full OTLP tracing are intentionally deferred. Backend metrics and
request correlation are required. Existing verification flags are not weakened.

## Consumer requests and retry behavior

All API operations below use `/api/v1`. Mutation inputs reject unknown fields
with 422; `/docs` and `/openapi.json` enumerate their accepted fields. Responses
preserve existing arrays and envelopes. The accepted compatibility inputs are
optional course `instructor_id`, legacy token-duration configuration units, and
blank/null `qr_code`; a nonblank QR returns 422 and `qr_code_enabled` stays false.

### Activation

Authorized instructor/admin bulk enrollment accepts `create_accounts=true`.
Only newly created students receive `activation_url` and
`activation_expires_at` in the existing per-email details. The staff caller must
distribute these links privately; neither email delivery nor a default password
is provided. Links expire in 24 hours; storage contains only a SHA-256 digest.
Accounts remain inactive with an unusable random credential until activation.
Pending-account enrollment is permitted only in that creation transaction.
Later bulk attempts treat inactive accounts as ineligible (`not_found`), even
when they have an existing enrollment; repeated successful emails within the
original creating request report `already_enrolled`. The losing concurrent
creating request receives no activation link or credential.

```http
POST /api/v1/auth/activate
Content-Type: application/json

{"token":"TOKEN_FROM_PRIVATE_LINK","password":"YOUR_NEW_PASSWORD","full_name":"Student Name"}
```

`full_name` is optional. Password validation/hashing matches registration.
Success is 200 with the existing user representation and `Cache-Control:
no-store`; then use normal login. Invalid, expired or consumed tokens return 400
without changing the account. A row lock ensures only one concurrent activation
succeeds. Activation adds the now-eligible student to retained active rosters.
Expiry/replacement is an operator support concern; no automatic resend endpoint
or password-reset service is claimed.

### Device proof

Register a valid PEM SubjectPublicKeyInfo key with the existing device endpoint.
P-256 ECDSA/SHA-256 and RSA >=2048 bits/SHA-256 are supported. Key replacement
clears trust; administrative deactivation records revocation and owners cannot
reverse it. Legacy null keys remain null until replaced by their owners. Device
inventory alone never earns registered/trusted scoring.

1. Authenticate as the submitting student and POST the proposed unsigned
   `CheckinCreate` payload to `/devices/{device_id}/challenge`.
2. Receive `challenge_id`, `expires_in_seconds=120`, `algorithm`, and
   `signing_payload` (standard base64).
3. Base64-decode `signing_payload`; sign those exact bytes, not its base64 string.
4. Submit the identical check-in payload with paired `device_challenge_id` and
   standard-base64 `device_signature` to `/checkins/`.

```json
{"session_id":"SESSION_UUID","latitude":1.3483,"longitude":103.6831,
 "location_accuracy_meters":10,"device_fingerprint":"my-device"}
```

For ECDSA-P256-SHA256, signature bytes are IEEE P1363 `r || s` (32 bytes each,
64 total), as returned by browser WebCrypto ECDSA with SHA-256; DER signatures
are not accepted. RSA uses RSASSA-PKCS1-v1_5/SHA-256, not RSA-PSS.
Public-key PEM and base64 signature inputs are each bounded to 20,000 characters.
The UTF-8 signing document is server-generated canonical JSON, with sorted keys
and compact separators. It contains version, challenge UUID, random nonce,
user/device/session identities, SHA-256 of the canonical PEM key and SHA-256
of the normalized proposed payload. Payload hashing uses Pydantic JSON-mode
values, all defaults included, sorted compact JSON, excluding only the two
proof fields. Clients should sign the returned bytes rather than reproduce
normalization. Redis stores only this document with a 120-second TTL; images
and signatures are not stored in the challenge or audit.

Expired/replayed/substituted/foreign/invalid proofs return 403; unpaired fields
return 422. Recheck activity, revocation, ownership and key at finalization.
A valid proof is atomically consumed before persistence; if a later transaction
fails, obtain a new challenge. Redis unavailability returns 503. An unsigned
submission remains supported, with unknown-device risk (device contribution
0.20). A valid registered proof contributes 0.10; a valid trusted proof 0.00.
`device_trusted` in joined responses describes current device inventory;
retained `risk_factors` and outcome-audit contributions describe the submitted
scoring evidence, including the audit's `device_proof` boolean.

### Attendance and collection bounds

Attendance is approved unique eligible students / captured eligible roster.
Submission counts and pending/flagged/appealed/rejected counts remain distinct.
Rejected-only attendance is zero. Snapshot eligibility when a session first
activates; append newly eligible students while active. Withdrawal/account
changes do not rewrite history. Administrative resets preserve known snapshots;
used/legacy unknown rosters are not reconstructed from current enrollment.

Reporting detail covers retained 30 days, excludes cancelled sessions and
sessions whose window has not opened, uses scheduled session dates in
Asia/Singapore, and stores timestamps in UTC. End date defaults to today.
`coverage` discloses supported start/end, cutoff, retention clamping and
`denominator_available`. Unknown denominators produce null rates, never absence.
Course/current enrollment counts remain current-state data. Student historical
statistics remain accessible within taught courses after withdrawal while
retained roster/check-in evidence exists. Profiles still require the documented
current enrollment relationship. Unrelated courses remain inaccessible.

Reports are bounded to 1,000 sessions, 10,000 check-ins and 10,000 students;
student reports allow 100 courses. Narrow the range on 422. CSV exports stream
200-row database batches and at most 10,000 rows; strings beginning with
spreadsheet formula prefixes, including after leading whitespace, are prefixed
with an apostrophe. Course JSON exports remain arrays; session JSON keeps its
summary/checkins object and adds coverage. Export coverage also appears in
`X-Reporting-Available-From` and `X-Reporting-Retention-Limited` headers.
`X-Reporting-Coverage` contains the same complete JSON coverage object, including
denominator availability, for array-shaped course exports and CSV downloads.
Active sessions, own enrollments, course rosters and session check-ins accept
`limit` (default/max 100) and nonnegative `offset`; their collection shapes stay
unchanged. Existing envelope lists retain their documented bounds; consult
OpenAPI for their exact limits.
Device inventory also uses default/max 100 with offset. Own session/history and
flagged-review lists accept offsets while retaining their existing limit defaults.

### Privacy, auditing and failure boundaries

`DELETE /users/me` schedules anonymization 30 days later and returns
`scheduled_deletion_at`. It immediately disables the account, withdraws both
consents, clears the face hash and revokes devices. A repeated authorized
deletion request returns the same deadline; an already-issued token is allowed
only for this idempotent retry while deletion is pending. Ordinary endpoints
deny the inactive account. Camera-consent withdrawal independently clears face
enrollment. Cleanup removes expired activation credentials and identifying
roster snapshots along with existing attendance retention/anonymization.
Immutable security audit evidence (including pre-existing minimized login/IP
data) remains under the indefinite-retention exception. Account identity keys
remain for retained relationships; PII fields are anonymized when due.

Location is evaluated at full precision and stored/audited at four decimal
places (approximately 11 m latitude resolution). Required attempted/outcome
events include location, reviewer/reason where relevant, automatic critical
reasons, blocked logins, available device identity and security denials.
All events add schema_version=1 and request correlation; no images, bearer or
activation tokens, signatures or raw service responses are recorded.
PostgreSQL rejects audit UPDATE, DELETE and TRUNCATE, even from the table owner;
restricted application privileges are SELECT/INSERT only on audits. Operators
must not bypass/disable this trigger during ordinary cleanup.

Request bodies are limited to 16 MiB before JSON parsing (including chunked
bodies); decoded image payloads to 10 MiB. Face responses are streamed and
bounded to 64 KiB decompressed (128 KiB raw transport cap). Image decoding/pixel
limits belong to Module 3 and remain part of the external integration gate.
Bodies over the request limit return 413; schema/extra/image/QR violations 422.
Missing enabled-verification evidence remains 400. Unavailable/invalid face
evidence is 503 with no check-in; changed verification policy/reference hash
is 409 with no check-in. Valid biometric failure is retained rejected attendance
with HTTP 201: consumers must examine `status`. Duplicate attendance is 400.
Unexpected failures return sanitized JSON 500; database connectivity/pool
failures return 503. Rate limits return 429 and `Retry-After`; retry after that
delay. On 409 refresh policy and obtain a new proof; on 503 retry when the
dependency recovers. Refresh issues another token pair without revoking the old
refresh token; rotation/logout remains optional and is not claimed.

Synchronous DB/Redis/IP phases run in bounded worker threads; transactions are
released before biometric awaits and slow country lookup. Finalization locks
user, course, session, enrollment and device in that order. Bulk creating batches
use an advisory transaction lock to prevent opposite-email creation deadlocks;
existing user locks are sorted. Cleanup uses its own PostgreSQL advisory lock,
with matching user-before-session/device ordering, to prevent overlapping runs.
The VPN/proxy hint checks user-agent words only; it cannot establish actual VPN
use. Private/local IPs retain the grading exception. Impossible travel uses the
last retained approved location, >=1 km displacement and >100 m/s after both
accuracy radii; nonpositive elapsed time is suspicious. It flags review without
overriding critical rejection. The bundled Singapore map is a fixed snapshot,
not a live territorial dataset.

## Deployment, operators and observability

Copy the root `.env.example` to private ignored `.env`, generate fresh secrets
and set separate `MIGRATION_DATABASE_URL`, `BACKEND_DATABASE_URL` and optionally
`DASHBOARD_DATABASE_URL`. Example JWT placeholders are intentionally too short
to start the application. URLs inside Compose use `postgres:5432`; host tooling
can use `127.0.0.1:5434` (explicit IPv4 avoids Windows localhost connection
delays with IPv4-only published ports). Redis publishes `127.0.0.1:6380`.

The `backend-migrate` job owns migrations and idempotent role provisioning;
`backend` receives only its application URL. The operator owns schema/DDL.
The application has domain DML, audit SELECT/INSERT and version-table SELECT.
Optional dashboard access is read-only; credential/activation columns are
excluded from its users projection. These are service identities, not end-user
authorization; dashboard student/course views should use scoped backend APIs.
Provisioning refuses role membership or existing schema/table ownership that
could bypass restrictions. Changing `POSTGRES_PASSWORD` in an environment file
does not rotate existing PostgreSQL credentials: explicitly ALTER ROLE using a
private operator session, then update private URLs and recreate affected services.
For an existing Redis volume, set `REDIS_VOLUME_NAME` to preserve it before
recreation; do not reset the integration database or its data volumes.

```powershell
docker compose up -d --build postgres redis backend
```

Backend `/health` checks DB, exact frozen schema/ORM and Redis. It does not
certify face capabilities. Configure `FACE_SERVICE_URL` to a functioning
implementation. Enabled biometric policies remain enabled when it is missing.
The production image includes canonical/legacy migrations, contracts and
recovery tooling; run isolated backup/restore and the strict verifier before
deployment. Migration scripts `0007`/`0008` are forward-only additions; historical
recovery/provenance remain untouched. Backup dumps and private role URLs stay
ignored and must be handled as sensitive operator material.

Idempotent CourseTA provisioning (operator only, bind existing validated UUIDs;
no TA-management API was added):

```sql
INSERT INTO course_tas(course_id, ta_id)
SELECT :course_id, :ta_id
WHERE EXISTS(SELECT 1 FROM courses WHERE id=:course_id)
  AND EXISTS(SELECT 1 FROM users WHERE id=:ta_id AND role='ta' AND is_active)
ON CONFLICT(course_id, ta_id) DO NOTHING;
```

Remove an assignment with a parameterized DELETE using the same pair. API
authorization reads current assignments; removal takes effect immediately.
Session mutation still requires session ownership (or administrator); course
review/read rights through teaching do not grant mutation of another teacher's
session. Admin status overrides and setup routes remain supported.

For remote ingress, expose the backend only through a proxy which overwrites
forwarded headers. An HTTP example (TLS is not required by the project):

```nginx
location / {
    client_max_body_size 16m;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
    proxy_pass http://127.0.0.1:8000;
}
```

The grading-required first-forwarded-address behavior is preserved; direct
infrastructure/API bindings are loopback-only. Client GPS and user-agent inputs
remain claims, not trusted attestation. Set the exact browser API base including
`/api/v1` at frontend build time; no frontend screens were implemented.

`/metrics` exposes the integration guide's histogram/counters. Success means
approved at submission; manual reviews alter statistics, not the submission
counter. Additional metrics cover HTTP error status, stored outcome, bounded
dependency operation/category, retention success/failure/overlap and last-success
timestamp. Labels never contain users, submitted data or URLs with identifiers.
HTTP response `X-Request-ID` is server generated and propagated to redacted
logs and biometric calls, with validated W3C trace context. Exact allowed CORS
origins expose `Retry-After`, `Content-Disposition`, request and reporting headers.
OTLP export/full tracing is intentionally absent.

## Regression evidence mapping

`tests/test_completion.py` covers the newly added API/validation/privacy/reporting
contracts, including key replacement/revocation/proof substitutions, RSA and P-256,
activation expiry/replay, roster withdrawal/legacy uncertainty, travel boundaries,
Singapore midnight, CSV formulas, TA removal/shared-course ownership, slow IP/face
nonblocking behavior, body/upstream bounds and sanitized errors/correlation.
`tests/test_completion_postgresql.py` covers real concurrent registration,
enrollment, activation, opposite-order creating batches, activation/roster races,
review/appeal, tenth-attempt lockout, atomic Redis proof consumption, cleanup
advisory locking and restricted audit/read-only roles. Existing 54 PostgreSQL
cases cover migration/recovery/drift and final eligibility races; none are
replaced by mock evidence. Final counts and reproducible release/load results
are recorded in the linked completion report.

