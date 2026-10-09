# SAIV Grading Clarifications

> **Current Module 2 policy (29 September 2026):** The user approved the
> [public contract reductions](BACKEND-COMPLETION.md#approved-public-contract-reductions).
> They supersede earlier conflicting examples only for optional liveness/GPS
> accuracy, per-attempt GPS permission, keyless inventory, instructor reads,
> the public course catalogue and the flagged response envelope. Other written
> requirements and grading/security values continue to govern.

These clarifications were announced after the original requirements were issued.
They override conflicting values or behavior elsewhere in the project documentation.
All other requirements remain unchanged.

## Authority

Use the following precedence when requirements conflict:

1. This grading-clarifications document
2. `SECURITY-REQUIREMENTS.md`
3. `API-SPECIFICATION.md`
4. Documents under `recommended_design/`

Public tests help validate the implementation, but do not override these written
requirements.

## Account lockout

Login must track consecutive failed password attempts for each account. After ten
consecutive failed password attempts on the same account, the account is blocked.
The tenth failed attempt and all later login attempts must return HTTP 429, including
an attempt using the correct password. A successful login before the tenth failure
resets the consecutive-failure counter.

The existing administrative account-reactivation flow may unblock the account and
reset its failed-attempt counter.

## Rate-limit values used for grading

Redis-backed rate limiting must remain implemented, but the IP-based limits must be
large enough that the test suite does not exhaust them:

| Endpoint category | Grading limit | Window | Key |
|---|---:|---:|---|
| Login attempts | 100,000 | 1 hour | Client IP address |
| Registration | 100,000 | 1 hour | Client IP address |
| General authenticated API | 1,000 | 1 hour | User ID |
| Check-in attempts | 10 | 1 minute | User ID |

The 100,000/hour login and registration values override the lower values elsewhere
in the documentation. The account lockout above is independent of per-IP rate
limiting and must still occur after ten consecutive password failures on one account.

## Singapore-only check-ins

Check-ins must be rejected with HTTP 403, or persisted with status `rejected`, when:

- The submitted GPS coordinates are outside Singapore; or
- The client uses a public IP address outside Singapore.

Determine the client IP from the first address in `X-Forwarded-For` when that header
is present. Otherwise, use the request socket address. Private and local addresses,
including `10.0.0.0/8`, `192.168.0.0/16`, and `127.0.0.0/8`, may be treated as
on-campus and allowed.

This Singapore rule takes precedence over general VPN/proxy examples in the
recommended integration and risk guidance. A private or local address must not be
rejected merely because it is private or local.

## Public-test score announcement

At the time of the announcement, the public tests totalled 92 points. This is grading
context rather than an API or security rule. Current reports should state the actual
tests and points observed because the public suite may change later.

