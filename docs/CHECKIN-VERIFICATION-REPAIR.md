# Check-in verification and weighted scoring repair

Implemented 28 September 2026 for backend audit F01/F02, directly related F04
finalization and F13 configured defaults. Authority remains grading clarifications,
Security Requirements, API Specification, recommended design, then the PDFs.
Historical audit findings are retained as evidence; this document describes the repair.

## Integration contract

| Condition | Result |
|---|---|
| Either session verification flag enabled, no nonblank image | 400; no check-in |
| Required service times out, cannot connect, or returns malformed/inconsistent data | 503; no check-in |
| Service rejects image with 400/422 | Backend 400; no check-in |
| Valid failed liveness or matching | 201 with persisted rejected check-in |
| Verification flags or reference hash change during service calls | 409; reload requirements and resubmit |
| Both verification flags false | No biometric calls; null biometric results |

Service responses use operation-specific validation. Pass flags are strict booleans,
scores finite numbers in [0,1], and thresholds must match 0.60 liveness / 0.70 face.
Pass flags must equal the score comparison. Matching cannot pass without a detected
face. Successful enrollment requires a 64-hex hash, quality >=0.50, face detection,
and detection confidence >=0.70. Unknown extra fields remain compatible; optional
hashes are validated when supplied. Service success uses 201 for enrollment and
200 for liveness/matching. Backend diagnostics contain only operation, failure
category, upstream status and duration. Image decoding remains the service's job.

## One policy, with explicit remaining limitations

Every new check-in uses app/risk.py, policy weighted-v1. Fixed weights are liveness
0.25, face 0.25, device 0.20, network 0.15 and geolocation 0.15. Enabled biometric
risk is 1 minus score. Disabled verification contributes zero without renormalization.
The scorer refuses missing or inconsistent required evidence independently of routes.

Device risk is 0 for an active owned trusted device, 0.5 for an active owned
untrusted device, and 1 for unknown, inactive or another owner's fingerprint.
This is inventory-based trust, not proof of private-key possession. Network detection
remains unavailable and contributes zero in the check-in route. Singapore GPS/IP
eligibility remains independently enforced, including the private/local IP exception.
Attestation, signatures, VPN/proxy detection, replay and impossible travel remain
separate F05/F06 work.

Geolocation risk is min(1, distance/radius), plus 0.25 when accuracy exceeds radius,
capped at 1. Scores round to four decimals. Valid failed biometrics or distance
strictly greater than twice radius reject regardless of score. Score >=0.70 always
rejects. Below 0.70, score >= session threshold flags; otherwise it approves.
Threshold zero never auto-approves; threshold one cannot override rejection.
Positive risk factors retain category/severity/weight and add risk, contribution
and critical. Outcome audits record policy, effective threshold, enabled checks,
all contributions and network_detection=unavailable, without images or hashes.

Explicit session thresholds override course thresholds. New courses without an
explicit threshold use RISK_SCORE_THRESHOLD (default 0.50). ORM creation defaults
match that setting. Existing persisted course/session thresholds remain unchanged.

## Transactions and races

Capture immutable IDs, flags and reference hash, commit the attempted audit and
release the transaction before service calls. No ORM access or database locks
span those awaits. Finalization refreshes locked rows in the order user, course,
session, enrollment and device. It rechecks account, role, consents, session window,
course/enrollment eligibility and uniqueness. It uses fresh venue, radius, threshold
and device values. Changed verification policy requires a new submission (409).
Attendance, device counters and outcome audit commit together. Face enrollment
also releases its initial read transaction and rechecks locked account/consent
before updating the hash. Schema migrations and historical attendance are unchanged.

## Verification evidence

The automated suite includes actual HTTP payload/response handling via httpx
MockTransport and backend routes. These are controlled contract fixtures, not a
claim of real Module 3 interoperability. Real PostgreSQL tests use separate
connections, production-style expiry, finite lock/statement timeouts and disposable
migrated databases. They cover policy/hash changes, account/role/consent changes,
course/enrollment deactivation, session closure, fresh scoring settings, simultaneous
duplicates, and enrollment consent/activity races.

F00 recovery tests now restore the original immutable dump into fresh disposable
databases rather than assuming the operator's committed rehearsal remains legacy.
Recovery schemas, provenance and migration files are preserved. Native client tools
are used by default; set F00_POSTGRES_CONTAINER for Docker pg_restore transport.

**Full-suite result: 285 passed in 61.23 seconds, including 54 real PostgreSQL
tests (35 F00 and 19 finalization races), with no skips.** Private evidence: tmp/verification-tests.xml and
tmp/verification-readiness.json. The readiness evidence proves all original
column values/primary keys still match the pre-F00 backup, excluding its single
known recovery event. Counts remain users 403, courses 99, sessions 77,
enrollments 41, devices 4, checkins 9, course_tas 0 and audit_logs 1238.
Revision remains 20260928_0006, schema readiness is healthy and Checkin reads work.

## Rollout checklist

- [x] Required images and endpoint-specific service results enforced.
- [x] Legacy scoring removed; current threshold/accuracy/device inputs honored.
- [x] Fresh locked finalization and PostgreSQL race tests added.
- [x] Configured creation defaults and existing-value preservation verified.
- [x] API specification and permissive integration examples updated.
- [x] Read-only existing-database preservation and liveness-session inventory captured.
- [ ] Restore Module 3 availability and verify real-service enrollment/matching;
  verify liveness too for sessions that enable it. Do not claim this from fixtures.
- [ ] Owners review the 65 active/scheduled sessions currently requiring liveness
  listed in tmp/verification-readiness.json. Keep the requirement only with an
  available tested capability, or explicitly disable the bonus requirement.
- [ ] Rehearse 400/503/409 retry handling and persisted rejected outcomes with clients.
- [ ] Deploy/restart the repaired backend after capability review; inspect its
  sanitized diagnostics and outcome audits. This repair has not restarted traffic.

The local face service was unavailable during the read-only rollout inspection.
Session flags were not changed automatically. F05/F06, image/body/decompressed
response hardening, and other unrelated audit findings remain open.
