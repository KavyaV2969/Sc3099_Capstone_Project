# SAIV Database Schema

> Apply [`../GRADING-CLARIFICATIONS.md`](../GRADING-CLARIFICATIONS.md) before this
> recommended design when requirements conflict, especially for account lockout and
> Singapore-only check-ins.

## Overview

PostgreSQL database with 8 main tables for users, courses, sessions, check-ins, devices, risk signals, and audit logs.

---

## Entity Relationship Diagram

```
Users â”€â”¬â”€< Enrollments >â”€â”€ Courses
       â”‚
       â”œâ”€< Devices
       â”‚
       â”œâ”€< CheckIns >â”€â”€ Sessions â”€â”€< Courses
       â”‚                    â”‚
       â””â”€< AuditLogs        â””â”€< RiskSignals
```

---

## Tables

### users

Stores user accounts (students, instructors, TAs, admins).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| email | VARCHAR(255) | UNIQUE, NOT NULL | User email |
| full_name | VARCHAR(255) | NOT NULL | Full name |
| hashed_password | VARCHAR(255) | NOT NULL | Bcrypt hash |
| role | ENUM | NOT NULL | student\|instructor\|ta\|admin |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Account status |
| camera_consent | BOOLEAN | DEFAULT FALSE | Camera permission |
| geolocation_consent | BOOLEAN | DEFAULT FALSE | Location permission |
| face_embedding_hash | VARCHAR(64) | NULLABLE | SHA-256 hash (not raw embedding!) |
| face_enrolled | BOOLEAN | DEFAULT FALSE | Has enrolled face |
| created_at | TIMESTAMP | NOT NULL | Creation time |
| updated_at | TIMESTAMP | NOT NULL | Last update |
| last_login_at | TIMESTAMP | NULLABLE | Last login |
| scheduled_deletion_at | TIMESTAMP | NULLABLE | Auto-delete time (30 days) |

**Indexes:** email, role, is_active

**Privacy Note:** Only store face_embedding_hash, NEVER raw images or embeddings!

---

### courses

Course information.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| code | VARCHAR(20) | UNIQUE, NOT NULL | e.g., "CS6101" |
| name | VARCHAR(255) | NOT NULL | Course name |
| description | TEXT | NULLABLE | Description |
| semester | VARCHAR(20) | NOT NULL | e.g., "AY2024-25 Sem 1" |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Active status |
| venue_latitude | FLOAT | NULLABLE | Default venue lat |
| venue_longitude | FLOAT | NULLABLE | Default venue lng |
| venue_name | VARCHAR(255) | NULLABLE | Venue name |
| geofence_radius_meters | FLOAT | DEFAULT 100.0 | Check-in radius |
| require_face_recognition | BOOLEAN | DEFAULT FALSE | Require face match |
| require_device_binding | BOOLEAN | DEFAULT TRUE | Require device binding |
| risk_threshold | FLOAT | DEFAULT 0.5 | Risk score threshold (0-1) |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

**Indexes:** code, semester, is_active

**Note:** there is deliberately no `instructor_id` column on `courses`. The
instructor is recorded per session (`sessions.instructor_id`), since different
sessions of a course may be run by different instructors/TAs. If your design
needs a course-level instructor, add a nullable `instructor_id` FK(users.id)
column; the API specification and tests do not require it.

---

### enrollments

Student enrollments in courses.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| student_id | VARCHAR(36) | FK(users.id), NOT NULL | Student |
| course_id | VARCHAR(36) | FK(courses.id), NOT NULL | Course |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Active enrollment |
| enrolled_at | TIMESTAMP | NOT NULL | Enrollment time |
| dropped_at | TIMESTAMP | NULLABLE | Drop time |

**Indexes:** student_id, course_id, (student_id, course_id) UNIQUE

---

### sessions

Attendance sessions (lectures, tutorials, etc.).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| course_id | VARCHAR(36) | FK(courses.id), NOT NULL | Course |
| instructor_id | VARCHAR(36) | FK(users.id), NULLABLE | Instructor |
| name | VARCHAR(255) | NOT NULL | e.g., "Lecture 5" |
| session_type | VARCHAR(50) | DEFAULT 'lecture' | lecture\|tutorial\|lab\|exam |
| description | TEXT | NULLABLE | |
| scheduled_start | TIMESTAMP | NOT NULL | Session start |
| scheduled_end | TIMESTAMP | NOT NULL | Session end |
| checkin_opens_at | TIMESTAMP | NOT NULL | Check-in window start |
| checkin_closes_at | TIMESTAMP | NOT NULL | Check-in window end |
| status | ENUM | NOT NULL | scheduled\|active\|closed\|cancelled |
| actual_start | TIMESTAMP | NULLABLE | Actual start |
| actual_end | TIMESTAMP | NULLABLE | Actual end |
| venue_latitude | FLOAT | NULLABLE | Override venue |
| venue_longitude | FLOAT | NULLABLE | |
| venue_name | VARCHAR(255) | NULLABLE | |
| geofence_radius_meters | FLOAT | NULLABLE | Override radius |
| require_liveness_check | BOOLEAN | DEFAULT TRUE | Require liveness |
| require_face_match | BOOLEAN | DEFAULT FALSE | Require face match |
| risk_threshold | FLOAT | NULLABLE | Override threshold |
| qr_code_secret | VARCHAR(64) | NULLABLE | One-time QR code |
| qr_code_expires_at | TIMESTAMP | NULLABLE | |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

**Indexes:** course_id, status, scheduled_start, (checkin_opens_at, checkin_closes_at)

---

### devices

Registered user devices.

F00 legacy transition: two existing devices have no public key. Preserve their rows
and NULL values; new registrations and re-registrations must supply a nonblank
public key. Storage remains nullable until their owners supply real keys and a
separate verified migration enforces NOT NULL. Do not invent keys or remove devices
to enforce this requirement. Other implemented device widths, uniqueness and
nullability follow the table below. Additional attestation/key-rotation fields
remain feature work outside the F00 schema reconciliation.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| user_id | VARCHAR(36) | FK(users.id), NOT NULL | Owner |
| device_fingerprint | VARCHAR(64) | UNIQUE, NOT NULL | Hash of device ID |
| device_name | VARCHAR(255) | NULLABLE | User-friendly name |
| platform | VARCHAR(50) | NULLABLE | ios\|android\|web\|desktop |
| browser | VARCHAR(100) | NULLABLE | For web clients |
| os_version | VARCHAR(50) | NULLABLE | |
| app_version | VARCHAR(50) | NULLABLE | |
| public_key | TEXT | NOT NULL | RSA/ECDSA public key |
| public_key_created_at | TIMESTAMP | NOT NULL | |
| public_key_expires_at | TIMESTAMP | NULLABLE | For rotation |
| attestation_passed | BOOLEAN | DEFAULT FALSE | SafetyNet/Play Integrity |
| last_attestation_at | TIMESTAMP | NULLABLE | |
| attestation_token | TEXT | NULLABLE | Encrypted token |
| is_trusted | BOOLEAN | DEFAULT FALSE | Trust status |
| trust_score | VARCHAR(20) | DEFAULT 'low' | low\|medium\|high |
| is_emulator | BOOLEAN | DEFAULT FALSE | Emulator flag |
| is_rooted_jailbroken | BOOLEAN | DEFAULT FALSE | Root flag |
| first_seen_at | TIMESTAMP | NOT NULL | |
| last_seen_at | TIMESTAMP | NOT NULL | |
| total_checkins | INTEGER | DEFAULT 0 | Counter |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| revoked_at | TIMESTAMP | NULLABLE | |
| revocation_reason | TEXT | NULLABLE | |

**Indexes:** user_id, device_fingerprint, is_active, is_trusted

---

### checkins

Student check-in records.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| session_id | VARCHAR(36) | FK(sessions.id), NOT NULL | Session |
| student_id | VARCHAR(36) | FK(users.id), NOT NULL | Student |
| device_id | VARCHAR(36) | FK(devices.id), NULLABLE | Device used |
| status | ENUM | NOT NULL | pending\|approved\|flagged\|rejected\|appealed |
| checked_in_at | TIMESTAMP | NOT NULL | Check-in time |
| verified_at | TIMESTAMP | NULLABLE | Approval time |
| latitude | FLOAT | NULLABLE | GPS lat (with consent) |
| longitude | FLOAT | NULLABLE | GPS lng |
| location_accuracy_meters | FLOAT | NULLABLE | GPS accuracy |
| distance_from_venue_meters | FLOAT | NULLABLE | Calculated distance |
| liveness_passed | BOOLEAN | NULLABLE | Liveness result |
| liveness_score | FLOAT | NULLABLE | 0-1 confidence |
| liveness_challenge_type | VARCHAR(50) | NULLABLE | blink\|head_turn\|speak |
| face_match_passed | BOOLEAN | NULLABLE | Match result |
| face_match_score | FLOAT | NULLABLE | 0-1 similarity |
| face_embedding_hash | VARCHAR(64) | NULLABLE | SHA-256 hash |
| risk_score | FLOAT | NOT NULL, DEFAULT 0.0 | 0-1 risk score |
| risk_factors | TEXT | NULLABLE | JSON array |
| qr_code_verified | BOOLEAN | DEFAULT FALSE | QR verification |
| reviewed_by_id | VARCHAR(36) | FK(users.id), NULLABLE | Reviewer |
| reviewed_at | TIMESTAMP | NULLABLE | Review time |
| review_notes | TEXT | NULLABLE | |
| appeal_reason | TEXT | NULLABLE | Student appeal |
| appealed_at | TIMESTAMP | NULLABLE | |
| scheduled_deletion_at | TIMESTAMP | NULLABLE | Auto-delete (30 days) |

**Indexes:** session_id, student_id, status, checked_in_at, risk_score, (session_id, student_id) UNIQUE

**Constraint:** One check-in per student per session

---

### risk_signals

Individual risk indicators for check-ins.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| checkin_id | VARCHAR(36) | FK(checkins.id), NOT NULL | Related check-in |
| signal_type | ENUM | NOT NULL | See types below |
| severity | ENUM | NOT NULL | low\|medium\|high\|critical |
| confidence | FLOAT | NOT NULL, DEFAULT 1.0 | 0-1 confidence |
| details | TEXT | NULLABLE | JSON metadata |
| weight | FLOAT | NOT NULL, DEFAULT 0.1 | Contribution to risk |
| detected_at | TIMESTAMP | NOT NULL | Detection time |

**Signal Types:**
- Geo: `geo_out_of_bounds`, `impossible_travel`, `geo_accuracy_low`
- Network: `vpn_detected`, `proxy_detected`, `tor_detected`, `suspicious_ip`
- Device: `device_unknown`, `device_emulator`, `device_rooted`, `attestation_failed`
- Behavioral: `rapid_succession`, `unusual_time`, `pattern_anomaly`
- Liveness: `liveness_failed`, `liveness_low_confidence`, `deepfake_suspected`, `replay_suspected`
- Face: `face_match_failed`, `face_match_low_confidence`

**Indexes:** checkin_id, signal_type, severity, detected_at

---

### audit_logs

Immutable audit trail.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR(36) | PK | UUID |
| user_id | VARCHAR(36) | FK(users.id), NULLABLE | Actor |
| action | ENUM | NOT NULL | See actions below |
| resource_type | VARCHAR(50) | NULLABLE | user\|checkin\|session\|etc |
| resource_id | VARCHAR(36) | NULLABLE | Affected resource |
| ip_address | VARCHAR(45) | NULLABLE | IPv4/IPv6 |
| user_agent | VARCHAR(500) | NULLABLE | Client info |
| device_id | VARCHAR(36) | NULLABLE | Device used |
| details | TEXT | NULLABLE | JSON details |
| success | BOOLEAN | DEFAULT TRUE | Success flag |
| timestamp | TIMESTAMP | NOT NULL | Immutable timestamp |

**Actions:** `login_success`, `login_failed`, `logout`, `user_created`, `checkin_attempted`, `checkin_approved`, `checkin_rejected`, `data_exported`, `security_violation`, etc.

**Indexes:** user_id, action, timestamp, (resource_type, resource_id), ip_address

**Important:** NO `updated_at` field - logs are immutable!

---

## Migration Strategy

Use Alembic for database migrations:

```bash
# Create migration
alembic revision --autogenerate -m "Initial schema"

# Apply migration
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## Privacy Requirements

1. **No Raw Face Data**: Only store SHA-256 hashes
2. **No BLOB Columns**: No binary data in user/checkin tables
3. **PII Retention**: Auto-delete after 30 days (scheduled_deletion_at)
4. **Audit Trail**: All sensitive actions must be logged
5. **Consent Tracking**: Camera and geolocation consent required

---

## Performance Optimization

1. **Indexes**: All foreign keys and frequently queried columns
2. **Unique Constraints**: Prevent duplicate enrollments and check-ins
3. **Connection Pooling**: Use SQLAlchemy pool (size=10, max_overflow=20)
4. **Query Optimization**: Use eager loading for relationships

---

## Testing

Validate schema with public tests:
```bash
pytest tests/public/test_privacy_basic.py -v
```
# Implemented Module 2 schema â€” 29 September 2026

This document retains the recommended design below. The implemented contract is
the eight existing application tables plus forward migrations `20260929_0007`
and `20260929_0008`; see [completion contract](../BACKEND-COMPLETION.md).
`Checkin.risk_factors` and immutable outcome-audit contributions provide risk
signals; consumers must not expect a duplicate `risk_signals` table.
`course_tas` provides administrative course assignments. Session venue settings
are materialized rather than live nullable overrides. Optional descriptive,
attestation and QR columns are intentionally absent.
New storage consists only of activation digest/expiry, device revocation time,
and a retained JSON-in-TEXT session roster. A null roster means historical
eligibility is unavailable, never an empty class. Audit mutation triggers and
counter/activation/revocation constraints are part of the frozen head contract.
Historical recovery still verifies `20260928_0006` before the normal forward
upgrade to `20260929_0008`; no historical migration/provenance is rewritten.
