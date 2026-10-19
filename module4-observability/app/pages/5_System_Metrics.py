import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, current_role, get_client
from api_client import safe_call
from utils import safe_items
from config import AUTO_REFRESH_MS, PROMETHEUS_JOBS, PROMETHEUS_URL
import metrics as prom

st.set_page_config(page_title="System Metrics · SAIV Dashboard", page_icon="📈", layout="wide")
require_role("admin")
sidebar_user_box()

st.title("📈 System Metrics")
st.caption("Technical health (Prometheus) alongside business risk metrics (Backend API).")

with st.sidebar:
    st.markdown("### Live updates")
    if st.toggle("Auto-refresh every 30s", value=False, key="metrics_auto"):
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(interval=AUTO_REFRESH_MS, key="metrics_autorefresh")
        except ImportError:
            st.caption("Install `streamlit-autorefresh` to enable this.")

client = get_client()

# --------------------------------------------------------------------- #
# System health
# --------------------------------------------------------------------- #
st.subheader("Service health")

if not prom.prometheus_reachable():
    st.error(
        f"Could not reach Prometheus at `{PROMETHEUS_URL}`. "
        "Make sure `docker-compose up -d prometheus` is running, or that "
        "PROMETHEUS_URL is set correctly."
    )
else:
    up = prom.targets_up()
    health_cols = st.columns(len(PROMETHEUS_JOBS) + 1)
    for i, (label, job) in enumerate(PROMETHEUS_JOBS.items()):
        instances = up.get(job, [])
        healthy = any(is_up for _, is_up in instances)
        health_cols[i].metric(label, "🟢 Up" if healthy else ("🔴 Down" if instances else "⚪ No data"))
    health_cols[-1].metric("Prometheus", "🟢 Up")

st.divider()

# --------------------------------------------------------------------- #
# Technical metrics per service
# --------------------------------------------------------------------- #
st.subheader("API performance")

job_label = st.selectbox("Service", list(PROMETHEUS_JOBS.keys()), key="metrics_job_pick")
job = PROMETHEUS_JOBS[job_label]

m1, m2, m3 = st.columns(3)
p95 = prom.get_latency_p95_ms(job)
m1.metric("p95 latency", f"{p95:.0f} ms" if p95 is not None else "no data")
rate = prom.get_request_rate(job)
m2.metric("Request rate", f"{rate:.2f} req/s" if rate is not None else "no data")
err = prom.get_error_rate_pct(job)
m3.metric("5xx error rate", f"{err:.2f}%" if err is not None else "no data")

if p95 is None and rate is None and err is None:
    with st.expander("Why is this all 'no data'?"):
        st.markdown(
            f"""
This page queries Prometheus for metrics named in
`docs/recommended_design/INTEGRATION-GUIDE.md`:

- `http_request_duration_seconds_bucket{{job="{job}"}}`
- `http_requests_total{{job="{job}"}}`

If your backend teammate instruments the service with different metric
names, update the constants at the top of `app/config.py`
(`METRIC_HTTP_DURATION_BUCKET`, `METRIC_HTTP_REQUESTS_TOTAL`) to match —
nothing else on this page needs to change.
            """
        )

ts, ys = prom.get_request_rate_series(job, minutes=30)
if ts:
    df = pd.DataFrame({"time": [datetime.fromtimestamp(t) for t in ts], "requests_per_sec": ys})
    fig = px.line(df, x="time", y="requests_per_sec", title=f"Request rate — last 30 min ({job_label})")
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# --------------------------------------------------------------------- #
# Business metrics: risk distribution & high-risk alerts (from backend)
# --------------------------------------------------------------------- #
st.subheader("Risk & attendance signals")

if current_role() in ("instructor", "admin"):
    overview = safe_call(client.get, "/stats/overview", error_prefix="Could not load overview stats")
    if overview:
        c1, c2, c3 = st.columns(3)
        avg_risk = overview.get("average_risk_score")
        c1.metric("Average risk score", f"{avg_risk:.2f}" if avg_risk is not None else "—")
        c2.metric("High-risk check-ins today", overview.get("high_risk_checkins_today", "—"))
        checkin_success = prom.get_checkin_success_rate_pct()
        c3.metric(
            "Check-in success rate (Prometheus)",
            f"{checkin_success:.1f}%" if checkin_success is not None else "no data",
        )
else:
    st.info("Risk score aggregates require the instructor or admin role.")

recent = (safe_call(client.get, "/checkins/", params={"limit": 100}, error_prefix="Could not sample recent check-ins")
          if current_role() in ("instructor", "admin") else [])
items = safe_items(recent)
if items:
    df = pd.DataFrame(items)
    if "risk_score" in df.columns:
        fig = px.histogram(
            df, x="risk_score", nbins=20,
            title="Risk score distribution — most recent 100 check-ins",
        )
        fig.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)
