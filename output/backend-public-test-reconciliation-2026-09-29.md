# Backend public-test reconciliation — 29 September 2026

> **Historical evidence:** Current status and policy are superseded by the user-approved
> [reduced-contract implementation and release report](backend-reduced-contract-2026-09-29.md).
> The earlier remaining-conflict claims below describe the policy before those reductions.

**Result: compatible backend fixes implemented; supplied public tests unchanged.**
The user explicitly chose to preserve the public tests and document remaining
conflicts. The original request to make every supplied test pass cannot be
satisfied while also preserving the authoritative requirements and the deferred
Module 3 dependency. This report does not claim a green public-suite result.

Authority: [GRADING-CLARIFICATIONS.md](../docs/GRADING-CLARIFICATIONS.md#authority)
explicitly states that public tests do not override written requirements. The
previous decisions about scoped instructor access, required device keys and
strict enabled verification remain in force.

## Minimal implementation changes

| File (under module2-backend) | Change and purpose |
|---|---|
| `app/schemas/courses.py` | Accept legacy course `require_device_binding: true` as an excluded, nonpersistent affirmation. False cannot disable the mandatory device signal. |
| `app/routers/devices.py` | POST root aliases existing registration; GET root adds bounded admin-only inventory using existing response schema. Public-key validation, ownership and revocation preserved. |
| `app/routers/audit.py` | Admin-only rolling UTC audit summary with grouped counts; immutable evidence remains read-only. |
| `app/schemas/analytics.py`, `app/routers/stats.py` | Add legacy public-consumer names without deleting existing fields. Derived rates use the same retained approved/eligible denominator; new course/student counts use existing instructor scope. |
| `app/routers/export.py` | Session JSON adds top-level session ID and records alias; existing checkins/summary/coverage preserved. |
| `tests/test_public_compatibility.py` | Seven regression cases for positive compatibility plus role/key/false-toggle refusal and approved/flagged/rejected rate semantics. |
| `tests/test_compliance.py` | Update local OpenAPI inventory: audit summary is now supported. The old assertion forbidding this route was obsolete after the requested compatibility addition. |
| `docs/BACKEND-COMPLETION.md`, API/README/report addenda | Document compatibility contracts, remaining marking conflicts and actual run scope. |

No migration, new storage, dependency, optional biometric implementation, or
change to `tests/public`, `tests/conftest.py` or scoring logic was introduced.

## Unchanged supplied-suite result

All 97 public cases collect. Real HTTP execution against the updated isolated
backend image (PostgreSQL and Redis, not main integration data) returned:

- **68 passed, 12 failed, 1 fixture error, 16 skipped in 23.59 seconds.**
- 15 skips are face-service tests because no service is running at the configured
  local endpoint; the checked-in implementation is still a 501 scaffold. One
  concurrent-checkin case is unconditionally skipped by its supplied decorator.
- The supplied scoring plugin reported **58/75 observed points (77.3%)**. Its
  observed denominator excludes unavailable/setup-failed cases; this is not a
  full-project marking prediction or evidence of a complete grading pass.
- Previous 79-case backend-facing baseline: 43 passed, 6 failed, 29 fixture
  errors, 1 skip. The new course compatibility removed 28 cascading setup errors
  and exposed downstream assumptions; fewer fixture errors do not mean every
  newly reached assertion passes.

JUnit: `tmp/backend-public-compatibility.xml`; output:
`tmp/backend-public-compatibility.txt`. No hidden test-specific behavior or fake
success responses were added.

## Every remaining failure/error and its authority conflict

Paths in the first column are relative to `tests/public`.

| Supplied case | Actual outcome and cause | Authoritative requirement | Required test-side reconciliation, intentionally not applied |
|---|---|---|---|
| `test_api_functional.py::TestCheckInWorkflow::test_successful_checkin` | 403: newly registered fixture student has not granted geolocation/camera consent; session requires liveness and no image is submitted. | Security Consent Tracking; API POST /checkins verification requirements; `checkins._validate_eligibility`. | Grant explicit consent and either explicitly disable optional verification in this fixture or provide real service/evidence. |
| `test_api_functional.py::TestCheckInWorkflow::test_duplicate_checkin_fails` | First attempt 422: missing `location_accuracy_meters`; same consent/verification prerequisites would apply afterward. | API check-in request/typed `CheckinCreate` validation; consent and enabled evidence requirements. | Submit accuracy and satisfy eligibility/evidence before testing duplicate attendance. |
| `test_api_functional.py::TestCheckInWorkflow::test_list_my_checkins` | Empty history: setup submission fails validation and creates no check-in. | Invalid submissions must not create attendance; same required inputs/consents/evidence. | Assert setup response succeeds with valid prerequisites before asserting populated history. |
| `test_frontend_dashboard.py::TestFrontendCheckinContract::test_checkin_request_format` | 403: no geolocation consent; required liveness image null. Test only permits 201/400. | Consent cannot be assumed; enabled biometric input cannot be omitted. | Grant consent and provide evidence, or explicitly select a session with both optional biometric checks disabled. |
| `test_integration.py::TestEndToEndCheckIn::test_complete_student_checkin_flow` | 422: missing accuracy. This flow does grant consent and explicitly disables liveness. | API request/typed check-in accuracy validation. | Add `location_accuracy_meters`; no biometric policy change is needed for this flow. |
| `test_observability.py::TestStatsEndpoints::test_stats_course` | 403: instructor neither assigned to course nor owner of a session there. | Documented taught-course scope in completion contract and access helpers; earlier settled instructor permissions. | Assign instructor explicitly or create their session before querying course analytics. |
| `test_observability.py::TestStatsEndpoints::test_stats_student` | 403: target enrollment belongs to a course unrelated to the instructor. | Same taught-course scope; student data must remain scoped to legitimate teaching access. | Provision the teaching relationship first. |
| `test_observability.py::TestEnrollmentManagement::test_list_course_enrollments` | 403: no teaching/TA relationship to the course. | Scoped enrollment/student access. | Provision authorized teaching relationship first. |
| `test_observability.py::TestCheckinFiltering::test_flagged_checkins_queue` | Returns documented array `[]`; test requires `items`/`total` envelope. | API GET /checkins/flagged explicitly shows an array; existing consumers retain that contract. | Assert the documented list, or agree a separately requested opt-in envelope contract. |
| `test_performance.py::TestResponseLatency::test_checkin_endpoint_latency` | 422: omitted accuracy; consent/liveness prerequisites also missing. | Same check-in validation and verification requirements. | Supply valid inputs and explicitly provision appropriate session policy/consent before measuring latency. |
| `test_performance.py::TestResponseLatency::test_list_endpoint_latency` | 401: courses requested without bearer token. | API GET /courses/ explicitly requires auth. | Use authenticated headers for the latency request. |
| `test_performance.py::TestDatabaseOptimization::test_pagination_support` | 401: courses requested without bearer token. | Same explicit auth requirement. | Use authenticated headers for pagination request. |
| `test_api_functional.py::TestDeviceManagement::test_list_my_devices` (fixture error) | 422: fixture omits required public key and sends unsupported browser field. | API POST /devices/register explicitly requires a nonblank key; completion contract requires valid parsed P-256/RSA key. | Register a valid disposable public key with accepted fields. Never invent a server key or grant proof-based trust without possession. |

Relevant source: [public fixtures](../tests/conftest.py),
[API specification](../docs/API-SPECIFICATION.md),
[security requirements](../docs/SECURITY-REQUIREMENTS.md),
[current contracts](../docs/BACKEND-COMPLETION.md).
Several face tests also depend on sample images and the actual provider; no fake
face or liveness service was supplied to manufacture passing results.

## Backend regression/deployment verification

Final backend-local suite: **356 passed in 65.37 seconds, zero failures/errors/
skips**, including all 71 PostgreSQL cases (54 original + 17 completion cases).
Pinned Linux test image: **285 passed in 20.02 seconds**.
Fresh JUnit: `tmp/backend-public-compatibility-local.xml`.
Production image:
`sha256:17a24dd784c1beb7f5d3c35d3ed7a88887200e4e7549abb4f5c22479aa03847a`.
No schema change was needed. The existing startup migration job and schema/
DB/Redis readiness remain applicable. Prior normal-API load evidence remains
historical; no additional latency claim is made for the new admin/statistics routes.
The updated migration job completed and the main backend returned healthy
API/database/Redis/schema status after image replacement. The isolated public-test
instance was stopped after the run. Source diff validation passed.
[Sanitized result evidence](backend-public-test-evidence-2026-09-29.json).
The affected change group already passed **118 tests**. Initial broader runs
identified one obsolete backend-local assertion prohibiting `/audit/summary`;
that inventory assertion was updated to the now documented supported route.
No supplied public assertion was edited.

## Disposition

Compatible behavior is implemented and reviewable. Remaining failures are
explicit requirement/test inconsistencies; the user has chosen to leave them
unchanged. The real biometric gate remains deferred, so neither an all-public
pass nor real integration readiness is claimed.
