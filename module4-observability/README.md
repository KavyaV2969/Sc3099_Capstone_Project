# SC3099 Module 4 — Observability & Instructor Dashboard

**Integration baseline:** 19 October 2026 repository snapshot supplied in `20261019 Codebase.zip`. The 22 September Module 4 draft was adapted to the **actual** Module 2 routers and Pydantic schemas; it was not pasted unchanged. The starter-pack docs and all five course PDFs were used as additional design constraints.

## Architectural role

The staff dashboard (Streamlit, port **8501**) calls Module 2 via its authenticated `/api/v1` REST routes (backend port **8000**) and reads observability data from Prometheus (port **9090**). It must not process or store face images, calculate attendance/risk decisions itself, change database records directly, or bypass backend authorization. Backend endpoints are the source of truth.

The app intentionally omits the old `DB Insights` optional SQL page. That page depended on direct database credentials, was not essential to the rubric, and could expose personal data beyond the API's per-course authorization. The 19 October `prometheus.yml`, Grafana provisioning files and `otel-collector-config.yml` are preserved to keep the existing Compose volume mounts intact.

## File layout

```text
module4-observability/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── auth.py
│   ├── api_client.py
│   ├── utils.py
│   ├── metrics.py
│   └── pages/
│       ├── 1_Overview.py
│       ├── 2_Sessions.py
│       ├── 3_Checkins.py
│       ├── 4_Audit_Logs.py
│       ├── 5_System_Metrics.py
│       ├── 6_Courses.py
│       ├── 7_Enrollments.py
│       └── 8_Admin_Users.py
├── tests/
│   ├── test_dashboard_unit.py
│   └── test_page_smoke.py
├── .streamlit/config.toml
├── .dockerignore
├── .env.example
├── Dockerfile
├── requirements.txt
├── prometheus.yml
├── otel-collector-config.yml
└── grafana/provisioning/{dashboards.yml,datasources.yml}
```

## Key features and role permissions

| Feature | Admin | Instructor | TA |
|---|:---:|:---:|:---:|
| Sign in / refresh JWT / sign out | ✓ | ✓ | ✓ |
| Overview analytics (`/stats/overview`) | ✓ | ✓ | — |
| Session list | All | Own | Assigned via `/sessions/my-sessions` |
| Create, activate, close sessions | ✓ | Own | — |
| Session check-ins and session statistics | ✓ | Own | Assigned |
| Flagged/appealed check-in review | ✓ | Own | Assigned |
| Global check-in list | ✓ | Own | — (session-only instead) |
| Course roster view | ✓ | Own / permitted | Assigned |
| Add/remove enrollments | ✓ | Own | — |
| Create/edit courses | ✓ | — | — |
| Course statistics and official gradebook export | ✓ | Own | — |
| Audit log browsing | ✓ | — | — |
| Prometheus system metrics | ✓ | — | — |
| User account management | ✓ | — | — |

**These are UI guards, not a substitute for backend RBAC.** The actual backend enforces permissions on every endpoint, including access to students' data.

## How to run

### Option A: existing team Docker stack (preferred)

From the repository root, with Docker Desktop running:

```powershell
docker compose config
docker compose up -d --build postgres redis backend face-recognition prometheus grafana otel-collector dashboard
docker compose ps
docker compose logs --tail 100 dashboard
```

Then open `http://localhost:8501`. The app uses the existing Compose environment entries `BACKEND_URL=http://backend:8000` and `PROMETHEUS_URL=http://prometheus:9090`. **Do not set these container-internal names on your Windows host** — use `localhost` for running Streamlit outside Docker.

### Option B: standalone dashboard on Windows with an already-running backend

From `module4-observability` in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m pytest tests -q
$env:BACKEND_URL = "http://localhost:8000"
$env:PROMETHEUS_URL = "http://localhost:9090"
.\.venv\Scripts\python.exe -m streamlit run app/main.py --server.port 8501
```

The `.env.example` file documents settings; plain Streamlit does **not** automatically load `.env`. Set environment variables in the shell as above. You need valid staff credentials registered with the real backend. The old demo's `dev_mock_backend` is **not** included in the submission patch, and its seeded credentials are **not** valid against this backend.

### Offline regression tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

The included suite covers REST client login/refresh, denied roles, error recovery, deletion with 204 responses, CSV safety and timestamps; the page smoke tests simulate role-specific and empty/populated data for all eight page scripts, plus create-session and review submissions. The page tests **simulate** Streamlit: they do not prove actual browser rendering, Docker health, or real backend integration. Re-run with a real browser and team services before merging.

From the repository root, after all services are live, use the course's official tests:

```powershell
py -m pip install -r requirements-test.txt
$env:TEST_BACKEND_URL = "http://localhost:8000"
$env:TEST_FACE_URL = "http://localhost:8001"
py -m pytest tests/public -v
```

These public tests exercise many Module 1/2/3 behaviors too; failing one does not necessarily indicate a Module 4 problem.

## Backend contract cross-reference

The code follows the real 19 October route definitions in `module2-backend/app/routers/`:

- Auth: `POST /auth/login`, `POST /auth/refresh`, `GET /users/me`
- Sessions: `GET /sessions/` (instructor/admin), `GET /sessions/my-sessions` (TA), `POST /sessions/`, `PATCH /sessions/{id}`, `GET /sessions/{id}`
- Check-ins: `GET /checkins/` (instructor/admin), `GET /checkins/session/{id}`, `GET /checkins/flagged`, `POST /checkins/{id}/review` (requires non-empty `review_notes`)
- Analytics: `GET /stats/overview` (instructor/admin), `GET /stats/sessions/{id}`, `GET /stats/courses/{id}`, `GET /stats/students/{id}`
- Exports: `GET /export/session/{id}`, `GET /export/attendance/{id}` with `format=csv|json`, instructor/admin only
- Audit: `GET /audit/` admin-only. **There is no `/audit/summary`** in the current backend, so a bounded client-side action summary is derived from `/audit/` and marked incomplete if more than 1,000 matching rows exist.
- Courses: `GET /courses/`, `POST /courses/` and `PUT /courses/{id}` (writes admin-only)
- Enrollments: `GET /enrollments/course/{id}`, `POST /enrollments/`, `POST /enrollments/bulk`, `DELETE /enrollments/{id}` (mutations instructor/admin only). `create_accounts=true` is not supported by the current backend, so the dashboard does not offer it.
- Users: `GET /users/`, `PATCH /users/{id}`, activation/deactivation via `/admin/users/{id}/activate|deactivate` (admin-only)

The spec examples, public tests and actual backend schemas do not always name statistics keys identically. `utils.pick(...)` handles known equivalent fields without inventing data for unavailable keys. **Attendance success rate is not the same thing as gradebook approval rate.** CSV preview downloads contain only the rows currently loaded and are clearly marked; official server exports are the full gradebook source. Client-side preview CSVs omit raw GPS/device/risk-factor data and escape spreadsheet formula-like input.

## Integration boundaries — what still requires teammates

1. **No complete live Docker verification in this delivery environment.** Docker is unavailable here, and the environment cannot download Streamlit wheels. Validation is limited to Python compilation, YAML parsing, and the offline regression suite. The earlier agent's mock-backend run was historical, not a fresh check against the 19 October services.
2. **Backend and face service currently lack Prometheus instrumented `/metrics` routes.** The provided Prometheus configuration scrapes `/metrics` at both services. Until those service owners expose compatible counters/histograms, service targets may show down/unavailable and latency/request-rate panels will say `no data`. The backend business stats pages still work independently.
3. **Prometheus metric naming contract:** the dashboard expects `http_request_duration_seconds_bucket`, `http_requests_total`, `checkin_attempts_total`, `checkin_success_total` as in the integration guide. If teammates choose different names, align constants in `app/config.py` with instrumentation (and adjust `app/metrics.py` if label conventions differ).
4. **Collector version compatibility:** the repository's pre-existing OpenTelemetry collector YAML uses a `logging` exporter. The Compose image uses `:latest`; the team should validate this collector/exporter combination, ideally pin versions in a coordinated infrastructure PR rather than changing them blindly inside Module 4.
5. **Privacy:** raw face images are never read or retained by this dashboard. Official backend exports can include personal data and should be downloaded only by authorized staff, stored securely, and deleted according to your team's retention policy. The backend must escape formula-like strings in official CSV exports if they will be opened in Excel; that backend-side hardening is outside Module 4.
6. **Permissions and sample data:** some pages require realistic courses, assigned instructors/TAs, enrolled students, and flagged check-ins. Empty states are implemented, but these workflows must be demonstrated with real populated team data.

## Troubleshooting

- **Can't sign in**: check `http://localhost:8000/health`, the backend account, and the Docker backend logs. Use staff account roles; student accounts are denied by the dashboard.
- **403 on a page**: the backend is enforcing role/ownership. Do not bypass it; ensure the user is assigned to the intended course/session.
- **422 creating a session**: use a future SGT start time, end after start, and a course with venue coordinates.
- **No metrics**: verify Prometheus at `http://localhost:9090/targets`, check the two `/metrics` endpoints and labels with the Module 2/3 owners.
- **Audit summary incomplete**: it is a 1,000-row sample with an explicit warning; use audit explorer filters/pagination for older events.
- **Download disappeared**: regenerate after changing session/course/format; generated exports are cached only within the user's Streamlit session and cleared on logout.

**Don't deploy this to the public internet unchanged.** Project defaults (HTTP-only services, sample Compose passwords, and the unrestricted role-selection registration contract) are for the course's local lab setup, not a production security model.
