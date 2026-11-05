import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

from auth import is_authenticated, current_user, current_role, login_form, sidebar_user_box, flush_cookie_action
from config import BACKEND_URL, PROMETHEUS_URL

st.set_page_config(
    page_title="SAIV Instructor Dashboard",
    page_icon="📊",
    layout="wide",
)

PAGES = {
    "overview": ("pages/1_Overview.py", "Overview", "📊", ("instructor", "admin")),
    "sessions": ("pages/2_Sessions.py", "Sessions", "🗓️", ("instructor", "ta", "admin")),
    "checkins": ("pages/3_Checkins.py", "Check-ins", "✅", ("instructor", "ta", "admin")),
    "audit": ("pages/4_Audit_Logs.py", "Audit Logs", "📜", ("admin",)),
    "metrics": ("pages/5_System_Metrics.py", "System Metrics", "📈", ("admin",)),
    "courses": ("pages/6_Courses.py", "Courses", "🎓", ("instructor", "ta", "admin")),
    "enrollments": ("pages/7_Enrollments.py", "Enrollments", "👥", ("instructor", "ta", "admin")),
    "users": ("pages/8_Admin_Users.py", "Admin Users", "🛠️", ("admin",)),
}


def home_page():
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
- **System Metrics** — API latency, request rate, service health via Prometheus *(admin)*
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
        links = [(path, label, icon) for path, label, icon, roles in PAGES.values() if user.get("role") in roles]
        for start in range(0, len(links), 4):
            row = links[start:start + 4]
            cols = st.columns(4)
            for col, (path, label, icon) in zip(cols, row):
                col.page_link(path, label=label, icon=icon)


flush_cookie_action()

navigation = [st.Page(home_page, title="Home", icon="🏠", default=True, url_path="home")]
if is_authenticated():
    role = current_role()
    navigation += [
        st.Page(path, title=label, icon=icon, url_path=key)
        for key, (path, label, icon, roles) in PAGES.items()
        if role in roles
    ]

st.navigation(navigation).run()
