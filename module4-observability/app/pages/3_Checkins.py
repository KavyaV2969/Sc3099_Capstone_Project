import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

from auth import require_role, sidebar_user_box, get_client, current_role
from api_client import safe_call, fetch_all
from utils import (fmt_dt, risk_badge, status_badge, safe_items, safe_total, pagination_controls, download_csv_button,
                   has_value, render_risk_factors, flash, show_flash, reset_offset_on_change, signal_columns,
                   df_to_csv_bytes)
from config import AUTO_REFRESH_MS, CHECKIN_EXPORT_CAP

st.set_page_config(page_title="Check-ins · SAIV Dashboard", page_icon="✅", layout="wide")
require_role("instructor", "ta", "admin")
sidebar_user_box()

st.title("✅ Check-ins")
client = get_client()

with st.sidebar:
    st.markdown("### Live updates")
    if st.toggle("Auto-refresh every 30s", value=False, key="checkins_auto"):
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(interval=AUTO_REFRESH_MS, key="checkins_autorefresh")
        except ImportError:
            st.caption("Install `streamlit-autorefresh` to enable this.")

tab_all, tab_flagged = st.tabs(["All check-ins", "🚩 Flagged / appealed queue"])

# ======================================================================= #
# All check-ins - filterable, paginated
# ======================================================================= #
with tab_all:
    if "checkins_offset" not in st.session_state:
        st.session_state.checkins_offset = 0

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        session_id = c1.text_input("Session ID", key="ci_session_f")
        course_id = c2.text_input("Course ID", key="ci_course_f")
        student_id = c3.text_input("Student ID", key="ci_student_f")
        status = c4.selectbox(
            "Status", ["(any)", "pending", "approved", "flagged", "rejected", "appealed"], key="ci_status_f"
        )
        c5, c6, c7 = st.columns(3)
        min_risk = c5.slider("Min risk score", 0.0, 1.0, 0.0, 0.05, key="ci_min_risk")
        max_risk = c6.slider("Max risk score", 0.0, 1.0, 1.0, 0.05, key="ci_max_risk")
        limit = c7.selectbox("Page size", [10, 25, 50, 100], index=1, key="ci_limit")

    filter_sig = (session_id.strip(), course_id.strip(), student_id.strip(), status, min_risk, max_risk, limit)
    reset_offset_on_change("checkins_offset", filter_sig)
    params = {"limit": limit, "offset": st.session_state.checkins_offset}
    if session_id.strip():
        params["session_id"] = session_id.strip()
    if course_id.strip():
        params["course_id"] = course_id.strip()
    if student_id.strip():
        params["student_id"] = student_id.strip()
    if status != "(any)":
        params["status"] = status
    if min_risk > 0:
        params["min_risk_score"] = min_risk
    if max_risk < 1:
        params["max_risk_score"] = max_risk

    if current_role() == "ta":
        st.info("TA view: select an assigned session. Global check-in access is restricted.")
        assigned = safe_call(client.get, "/sessions/my-sessions", params={"limit": 200},
                             error_prefix="Could not load assigned sessions")
        if assigned is None:
            result = None
        else:
            assigned = safe_items(assigned)
            if not assigned:
                st.caption("You have no assigned sessions yet.")
                result = {"items": [], "total": 0}
            else:
                labels = {f"{session.get('course_code', '?')} — {session.get('name')} [{session.get('status')}]": session["id"]
                          for session in assigned}
                selected_session = st.selectbox("Assigned session", list(labels), key="ta_ci_session")
                reset_offset_on_change("checkins_offset", labels[selected_session], name="ta_session")
                scoped, _ = fetch_all(client, f"/checkins/session/{labels[selected_session]}",
                                      error_prefix="Could not load assigned session check-ins")
                if scoped is None:
                    result = None
                else:
                    if status != "(any)":
                        scoped = [x for x in scoped if x.get("status") == status]
                    if student_id.strip():
                        scoped = [x for x in scoped if x.get("student_id") == student_id.strip()]
                    scoped = [x for x in scoped if min_risk <= float(x.get("risk_score") or 0) <= max_risk]
                    total_count = len(scoped)
                    result = {"items": scoped[st.session_state.checkins_offset:st.session_state.checkins_offset + limit],
                              "total": total_count}
        st.caption("Filters are applied to the selected session. Global course and session ID filters are not used for TA view.")
    else:
        result = safe_call(client.get, "/checkins/", params=params, error_prefix="Could not load check-ins")
    items = safe_items(result)
    total = safe_total(result, fallback=len(items))

    if items:
        df = pd.DataFrame(items)
        cols = [c for c in [
            "checked_in_at", "student_name", "student_email", "session_name",
            "status", "risk_score", "distance_from_venue_meters", "liveness_passed", "liveness_score",
            "face_match_passed", "face_match_score", "device_trusted",
        ] if c in df.columns]
        view = signal_columns(df[cols])
        if "checked_in_at" in view:
            view["checked_in_at"] = view["checked_in_at"].apply(fmt_dt)
        if "status" in view:
            view["status"] = view["status"].apply(status_badge)
        if "risk_score" in view:
            view["risk_score"] = view["risk_score"].apply(risk_badge)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.session_state.checkins_offset = pagination_controls(
            total, limit, st.session_state.checkins_offset, "ci"
        )
        download_csv_button(df, "checkins.csv", key="all_checkins_csv", signals_option=True)
        if current_role() != "ta" and total > len(items):
            if st.button(f"Prepare export of all {total} matching check-ins", key="ci_full_export"):
                everything, _ = fetch_all(client, "/checkins/", params={k: v for k, v in params.items()
                                                                       if k not in ("limit", "offset")},
                                          cap=CHECKIN_EXPORT_CAP, error_prefix="Could not prepare the export")
                if everything:
                    st.session_state["ci_full_export_bytes"] = df_to_csv_bytes(
                        pd.DataFrame(everything), st.session_state.get("all_checkins_csv_signals", False))
                    st.session_state["ci_full_export_rows"] = len(everything)
            if st.session_state.get("ci_full_export_bytes"):
                st.download_button(
                    f"⬇ Download {st.session_state['ci_full_export_rows']} rows (CSV)",
                    data=st.session_state["ci_full_export_bytes"], file_name="checkins_all.csv",
                    mime="text/csv", key="ci_full_export_dl", use_container_width=True,
                )
    else:
        st.caption("No check-ins match these filters.")

# ======================================================================= #
# Flagged / appealed queue - approve or reject directly
# ======================================================================= #
with tab_flagged:
    st.caption("Check-ins with status `flagged` or `appealed` — review and resolve them here.")
    fc1, fc2 = st.columns(2)
    course_f = fc1.text_input("Course ID (optional)", key="flag_course_f")
    session_f = fc2.text_input("Session ID (optional)", key="flag_session_f")

    params = {}
    if course_f.strip():
        params["course_id"] = course_f.strip()
    if session_f.strip():
        params["session_id"] = session_f.strip()

    flagged_items, flagged_total = fetch_all(
        client, "/checkins/flagged", params=params, error_prefix="Could not load flagged queue"
    )
    flagged = flagged_items

    if flagged is None:
        st.warning("Could not load the review queue. Please retry; no empty-queue assertion can be made.")
    elif not flagged_items:
        st.success("🎉 Nothing needs review right now.")
    else:
        st.write(f"**{flagged_total}** check-in(s) awaiting review.")
        if flagged_total > len(flagged_items):
            st.warning(f"Showing the first {len(flagged_items)}; resolve some to reveal the rest.")
        for item in flagged_items:
            title = f"{item.get('student_name', item.get('student_id'))} · {item.get('session_name', '')} · risk {item.get('risk_score')}"
            with st.expander(title):
                left, right = st.columns([2, 1])
                with left:
                    st.write(f"Status: {status_badge(item.get('status'))}")
                    st.write(f"Checked in: {fmt_dt(item.get('checked_in_at'))}")
                    signal_bits = []
                    if item.get("distance_from_venue_meters") is not None:
                        signal_bits.append(f"{item['distance_from_venue_meters']:.0f} m from venue")
                    if item.get("liveness_score") is not None:
                        signal_bits.append(f"liveness {item['liveness_score']:.2f}")
                    if item.get("face_match_score") is not None:
                        signal_bits.append(f"face match {item['face_match_score']:.2f}")
                    if item.get("device_trusted") is not None:
                        signal_bits.append("trusted device" if item["device_trusted"] else "untrusted device")
                    if signal_bits:
                        st.caption(" · ".join(signal_bits))
                    if item.get("appeal_reason"):
                        st.info(f"Student's appeal: {item['appeal_reason']}")
                    if has_value(item.get("risk_factors")):
                        render_risk_factors(item["risk_factors"])
                with right:
                    notes = st.text_area("Review notes", key=f"fq_notes_{item.get('id')}")
                    if st.button("✅ Approve", key=f"fq_approve_{item.get('id')}", use_container_width=True):
                        if not notes.strip():
                            st.error("Review notes are required.")
                        elif safe_call(
                            client.post, f"/checkins/{item['id']}/review",
                            json={"status": "approved", "review_notes": notes},
                        ):
                            flash("Approved.", "success")
                            st.rerun()
                    if st.button("⛔ Reject", key=f"fq_reject_{item.get('id')}", use_container_width=True):
                        if not notes.strip():
                            st.error("Review notes are required.")
                        elif safe_call(
                            client.post, f"/checkins/{item['id']}/review",
                            json={"status": "rejected", "review_notes": notes},
                        ):
                            flash("Rejected.", "warning")
                            st.rerun()

show_flash()
