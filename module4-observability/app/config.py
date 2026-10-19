"""
Central configuration for the SAIV Instructor Dashboard.

Everything here is read from environment variables (with sensible local
defaults) so the same code works both via `streamlit run app/main.py` on a
laptop and inside the docker-compose `dashboard` service.
"""
import os

# ---------------------------------------------------------------------------
# Service URLs
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_BASE = f"{BACKEND_URL}/api/v1"

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")

REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))

# How often the "live" pages auto-refresh themselves, in milliseconds.
# 30s matches the "polling is good enough for dashboards" guidance from the
# Module 4 briefing slides.
AUTO_REFRESH_MS = int(os.getenv("AUTO_REFRESH_MS", "30000"))

# ---------------------------------------------------------------------------
# Risk bands used for display; actual scoring and reviews are backend-owned.
# ---------------------------------------------------------------------------
RISK_LOW = 0.3
RISK_MEDIUM = 0.5
RISK_HIGH = 0.7

RISK_ICONS = {
    "low": "\U0001F7E2",       # green circle
    "medium": "\U0001F7E1",    # yellow circle
    "high": "\U0001F7E0",      # orange circle
    "critical": "\U0001F534",  # red circle
    "unknown": "\u26AA",       # white circle
}

STATUS_ICONS = {
    "approved": "\u2705",
    "pending": "\u23F3",
    "flagged": "\U0001F6A9",
    "rejected": "\u26D4",
    "appealed": "\U0001F64B",
}

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
# Students use the Module 1 PWA to check in; only these roles get to use the
# instructor dashboard. The backend still enforces this on every endpoint -
# this is only used so the dashboard doesn't invite students to a screen that
# will just 403 on them (see docs/SECURITY-REQUIREMENTS.md RBAC table).
DASHBOARD_ROLES = {"instructor", "ta", "admin"}
ALL_ROLES = {"student", "ta", "instructor", "admin"}

# ---------------------------------------------------------------------------
# Prometheus metric names this dashboard expects.
#
# These names come straight from docs/recommended_design/INTEGRATION-GUIDE.md
# ("Module 4: Dashboard -> Prometheus"). Because Module 2 (the backend) is
# technology-agnostic, whoever implements it may expose metrics under
# different names. If the System Metrics page shows "no data" for a panel,
# check what your backend teammate actually named their metrics and update
# the constants below - nothing else needs to change.
# ---------------------------------------------------------------------------
METRIC_HTTP_DURATION_BUCKET = "http_request_duration_seconds_bucket"
METRIC_HTTP_REQUESTS_TOTAL = "http_requests_total"
METRIC_CHECKIN_ATTEMPTS_TOTAL = "checkin_attempts_total"
METRIC_CHECKIN_SUCCESS_TOTAL = "checkin_success_total"

PROMETHEUS_JOBS = {
    "Backend API": "saiv-backend",
    "Face Recognition": "saiv-face-recognition",
}

