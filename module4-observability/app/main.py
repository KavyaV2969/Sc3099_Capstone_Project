"""
SAIV Instructor Dashboard - Module 4

Entry point. Run with:
    streamlit run app/main.py

Everything session-related (auth, role checks, shared formatting) lives in
auth.py / api_client.py / utils.py / metrics.py so that app/pages/*.py stay
focused on presentation. Streamlit auto-discovers the pages/ folder next to
this file and builds the sidebar navigation from it.
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

from auth import is_authenticated, current_user, login_form, sidebar_user_box
from config import BACKEND_URL, PROMETHEUS_URL

st.set_page_config(
    page_title="SAIV Instructor Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 SAIV Instructor Dashboard")
st.caption("Secure Attendance & Identity Verification System — Observability & Admin Portal")

if not is_authenticated():
    left, right = st.columns([1, 1])
    with left:
        login_form()
    with right:
        st.subheader("What you can do here")
        st.markdown(
            """
- **Overview** — today's check-in activity, approval rate, trends
- **Sessions** — create sessions, open/close check-in windows, drill into attendance
- **Check-ins** — filter attendance records, review the flagged/appealed queue
- **Audit Logs** — browse the immutable security/compliance trail *(admin)*
- **System Metrics** — API latency, request rate, service health via Prometheus
- **Courses / Enrollments** — manage rosters and geofence settings
- **Admin › Users** — activate/deactivate accounts, manage roles *(admin)*
            """
        )
        with st.expander("Connection settings (for troubleshooting)"):
            st.code(f"BACKEND_URL     = {BACKEND_URL}\nPROMETHEUS_URL  = {PROMETHEUS_URL}", language="text")
            st.caption(
                "Override these with the `BACKEND_URL` / `PROMETHEUS_URL` environment "
                "variables — already wired up in docker-compose.yml."
            )
else:
    sidebar_user_box()
    user = current_user()
    st.success(f"Welcome back, **{user.get('full_name', user.get('email'))}** ({user.get('role')}).")
    st.info("👈 Pick a page from the sidebar to get started.")

    cols = st.columns(4 if user.get("role") == "admin" else 3)
    cols[0].page_link("pages/1_Overview.py", label="Overview", icon="📊")
    cols[1].page_link("pages/2_Sessions.py", label="Sessions", icon="🗓️")
    cols[2].page_link("pages/3_Checkins.py", label="Check-ins", icon="✅")
    if user.get("role") == "admin":
        cols[3].page_link("pages/5_System_Metrics.py", label="System Metrics", icon="📈")
