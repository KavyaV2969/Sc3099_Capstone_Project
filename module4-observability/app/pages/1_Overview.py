import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, current_role, get_client
from api_client import safe_call, fetch_all
from alerts import render_flagged_alert, render_failed_login_alert
from utils import (
    risk_badge, status_badge, fmt_dt, safe_items, safe_total, pick, sgt_day_bounds,
    checkins_by_hour, status_counts, signal_columns,
)
from config import AUTO_REFRESH_MS, STATUS_COLORS

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

today_items = []
if overview:
    today_start, today_end = sgt_day_bounds()
    today_items, _ = fetch_all(
        client, "/checkins/",
        params={"start_date": today_start.isoformat(), "end_date": today_end.isoformat()},
        cap=2000, error_prefix="Could not load today's check-ins",
    )
    today_items = today_items or []
    sessions_today = safe_call(
        client.get, "/sessions/",
        params={"start_date": today_start.isoformat(), "end_date": today_end.isoformat(), "limit": 1},
        error_prefix="Could not load today's sessions",
    )

    row1 = st.columns(4)
    row1[0].metric("Sessions today", safe_total(sessions_today, fallback=0) if sessions_today is not None else "—")
    checkins_today = pick(overview, "today_checkins", "total_checkins_today")
    row1[1].metric("Check-ins today", checkins_today if checkins_today is not None else "—")
    flagged = pick(overview, "flagged_pending", "flagged_pending_review")
    row1[2].metric("Flagged, pending review", flagged if flagged is not None else "—")
    approval_rate = pick(overview, "approval_rate")
    row1[3].metric("Approval rate", f"{approval_rate * 100:.1f}%" if approval_rate is not None else "—")

    row2 = st.columns(4)
    active = pick(overview, "active_sessions", default="—")
    total_sessions = pick(overview, "total_sessions", default="—")
    row2[0].metric("Active / total sessions", f"{active} / {total_sessions}")
    row2[1].metric("Check-ins (7d)", pick(overview, "total_checkins_week", default="—"))
    avg_attendance = pick(overview, "average_attendance_rate")
    row2[2].metric("Avg attendance", f"{avg_attendance * 100:.1f}%" if avg_attendance is not None else "—")
    avg_risk = pick(overview, "average_risk_score")
    row2[3].metric(
        "Avg risk score",
        f"{avg_risk:.2f}" if avg_risk is not None else "—",
        help="0 = low risk, 1 = high risk",
    )

    high_risk_today = pick(overview, "high_risk_checkins_today")
    if high_risk_today:
        st.warning(f"⚠️ {high_risk_today} high-risk check-in(s) today — worth a look in the flagged queue.")
    render_flagged_alert(today_items)
    if current_role() == "admin":
        render_failed_login_alert(client)

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

    hcol1, hcol2 = st.columns(2)
    if today_items:
        hourly = checkins_by_hour(today_items)
        fig = px.bar(hourly, x="label", y="count", title="Check-ins by hour (today, SGT)",
                     labels={"label": "Hour", "count": "Check-ins"})
        fig.update_yaxes(rangemode="tozero")
        hcol1.plotly_chart(fig, use_container_width=True)
        fig = px.pie(status_counts(today_items), names="status", values="count", hole=0.45,
                     title="Verification status (today)", color="status", color_discrete_map=STATUS_COLORS)
        fig.update_traces(textinfo="percent", textposition="inside")
        fig.update_layout(legend=dict(orientation="h", y=-0.1))
        hcol2.plotly_chart(fig, use_container_width=True)
    else:
        hcol1.caption("No check-ins recorded today yet, so the hourly chart is empty.")
        hcol2.caption("No check-ins recorded today yet, so there is no verification status mix.")

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
        "status", "risk_score", "distance_from_venue_meters", "liveness_passed", "liveness_score",
        "face_match_passed", "face_match_score", "device_trusted",
    ] if c in df.columns]
    view = signal_columns(df[display_cols])
    if "checked_in_at" in view:
        view["checked_in_at"] = view["checked_in_at"].apply(fmt_dt)
    if "status" in view:
        view["status"] = view["status"].apply(status_badge)
    if "risk_score" in view:
        view["risk_score"] = view["risk_score"].apply(risk_badge)
    st.dataframe(view, use_container_width=True, hide_index=True)
else:
    st.caption("No check-ins recorded yet.")
