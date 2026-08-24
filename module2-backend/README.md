# Module 2 — Week 2 Backend API

This implementation provides database-backed authentication and the minimum
security foundation required to unblock the Frontend and Dashboard teams.

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

Authentication uses HS256 JWTs: access tokens expire after one hour and refresh
tokens after seven days. Passwords use bcrypt cost 12. Role values are
`student`, `ta`, `instructor`, and `admin`.

## Database scope

The initial Alembic migration intentionally creates only:

- `users` — required for authentication, profile consent, and account status
- `audit_logs` — immutable security events for registration, login, profile
  updates, and activation/deactivation

The other six project tables remain deferred until the team finalizes the full
database schema. IDs use the documented `VARCHAR(36)` UUID representation and
roles are validated string values in this interim migration.

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
- Registration is limited to 10 requests/hour/IP; login to 60/hour/IP; protected
  API calls to 1000/hour/user.
- Missing, malformed, expired, incorrectly typed, or inactive-user tokens are
  rejected.
- Password fields and hashes never appear in API responses.
- Registration accepts all four roles because the supplied API specification and
  course test fixtures require it. Restrict privileged role provisioning before
  production deployment.
