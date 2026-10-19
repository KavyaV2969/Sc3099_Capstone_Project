import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, get_client
from api_client import safe_call
from utils import fmt_dt, safe_items, safe_total, pagination_controls, download_csv_button, pick

st.set_page_config(page_title="Audit Logs · SAIV Dashboard", page_icon="📜", layout="wide")
require_role("admin")
sidebar_user_box()

st.title("📜 Audit Logs")
st.caption("Immutable security & compliance trail. Admin-only, per docs/SECURITY-REQUIREMENTS.md.")
client = get_client()

ACTIONS = [
    "(any)", "login_success", "login_failed", "logout", "user_created", "user_updated",
    "checkin_attempted", "checkin_approved", "checkin_flagged", "checkin_rejected",
    "checkin_appealed", "checkin_reviewed", "session_created", "session_updated",
    "session_deleted", "enrollment_added", "enrollment_removed", "device_registered",
    "face_enrolled", "security_violation", "data_exported",
]
# Actions worth calling out visually as higher-severity when they occur / fail.
HIGH_SEVERITY_ACTIONS = {"login_failed", "security_violation", "checkin_rejected"}

tab_logs, tab_summary = st.tabs(["Log explorer", "Summary"])

with tab_logs:
    if "audit_offset" not in st.session_state:
        st.session_state.audit_offset = 0

    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        user_id = c1.text_input("User ID", key="audit_user_f")
        action = c2.selectbox("Action", ACTIONS, key="audit_action_f")
        resource_type = c3.selectbox(
            "Resource type", ["(any)", "user", "session", "checkin", "course", "enrollment", "device"],
            key="audit_resource_f",
        )
        c4, c5, c6 = st.columns(3)
        resource_id = c4.text_input("Resource ID", key="audit_resource_id_f")
        success = c5.selectbox("Success", ["(any)", "true", "false"], key="audit_success_f")
        limit = c6.selectbox("Page size", [25, 50, 100, 200], index=1, key="audit_limit_f")

        use_date_range = st.checkbox("Filter by date range", key="audit_use_dates_f")
        start_date_val = end_date_val = None
        if use_date_range:
            c7, c8 = st.columns(2)
            start_date_val = c7.date_input("Start date", key="audit_start_f")
            end_date_val = c8.date_input("End date", key="audit_end_f")

    params = {"limit": limit, "offset": st.session_state.audit_offset}
    if user_id.strip():
        params["user_id"] = user_id.strip()
    if action != "(any)":
        params["action"] = action
    if resource_type != "(any)":
        params["resource_type"] = resource_type
    if resource_id.strip():
        params["resource_id"] = resource_id.strip()
    if use_date_range and start_date_val:
        params["start_date"] = start_date_val.isoformat()
    if use_date_range and end_date_val:
        params["end_date"] = end_date_val.isoformat()
    if success != "(any)":
        params["success"] = success == "true"

    result = safe_call(client.get, "/audit/", params=params, error_prefix="Could not load audit logs")
    items = safe_items(result)
    total = safe_total(result, fallback=len(items))

    if items:
        df = pd.DataFrame(items)

        # tests/public/test_privacy_basic.py explicitly accepts either field
        # name for the log timestamp - normalize to "timestamp" for display.
        if "timestamp" not in df.columns and "created_at" in df.columns:
            df["timestamp"] = df["created_at"]

        def _severity(row):
            if row.get("success") is False:
                return "🔴 failed"
            if row.get("action") in HIGH_SEVERITY_ACTIONS:
                return "🟠 notable"
            return "🟢 normal"

        df["severity"] = df.apply(_severity, axis=1)
        cols = [c for c in [
            "timestamp", "severity", "user_email", "action", "resource_type",
            "resource_id", "ip_address", "success",
        ] if c in df.columns]
        view = df[cols].copy()
        if "timestamp" in view:
            view["timestamp"] = view["timestamp"].apply(fmt_dt)
        st.dataframe(view, use_container_width=True, hide_index=True)

        with st.expander("Inspect raw `details` for a log entry"):
            options = {
                f"{pick(r, 'timestamp', 'created_at')} · {r.get('action')} · {r.get('id')}": r
                for r in items
            }
            if options:
                chosen_label = st.selectbox("Entry", list(options.keys()))
                st.json(options[chosen_label].get("details") or {})

        st.session_state.audit_offset = pagination_controls(total, limit, st.session_state.audit_offset, "audit")
        download_csv_button(df, "audit_logs.csv", key="audit_csv")
    else:
        st.caption("No audit logs match these filters.")

with tab_summary:
    from datetime import datetime, timedelta, timezone

    days = st.slider("Look back (days)", 1, 90, 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    summary_data = safe_call(client.get, "/audit/", params={"start_date": cutoff, "limit": 1000},
                             error_prefix="Could not load recent audit events")
    if summary_data is not None:
        sample = safe_items(summary_data)
        total = safe_total(summary_data, fallback=len(sample))
        st.metric("Events in selected period", total)
        if total > len(sample):
            st.warning(f"Only the latest {len(sample)} of {total} events are included in this breakdown; use Log explorer for pagination.")
        if sample:
            counts = pd.Series([event.get("action", "unknown") for event in sample]).value_counts()
            df = counts.rename_axis("action").reset_index(name="count")
            fig = px.bar(df, x="action", y="count", title=f"Recent audit events by action — {days} days")
            fig.update_yaxes(rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No audit events in this period.")
