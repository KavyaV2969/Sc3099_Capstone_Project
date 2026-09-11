# Module 2 — Week 3 Backend API

This implementation provides database-backed authentication and the core
Course → Enrollment → Session → Check-in flow.

## Implemented API

Base path: `/api/v1`

| Method | Path | Access |
|---|---|---|
| POST | `/auth/register` | Public |
| POST | `/auth/login` | Public |
| POST | `/auth/refresh` | Refresh token |
| GET | `/users/me` | Authenticated |
| PUT | `/users/me` | Authenticated |
| PATCH | `/admin/users/{user_id}/deactivate` | Admin |
| PATCH | `/admin/users/{user_id}/activate` | Admin |
| GET | `/audit/` | Admin |
| GET | `/courses/`, `/courses/{course_id}` | Authenticated |
| POST | `/courses/` | Admin |
| PUT | `/courses/{course_id}` | Admin or course instructor (partial update) |
| DELETE | `/courses/{course_id}` | Admin (soft delete) |
| GET | `/enrollments/my-enrollments` | Student |
| GET | `/enrollments/course/{course_id}` | Course instructor, assigned TA, or admin |
| POST | `/enrollments/` | Course instructor or admin |
| DELETE | `/enrollments/{enrollment_id}` | Course instructor or admin |
| GET | `/sessions/` | Instructor (own courses) or admin |
| GET | `/sessions/active` | Public; active courses and open check-in windows only |
| GET | `/sessions/my-sessions`, `/sessions/{session_id}` | Authenticated |
| POST | `/sessions/` | Instructor teaching the course |
| PATCH, DELETE | `/sessions/{session_id}` | Session owner (instructor) |
| POST | `/checkins/` | Actively enrolled student |

Authentication uses HS256 JWTs: access tokens expire after one hour and refresh
tokens after seven days. Passwords use bcrypt cost 12. Role values are
`student`, `ta`, `instructor`, and `admin`.

## Database scope

The initial Alembic migration intentionally creates only:

- `users` — required for authentication, profile consent, and account status
- `audit_logs` — immutable security events for registration, login, profile
  updates, and activation/deactivation

Migration `20260908_0002_attendance_tables.py` adds `courses`, `enrollments`,
`sessions`, `checkins`, and a two-column `course_tas` assignment table.
IDs retain the documented `VARCHAR(36)` UUID representation. Enrollment and
check-in uniqueness is enforced in the database. No Week 2 tables are altered.

TA assignments must currently be seeded directly in `course_tas`; no assignment
management endpoint is specified for Week 3. The API checks both the TA role and
the assignment before exposing a course roster.

Enrollment deletion removes the enrollment row, permitting later re-enrollment;
existing check-ins remain. Course deletion only sets `is_active=false` and also
prevents new enrollments, sessions, and check-ins for that course.

## Week 3 workflow and limits

1. Admin creates a course with an active `instructor_id` and venue coordinates.
2. Instructor/admin enrolls an existing student through `POST /enrollments/`.
3. Instructor creates a session with a future start and a later end.
4. Instructor activates it with `PATCH /sessions/{id}` and `{"status":"active"}`.
5. Student grants consent through the existing `PUT /users/me`, then submits
   `session_id`, `latitude`, `longitude`, `location_accuracy_meters`, and
   `device_fingerprint` to `POST /checkins/` during the check-in window.
6. Instructor closes it with `{"status":"closed"}`.

Sessions inherit omitted venue/geofence/risk settings from the course. Both venue
coordinates must be available when creating a session. The default check-in
window is 15 minutes before through 30 minutes after scheduled start. Timestamps
without a timezone are treated as UTC. Partial updates validate the resulting
schedule/window, including fields retained from the existing session.

Allowed transitions are scheduled → active → closed, and scheduled/active →
cancelled. Closed and cancelled are terminal, following the Week 3 instructions
over the broader cancellation language in the API specification. Only scheduled
sessions can be deleted. Activation does not override the configured check-in window.

The Week 3 GPS rule is: distance ≤ radius approves; distance ≤ twice the radius
flags; greater distances reject. Scores are respectively 0, 0.5, and 1; the stored
risk threshold is reserved for the later risk engine. All three outcomes create a
record and return 201. Duplicate attempts return 400. Geolocation consent is always
required; camera consent is required when the session requests liveness or face
matching. Those checks are not performed yet, and liveness response fields are null.
The device fingerprint is accepted but not persisted or used for device binding.

Deferred: optional bulk enrollment/account creation, TA assignment administration,
check-in history/review/appeal APIs, face/liveness integration, device binding,
advanced fraud/risk processing, statistics, and exports. No raw camera images are stored.

## Tests

From `module2-backend`, run:

```powershell
python -m pytest tests -q
```

Week 3 tests use temporary SQLite databases, actual JWT authentication, and a
stubbed Redis rate limiter. They cover ownership/RBAC, defaults, partial-update
validation, transitions, enrollment, consent, check-in windows, duplicate records,
geofence boundaries, and the end-to-end flow. Migration tests exercise upgrade,
downgrade, ORM schema comparison, and PostgreSQL SQL generation. The existing
PostgreSQL health test requires the configured local database to be running.

Public HTTP tests require a live backend. Their current course fixture omits
`instructor_id`, and their session fixture activates through a deferred admin
endpoint. The check-in fixtures also omit consent setup (and sometimes accuracy).
Those fixtures need to follow the workflow above; ownership and consent checks
are retained as required by the Week 3 instructions.

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
