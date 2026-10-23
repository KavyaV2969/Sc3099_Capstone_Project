# Backend handover fixes — 29 September 2026

**H01–H04 are resolved.** The backend implementation passes all existing backend regressions and the unchanged selected external tests. The corrected image is deployed locally, healthy after restart, and serves source matching the working tree. Real biometric interoperability remains explicitly deferred (H05).

The fixes modify six existing application files. No endpoint, dependency, service, table, column, migration or configuration mode was added. Previously completed security, public compatibility, privacy, migration and recovery behavior is preserved.

## Findings addressed

| Finding | Smallest correction | Verification |
|---|---|---|
| H02: reactivated student approved but omitted from attendance | Extend the existing roster helper to select and lock the student's actively enrolled courses when no course is specified. Both administrative activation paths use it; token activation reuses it. Append only to known active rosters; preserve closed/unknown history. | Six API cases cover both activation routes, idempotence, attendance totals, closed and legacy rosters. Existing PostgreSQL activation/enrollment race also tests concurrent account reactivation. Original PostgreSQL reproduction passes. |
| H03: wholly expired date range returns inverted coverage/known zero | Validate ordering after retention clamping in the existing `window()` function. No retained overlap returns 422. | Six window cases plus statistics/JSON/CSV API checks; partial coverage and valid empty retained periods stay correct. Original PostgreSQL reproduction passes. |
| H01: explicit session export omits records across Singapore midnight | Existing session filters can omit scheduled-date bounds for an explicit session. Its export coverage extends through that session's end, while retaining cancellation/window/retention exclusions. Course reporting defaults stay unchanged. | JSON rows/counts/attendance agree with session statistics; CSV preserves the Singapore date. Three exclusions cover cancelled, expired and unopened windows. Original PostgreSQL reproduction passes. |
| H04: contradictory handover guidance/head/closure claims | Update current reporting/lifecycle contracts, flagged-envelope wording, optional-liveness/proof instructions and current readiness at 0009. Clearly label the old verification repair as historical; recovery checkpoint remains 0006. | Current documentation references below; historical migrations/provenance unchanged; full recovery/schema regressions pass. |
| H05: real biometric integration | **Deferred, as requested.** No functioning service or approved fixture exists; required matching was not weakened. | Backend HTTP evidence/failure/concurrency tests pass. Real image interoperability is not certified. |

## Files changed and why

| Application file | Requirement/defect addressed |
|---|---|
| [services/enrollments.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/enrollments.py:29) | Reuse roster inclusion for account activation, with user → ordered courses → ordered sessions locking and fresh locked roster state. |
| [routers/admin.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/admin.py:42) | Include newly eligible students when the administrative activation operation succeeds. |
| [routers/users.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/users.py:131) | Apply the same inclusion to administrative `is_active=true` updates. |
| [routers/auth.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/auth.py:136) | Replace the existing activation-course loop with the shared helper; retain single-use/password/expiry behavior and consistent course-before-session locks. |
| [services/reporting.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/services/reporting.py:23) | Reject empty retained intersections; distinguish course date filtering from explicit session selection without adding a reporting layer. |
| [routers/export.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/app/routers/export.py:110) | Explicit eligible session exports no longer inherit the course's default end-today date filter. Existing shapes, streaming, CSV neutralization and bounds remain. |

Documentation updated: [completion register](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/BACKEND-COMPLETION.md), [API specification](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/API-SPECIFICATION.md), [integration guide](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/recommended_design/INTEGRATION-GUIDE.md), [historical verification repair](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/CHECKIN-VERIFICATION-REPAIR.md), [recovery runbook](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/docs/F00-DATABASE-RECOVERY.md), and [backend README](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/README.md). The earlier audit remains a labeled pre-fix record.

## Tests added or modified

**18 additional cases**: 17 in the existing [test_completion.py](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/tests/test_completion.py:369), and one additional parameter of the existing [PostgreSQL roster race](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/module2-backend/tests/test_completion_postgresql.py:47). These verify the observed defects and preservation boundaries, not new features. Existing tests were retained; external tests, fixtures and scoring hooks were not edited.

| Gate | Final result |
|---|---|
| Targeted activation/roster group | 19 passed |
| Targeted retention/reporting group | 12 passed |
| Targeted exports/report compatibility group | 17 passed |
| Full backend, real PostgreSQL/Redis available | **407 passed, zero failures/errors/skips**, including **75 PostgreSQL cases**, 97.89 s |
| Original three disposable-PostgreSQL audit reproductions | **3 passed**, 4.08 s |
| Pinned Linux image, all non-PostgreSQL cases | **332 passed, zero skips**, 20.80 s; PostgreSQL cases passed separately in the full suite |
| Unchanged external backend tests on preserved populated database | **66 passed, one supplied skip**, 16.157 s |
| Unchanged external backend tests on fresh isolated data | **66 passed, one supplied skip**, 14.394 s |
| Same external tests on that instance after population | **66 passed, one supplied skip**, 15.032 s |
| Image source / runtime / restart | Corrected source hashes match; both backend services healthy; backend metrics scrape up |

Selected external files remain `test_api_functional.py`, `test_security_basic.py`, `test_privacy_basic.py`, `test_performance.py`, `test_observability.py`, and `test_integration.py`. The supplied concurrent-check-in skip is unchanged. Module 3 and frontend/dashboard test files remain outside the backend selection, as previously agreed. External-source hashes match the prior release; no tracked source changes exist in external tests/scoring or excluded module implementations.

Full tests include fresh/upgrade migrations, frozen readiness, restricted audit roles/triggers, legacy recovery/restore, concurrent conflicts, lockout, activation, review, proof consumption and verification finalization. Head remains `20260929_0009`; no new migration is needed. Existing integration data was not reset. Docker's stopped runtime was recovered by preserving its inaccessible socket directories; database/container volumes were retained.

## Load, deployment and remaining limits

The corrected image is `sha256:ff5864eb6d97f8288dff207f7b9aa1ccfae3b02e2e06b27409715ef7113302de`, deployed at local ports 8000 and 18000. The previous image/container remains available for rollback. `/health` verifies API/database/Redis/schema; it does not certify the face service. Backend Prometheus target is up.

Direct-container HTTP load: **440 successful requests**, zero unexpected errors, no observed pool exhaustion. Both 10- and 100-user waves meet the two-second p95 target:

| Users | `/users/me` GET p95 | `/checkins/` POST p95 |
|---|---|---|
| 10 | 0.061 s | 0.261 s |
| 100 | 1.151 s | 1.494 s |

Course-lock contention was sampled during submission, with no request failures. Biometric latency was not included because the external gate is deferred.

**Environment observation retained:** two Windows-host-port load runs had 100-user GET p95 of 5.008 s and 4.350 s, while all requests succeeded. Logged application durations for those reads were at most 0.325 s; direct-container requests meet the target. This indicates time outside the measured application request handling, but does not conclusively identify its cause. No unrelated pool/concurrency feature was added to mask it. Validate latency through the eventual deployment ingress; Windows-host high-concurrency latency is not claimed fixed.

There are **no unresolved H01–H04 backend fixes**. Real biometric interoperability remains unavailable and user-deferred; full end-to-end integration readiness therefore remains conditional. Optional QR issuance, attestation, email, refresh rotation/logout, duplicate signal storage, paid network reputation and full tracing remain deferred as before.

**Verdict:** the corrected backend implementation and selected marking contract are ready to hand over. Consumers should use the updated contracts. Do not describe real biometric interoperability or every network environment's load performance as certified.

Sanitized counts, runtime checks, source hashes and both load routes are preserved in [release evidence](C:/Users/Lenovo/Desktop/Study/SC3099/student-starter/output/backend-handover-fixes-evidence-2026-09-29.json). Test logs/XML paths are recorded there; the original failed audit evidence is preserved separately.
