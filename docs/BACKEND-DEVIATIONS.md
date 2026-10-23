# Module 2 Backend: Deviations and Interpretations

The school's documents in this folder (`API-SPECIFICATION.md`, `SECURITY-REQUIREMENTS.md`,
`recommended_design/`) are kept exactly as issued. The coordinator's later announcements are
recorded in [GRADING-CLARIFICATIONS.md](GRADING-CLARIFICATIONS.md). This file lists every
place where the backend interprets, extends or differs from those sources, the Briefing and
the Module 2 design PDF, and why.

Order of precedence used when sources conflict:

1. Coordinator clarifications ([GRADING-CLARIFICATIONS.md](GRADING-CLARIFICATIONS.md)).
2. Behavior asserted by the supplied public tests (`tests/public`), because they are graded.
3. `SECURITY-REQUIREMENTS.md`, then `API-SPECIFICATION.md`, then `recommended_design/`.

Every documented endpoint is implemented; nothing in the specification is missing.

---

## 1. Coordinator clarifications

| Clarification | Implementation | Interpretation |
|---|---|---|
| Lockout after 10 consecutive failed passwords; further attempts return 429 | Failures 1-10 return 401; the tenth blocks the account; every later attempt returns 429, including the correct password. A successful login before the tenth failure resets the counter. Admin activation (`PATCH /admin/users/{id}/activate`) unblocks. | "Further attempts" read literally: the tenth failure itself is still a 401. |
| Per-IP limits raised to 100,000/hour | Login and registration: 100,000/hour per client IP (Redis). API 1,000/hour per user and check-ins 10/minute per user are unchanged. | - |
| Singapore-only check-ins | GPS outside Singapore's land boundary (bundled geoBoundaries polygon) returns 403. A public client IP outside Singapore returns 403. Client IP is the first `X-Forwarded-For` address, else the socket address. Private, loopback and link-local addresses are allowed. | Public IPs are checked offline against APNIC's Singapore delegations (`app/data/singapore_ip_ranges.txt`). That is the registry country of first allocation, not live geolocation: an address registered elsewhere but used in Singapore (some cloud ranges) is rejected. |

The private-IP allowance takes precedence over the integration guide's sample code, which
treated private ranges as VPN indicators.

## 2. Where the public tests and the written specification disagree

| Topic | Specification | Public tests | Implemented |
|---|---|---|---|
| Course list | `GET /courses/` requires auth | `test_performance` calls it without a token | Course list is public metadata. Course detail and all course changes still require auth. |
| Flagged queue | `GET /checkins/flagged` returns an array | `test_observability` reads `items`/`total` | Paginated envelope `{items, total, limit, offset}`; items are full check-in records. |
| Consent before check-in | Briefing: camera and geolocation consent "must be TRUE before check-in" | Fixtures check in freshly registered students, whose consents default to false | Submitting coordinates counts as consent for that attempt only; the stored preference is unchanged. Camera consent is still required for face enrollment, face matching and liveness. |
| Liveness required by the session | Spec: liveness failure rejects | Fixture sessions require liveness but send no image and expect 201 (approved, flagged or pending) | No usable image (or no camera consent) skips the call, adds the full liveness risk (0.25, factor `liveness_missing`) and flags the check-in for review, so skipping the face check never auto-approves. A liveness check that runs and fails still rejects. |
| Device registration | Schema: `public_key` NOT NULL | Fixture registers without a key and adds a `browser` field | `public_key` is optional and validated when supplied; unknown fields are ignored. |
| Instructor read scope | Instructor reads are for taught courses / enrolled students | Observability tests query stats and rosters as an unrelated instructor | Any instructor can read any course's statistics, rosters, check-ins and exports, and any student's statistics. Writes (sessions, enrollments, reviews) still need ownership or a teaching relationship. |
| Response field names | Spec field names | Tests use other names | Both are returned: overview `today_checkins`, `flagged_pending`, `total_courses`, `total_students`; session `checked_in_count`, `approved_count`, `flagged_count`; course `average_attendance_rate`, `flagged_checkins`; student `total_enrolled_courses`, `total_sessions`, `attended_sessions`, `attendance_rate`, `recent_sessions`; session JSON export `session_id`, `records`. |
| Course creation | No `require_device_binding` field in the request | Fixture sends `require_device_binding: true` | Accepted and ignored; device assessment always applies. |

## 3. API behavior beyond the specification

### Check-in assessment

- **Scoring** is done in the backend with the Security Requirements weights (liveness 0.25,
  face 0.25, device 0.20, network 0.15, geolocation 0.15). The face service's `/risk/assess`
  is not called.
- **Status rules.** Liveness or face-match failure, or GPS beyond twice the geofence: `rejected`.
  Risk at or above 0.70 is always `rejected` (the "CRITICAL: auto-reject" band). Risk at or
  above the session threshold: `flagged`. Otherwise `approved`, except that these review
  reasons flag an otherwise approved check-in:
  - a liveness check required by the session that was not performed;
  - outside the geofence;
  - an unregistered device;
  - a device fingerprint registered to another account (proxy sign-in);
  - impossible travel (at least 1 km from the student's last non-rejected check-in at
    more than 100 m/s, after subtracting known GPS accuracy).
- **Devices.** An owned, active, registered fingerprint is a known device (device risk 0.5).
  Trusted (0.0) additionally requires a signed single-use challenge
  (`POST /devices/{id}/challenge`, P-256 or RSA key). An unregistered device is risk 1.0.
- **Unknown GPS accuracy** adds 0.25 geolocation risk. Stored coordinates are rounded to
  4 decimal places; the geofence uses full precision.
- **Network detection** is a user-agent keyword hint (`vpn`/`tunnel` → `vpn_detected`,
  `proxy` → `proxy_detected`, `tor` → `tor_detected`). It is a heuristic, not real VPN detection.
- **Risk factors** use the recommended schema's signal types where one fits
  (`liveness_failed`, `liveness_low_confidence`, `face_match_failed`,
  `face_match_low_confidence`, `device_unknown`, `vpn_detected`, `proxy_detected`,
  `tor_detected`, `geo_out_of_bounds`, `geo_accuracy_low`, `impossible_travel`). Four extra
  types cover cases the schema does not name: `liveness_missing`, `device_untrusted`
  (registered but not proven), `device_shared` and `geo_distance` (inside the geofence but
  away from the venue). Each factor's `weight` is its contribution to the risk score, as in
  the specification's example, so a check-in's weights add up to its `risk_score`. Factors
  also carry `category`, `severity`, `risk` and `critical`.
- **Face service failures.** When an image is supplied for a required check, an
  unreachable, invalid or inconsistent face-service response returns 503 and creates no
  check-in. The integration guide's sample instead continued without liveness. A
  verification change between the start and end of a request returns 409.
- **QR codes** are not supported: `qr_code` is accepted and ignored, and `qr_code_enabled`
  is always false.

### Requests, responses and errors

- Unknown request-body fields are ignored rather than rejected.
- Error bodies are `{"detail": ..., "code": ...}`, following the Module 2 PDF's format
  (for example `UNAUTHORIZED`, `NOT_FOUND`, `VALIDATION_ERROR`, `TOO_MANY_REQUESTS`).
  Validation errors list every invalid field with `loc`, `msg` and `type`.
- Request bodies over 16 MiB return 413; decoded images over 10 MiB return 422.
- Every response carries an `X-Request-ID` for log correlation.
- **XSS.** Names (user, course, session, venue, device; course codes and semesters) reject
  HTML markup with 422. Appeal reasons and review notes are stored HTML-escaped.

### Statistics and exports

- **Attendance rate** = approved, retained check-ins from a roster snapshot taken when the
  session first becomes active (later enrollments are added while it is active). Without a
  snapshot (session never activated, not yet open, cancelled, or legacy), the course's
  current eligible enrollment is the denominator. `coverage.denominator_source` reports
  which was used. Rates are always numbers.
- Reports cover the 30-day retention window and exclude cancelled and not-yet-open
  sessions. Report sizes are bounded (1,000 sessions, 10,000 check-ins).
- CSV cells that begin with a spreadsheet formula character are prefixed with `'`.

### Roles and accounts

- **TAs** read every course's session check-ins, flagged queue, check-in details, rosters
  and session statistics. Reviewing check-ins requires an assignment, which admins manage
  with `PUT`/`DELETE /admin/courses/{course_id}/tas/{ta_id}`.
- **Enrollment removal** is a soft delete (`is_active=false`, `dropped_at` set) and is
  idempotent. Re-enrolling reactivates the same row.
- **Bulk enrollment** with `create_accounts=true` creates inactive accounts and returns a
  one-time `activation_url`, valid for 24 hours, completed with `POST /auth/activate`. No
  default passwords are issued, and no email is sent.
- **Logout.** `POST /auth/logout` revokes the presented access token and, optionally, the
  caller's refresh token until they expire, and records a `logout` audit event. Refresh
  does not rotate or revoke the old refresh token.
- **Right to deletion.** `DELETE /users/me` immediately disables the account, withdraws
  consent, clears the face hash and revokes devices. Personal data is anonymized 30 days
  later. Withdrawing camera consent also clears face enrollment.

### Endpoints not in the specification

`POST /auth/activate`, `POST /auth/logout`, `DELETE /users/me`, `POST /devices/` (alias of
`/devices/register`), `GET /devices/` (admin inventory), `POST /devices/{device_id}/challenge`,
`GET /audit/summary`, `PUT`/`DELETE /admin/courses/{course_id}/tas/{ta_id}`,
`GET /health/schema` and `GET /metrics`. The backend's `/health` reports database and Redis
reachability only; `/health/schema` performs the full schema verification.

## 4. Data model compared with the recommended schema

- **Tables.** All eight recommended tables exist, including `risk_signals` (one row per
  check-in risk factor). `course_tas` is added for TA assignments.
- **Added columns.**
  - `users.failed_login_attempts` for the lockout clarification.
  - `users.activation_token_hash` and `activation_expires_at` for activation links (stored
    as a SHA-256 digest).
  - `courses.instructor_id`, optional, as the school's note allows.
  - `sessions.attendance_roster`, the roster snapshot.
- **Omitted optional columns.** These belong to features not implemented, or to values
  materialized elsewhere:
  - courses: `description`, `require_face_recognition`, `require_device_binding`;
  - sessions: `description`, `actual_start`, `actual_end`, `qr_code_secret`,
    `qr_code_expires_at`, `updated_at`;
  - devices: `browser`, `os_version`, `app_version`, `public_key_created_at`,
    `public_key_expires_at`, `attestation_passed`, `last_attestation_at`,
    `attestation_token`, `is_emulator`, `is_rooted_jailbroken`, `revocation_reason`
    (revocation time is kept in `revoked_at`);
  - checkins: `liveness_challenge_type`, `face_embedding_hash`, `qr_code_verified`.
- **Nullability.** `devices.public_key` is nullable (see section 2).
- **Session settings.** A session's venue, geofence and risk threshold are copied from the
  course when the session is created, rather than stored as nullable overrides.
- **Enumerations** are CHECK constraints rather than PostgreSQL ENUM types. Status values
  match the specification.
- **Audit immutability.** A PostgreSQL trigger rejects UPDATE, DELETE and TRUNCATE on
  `audit_logs`, and the application's database role may only SELECT and INSERT there.
- **Migrations** are forward-only Alembic revisions; the current head is `20261013_0010`.

## 5. Privacy and retention

- Check-ins (and their risk signals) are deleted 30 days after check-in.
- User accounts are anonymized 30 days after a deletion request. Audit logs are retained
  indefinitely, as the Security Requirements specify.
- Only face-template hashes are stored; no images are stored or logged.
- No student IP address is sent to a third-party service.

## 6. Deployment

- `docker-compose up -d` works from a clean clone. Compose supplies local-development
  credential defaults; any shared deployment should override them in a private `.env`.
- A one-shot `backend-migrate` service applies migrations and provisions restricted
  database roles: the application role, plus a read-only `dashboard_reader` role for
  Module 4.
- Published ports for the backend, PostgreSQL and Redis are bound to 127.0.0.1.

## 7. Known limitations and dependencies on other modules

- **Module 3** must return the documented responses, including `match_threshold` 0.70 and
  `liveness_threshold` 0.60. Until a working service is deployed, any check-in or face
  enrollment that needs it returns 503.
- **Module 1** should register the device (`POST /devices/register`) before a student's
  first check-in. Unregistered devices are flagged for review.
- Network detection is a heuristic; the IP country check uses registry data (section 1).
- Activation links must be delivered by staff; there is no email delivery.
- **Open role registration.** `POST /auth/register` accepts any role, including `admin`, as
  the Briefing instructs ("ignore security restrictions about the roles during
  registration") and as the public tests rely on. For any real deployment, registration
  must ignore `role` and create students only; roles would then be assigned by an admin
  (`PATCH /users/{id}`).
- **Lockout as denial of service.** Because the graded lockout is per account (clarification
  1), anyone who knows an email address can block that account with ten wrong passwords,
  including an administrator's. An admin unblocks accounts with
  `PATCH /admin/users/{id}/activate`. If every admin is blocked, an operator can reset
  `users.failed_login_attempts` to 0 in the database.
- Full OpenTelemetry tracing is not implemented. Prometheus metrics are exposed at `/metrics`.
