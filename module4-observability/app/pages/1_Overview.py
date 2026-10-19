import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, current_role, get_client
from api_client import safe_call
from utils import risk_badge, status_badge, fmt_dt, safe_items, pick
from config import AUTO_REFRESH_MS

st.set_page_config(page_title="Overview · SAIV Dashboard", page_icon="📊", layout="wide")
require_role("instructor", "ta", "admin")
sidebar_user_box()

st.title("📊 Overview")

with st.sidebar:
    st.markdown("### Live updates")
    auto = st.toggle("Auto-refresh every 30s", value=False, key="overview_auto")
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(interval=AUTO_REFRESH_MS, key="overview_autorefresh")
        except ImportError:
            st.caption("Install `streamlit-autorefresh` to enable this.")
    if st.button("🔄 Refresh now", use_container_width=True):
        st.rerun()

client = get_client()

# --------------------------------------------------------------------- #
# System-wide KPIs (instructor/admin only per API-SPECIFICATION.md)
# --------------------------------------------------------------------- #
overview = None
if current_role() in ("instructor", "admin"):
    overview = safe_call(client.get, "/stats/overview", params={"days": 7}, error_prefix="Could not load overview stats")
else:
    st.info(
        "System-wide stats require the instructor or admin role. As a TA, head to "
        "**Sessions** to view attendance for the sessions you help run."
    )

if overview:
    row1 = st.columns(4)
    row1[0].metric("Total sessions", pick(overview, "total_sessions", default="—"))
    row1[1].metric("Active sessions", pick(overview, "active_sessions", default="—"))
    row1[2].metric("Check-ins (7d)", pick(overview, "total_checkins_week", default="—"))
    row1[3].metric("Avg attendance", f"{overview['average_attendance_rate'] * 100:.1f}%" if overview.get("average_attendance_rate") is not None else "—")

    row2 = st.columns(4)
    checkins_today = pick(overview, "today_checkins", "total_checkins_today")
    row2[0].metric("Check-ins today", checkins_today if checkins_today is not None else "—")
    approval_rate = pick(overview, "approval_rate")
    row2[1].metric("Approval rate", f"{approval_rate * 100:.1f}%" if approval_rate is not None else "—")
    flagged = pick(overview, "flagged_pending", "flagged_pending_review")
    row2[2].metric("Flagged, pending review", flagged if flagged is not None else "—")
    avg_risk = pick(overview, "average_risk_score")
    row2[3].metric(
        "Avg risk score",
        f"{avg_risk:.2f}" if avg_risk is not None else "—",
        help="0 = low risk, 1 = high risk",
    )

    # These extra fields appear in some backends' richer implementations but
    # aren't required by tests/public/test_observability.py - shown only if present.
    checkins_week = pick(overview, "total_checkins_week")
    avg_attendance = pick(overview, "average_attendance_rate")
    if checkins_week is not None or avg_attendance is not None:
        row3 = st.columns(4)
        if checkins_week is not None:
            row3[0].metric("Check-ins (7d, confirmed)", checkins_week)
        if avg_attendance is not None:
            row3[1].metric("Average attendance rate", f"{avg_attendance * 100:.1f}%")

    high_risk_today = pick(overview, "high_risk_checkins_today")
    if high_risk_today:
        st.warning(f"⚠️ {high_risk_today} high-risk check-in(s) today — worth a look in the flagged queue.")

    st.divider()

    trends = overview.get("trends") or {}
    tcol1, tcol2 = st.columns(2)

    by_day = trends.get("checkins_by_day") or []
    if by_day:
        df = pd.DataFrame(by_day)
        fig = px.bar(df, x="date", y="count", title="Check-ins per day")
        fig.update_yaxes(rangemode="tozero")
        tcol1.plotly_chart(fig, use_container_width=True)
    else:
        tcol1.caption("No daily check-in trend data returned by the backend yet.")

    rate_by_day = trends.get("attendance_rate_by_day") or []
    if rate_by_day:
        df = pd.DataFrame(rate_by_day)
        fig = px.line(df, x="date", y="rate", title="Attendance rate per day", markers=True)
        fig.update_yaxes(rangemode="tozero", tickformat=".0%", range=[0, 1])
        tcol2.plotly_chart(fig, use_container_width=True)
    else:
        tcol2.caption("No daily attendance-rate trend data returned by the backend yet.")

st.divider()

# --------------------------------------------------------------------- #
# Recent check-in activity (works for TA too - session-scoped endpoints)
# --------------------------------------------------------------------- #
st.subheader("Recent check-ins")
if current_role() == "ta":
    st.info("TA access is scoped to assigned sessions. Open Sessions → Session detail to view their check-ins.")
    recent = []
else:
    recent = safe_call(
        client.get, "/checkins/", params={"limit": 25, "offset": 0},
        error_prefix="Could not load recent check-ins",
    )
items = safe_items(recent)

if items:
    df = pd.DataFrame(items)
    display_cols = [c for c in [
        "checked_in_at", "student_name", "student_email", "session_name",
        "status", "risk_score", "distance_from_venue_meters", "liveness_passed",
    ] if c in df.columns]
    view = df[display_cols].copy()
    if "checked_in_at" in view:
        view["checked_in_at"] = view["checked_in_at"].apply(fmt_dt)
    if "status" in view:
        view["status"] = view["status"].apply(status_badge)
    if "risk_score" in view:
        view["risk_score"] = view["risk_score"].apply(risk_badge)
    st.dataframe(view, use_container_width=True, hide_index=True)

    if "status" in df.columns:
        counts = df["status"].value_counts().reset_index()
        counts.columns = ["status", "count"]
        fig = px.pie(counts, names="status", values="count", hole=0.45, title="Status mix (most recent 25)")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("No check-ins recorded yet.")
