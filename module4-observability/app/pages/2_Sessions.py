import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, current_role, current_user, get_client
from api_client import safe_call
from utils import (
    fmt_dt, risk_badge, status_badge, safe_items, safe_total,
    pagination_controls, download_csv_button, pick,
)

st.set_page_config(page_title="Sessions · SAIV Dashboard", page_icon="🗓️", layout="wide")
require_role("instructor", "ta", "admin")
sidebar_user_box()

st.title("🗓️ Sessions")
client = get_client()

if "sessions_offset" not in st.session_state:
    st.session_state.sessions_offset = 0

tab_list, tab_create, tab_detail = st.tabs(["All sessions", "Create session", "Session detail & review"])

# ======================================================================= #
# Tab 1 - list + filter
# ======================================================================= #
with tab_list:
    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        status_filter = c1.selectbox(
            "Status", ["(any)", "scheduled", "active", "closed", "cancelled"], key="sess_status_f"
        )
        course_filter = c2.text_input("Course ID (uuid, optional)", key="sess_course_f")
        limit = c3.selectbox("Page size", [10, 25, 50, 100], index=1, key="sess_limit_f")

    params = {"limit": limit, "offset": st.session_state.sessions_offset}
    if status_filter != "(any)":
        params["status"] = status_filter
    if course_filter.strip():
        params["course_id"] = course_filter.strip()

    if current_role() == "ta":
        result = safe_call(client.get, "/sessions/my-sessions", params={"limit": 200}, error_prefix="Could not load assigned sessions")
        if result is not None:
            result = [s for s in result if (status_filter == "(any)" or s.get("status") == status_filter)
                      and (not course_filter.strip() or s.get("course_id") == course_filter.strip())]
            result = {"items": result[st.session_state.sessions_offset:st.session_state.sessions_offset + limit],
                      "total": len(result)}
    else:
        result = safe_call(client.get, "/sessions/", params=params, error_prefix="Could not load sessions")
    items = safe_items(result)
    total = safe_total(result, fallback=len(items))

    if items:
        df = pd.DataFrame(items)
        cols = [c for c in [
            "name", "course_code", "session_type", "status", "scheduled_start",
            "scheduled_end", "total_enrolled", "checked_in_count",
        ] if c in df.columns]
        view = df[cols].copy()
        for c in ("scheduled_start", "scheduled_end"):
            if c in view:
                view[c] = view[c].apply(fmt_dt)
        if "status" in view:
            view["status"] = view["status"].apply(status_badge)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.session_state.sessions_offset = pagination_controls(total, limit, st.session_state.sessions_offset, "sess")
        download_csv_button(df, "sessions.csv", key="sessions_csv")
    else:
        st.caption("No sessions match these filters yet.")

# ======================================================================= #
# Tab 2 - create a session (instructor/admin only per API spec)
# ======================================================================= #
with tab_create:
    if current_role() not in ("instructor", "admin"):
        st.info("Only instructors and admins can create sessions. TAs can review check-ins on the other tabs.")
    else:
        courses_resp = safe_call(client.get, "/courses/", params={"limit": 100}, error_prefix="Could not load courses")
        courses = [course for course in safe_items(courses_resp)
                   if current_role() == "admin" or course.get("instructor_id") in (None, current_user().get("id"))]
        if not courses:
            st.warning("No courses found yet — create a course first on the **Courses** page.")
        else:
            course_lookup = {f"{c['code']} — {c['name']}": c["id"] for c in courses}
            with st.form("create_session_form"):
                course_label = st.selectbox("Course", list(course_lookup.keys()))
                name = st.text_input("Session name", placeholder="Lecture 5: Neural Networks")
                session_type = st.selectbox("Type", ["lecture", "tutorial", "lab", "exam"])

                now = datetime.now(ZoneInfo("Asia/Singapore"))
                default_start = (now + timedelta(days=1)).replace(second=0, microsecond=0)
                default_end = default_start + timedelta(hours=1)
                st.caption("All dates and times entered below use Singapore Time (SGT, UTC+08:00).")
                c1, c2 = st.columns(2)
                start_date = c1.date_input("Scheduled start date", value=default_start.date())
                start_time = c1.time_input("Scheduled start time", value=default_start.time())
                end_date = c2.date_input("Scheduled end date", value=default_end.date())
                end_time = c2.time_input("Scheduled end time", value=default_end.time())

                c3, c4 = st.columns(2)
                venue_name = c3.text_input("Venue name (optional — defaults to course venue)")
                selected_course = next(c for c in courses if c["id"] == course_lookup[course_label])
                radius = c4.number_input("Geofence radius (meters)", min_value=1.0,
                                          value=float(selected_course.get("geofence_radius_meters") or 100.0), step=10.0)

                c5, c6, c7 = st.columns(3)
                require_liveness = c5.checkbox("Require liveness check", value=True)
                require_face = c6.checkbox("Require face match", value=False)
                risk_threshold = c7.slider("Risk threshold", 0.0, 1.0, 0.5, 0.05)

                override_window = st.checkbox(
                    "Override check-in window (defaults: opens 15 min before start, "
                    "closes 30 min after start — per API-SPECIFICATION.md)"
                )
                co1, co2 = st.columns(2)
                checkin_opens = co1.text_input(
                    "Check-in opens at (ISO8601, e.g. 2026-01-15T13:45:00Z)", disabled=not override_window,
                )
                checkin_closes = co2.text_input(
                    "Check-in closes at (ISO8601)", disabled=not override_window,
                )

                submitted = st.form_submit_button("Create session", type="primary", use_container_width=True)

            if submitted:
                if datetime.combine(end_date, end_time) <= datetime.combine(start_date, start_time):
                    st.error("Session end must be after its start.")
                elif not name.strip():
                    st.error("Please give the session a name.")
                else:
                    payload = {
                        "course_id": course_lookup[course_label],
                        "name": name.strip(),
                        "session_type": session_type,
                        "scheduled_start": datetime.combine(start_date, start_time, tzinfo=ZoneInfo("Asia/Singapore")).isoformat(),
                        "scheduled_end": datetime.combine(end_date, end_time, tzinfo=ZoneInfo("Asia/Singapore")).isoformat(),
                        "geofence_radius_meters": radius,
                        "require_liveness_check": require_liveness,
                        "require_face_match": require_face,
                        "risk_threshold": risk_threshold,
                    }
                    if venue_name.strip():
                        payload["venue_name"] = venue_name.strip()
                    if override_window and checkin_opens.strip():
                        payload["checkin_opens_at"] = checkin_opens.strip()
                    if override_window and checkin_closes.strip():
                        payload["checkin_closes_at"] = checkin_closes.strip()

                    created = safe_call(client.post, "/sessions/", json=payload, error_prefix="Could not create session")
                    if created:
                        st.success(f"Session '{created.get('name')}' created with status `{created.get('status')}`.")

# ======================================================================= #
# Tab 3 - drill into one session: stats, status control, check-ins, review
# ======================================================================= #
with tab_detail:
    if current_role() == "ta":
        all_sessions_resp = safe_call(client.get, "/sessions/my-sessions", params={"limit": 200}, error_prefix="Could not load assigned sessions")
    else:
        all_sessions_resp = safe_call(client.get, "/sessions/", params={"limit": 200}, error_prefix="Could not load sessions")
    all_sessions = safe_items(all_sessions_resp)

    if not all_sessions:
        st.caption("No sessions available yet.")
    else:
        label_to_id = {
            f"{s.get('course_code', '?')} — {s.get('name')} ({s.get('status')})": s["id"] for s in all_sessions
        }
        chosen_label = st.selectbox("Select a session", list(label_to_id.keys()), key="sess_detail_pick")
        session_id = label_to_id[chosen_label]

        detail = safe_call(client.get, f"/sessions/{session_id}", error_prefix="Could not load session detail")

        if detail:
            info_cols = st.columns(4)
            info_cols[0].metric("Status", detail.get("status", "—"))
            info_cols[1].metric("Type", detail.get("session_type", "—"))
            info_cols[2].metric("Check-in opens", fmt_dt(detail.get("checkin_opens_at")))
            info_cols[3].metric("Check-in closes", fmt_dt(detail.get("checkin_closes_at")))

            if current_role() in ("instructor", "admin"):
                st.markdown("**Session controls**")
                b1, b2, b3, b4 = st.columns(4)
                status = detail.get("status")
                if b1.button("▶ Activate", disabled=status != "scheduled", use_container_width=True):
                    if safe_call(client.patch, f"/sessions/{session_id}", json={"status": "active"}):
                        st.success("Session activated. Students can check in during the configured window.")
                        st.rerun()
                if b2.button("⏹ Close", disabled=status != "active", use_container_width=True):
                    if safe_call(client.patch, f"/sessions/{session_id}", json={"status": "closed"}):
                        st.success("Session closed.")
                        st.rerun()
                if b3.button("🚫 Cancel", disabled=status in ("closed", "cancelled"), use_container_width=True):
                    if safe_call(client.patch, f"/sessions/{session_id}", json={"status": "cancelled"}):
                        st.warning("Session cancelled.")
                        st.rerun()
                with b4.popover("✏️ Rename"):
                    new_name = st.text_input("New name", value=detail.get("name", ""), key="rename_input")
                    if st.button("Save", key="rename_save"):
                        if safe_call(client.patch, f"/sessions/{session_id}", json={"name": new_name}):
                            st.success("Renamed.")
                            st.rerun()

            st.divider()

            # ---- Session stats ----
            stats = safe_call(client.get, f"/stats/sessions/{session_id}", error_prefix="Could not load session stats")
            if stats:
                st.subheader("Attendance")
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Enrolled", pick(stats, "total_enrolled", default="—"))
                checked_in = pick(stats, "checked_in_count", "checked_in")
                s2.metric("Checked in", checked_in if checked_in is not None else "—")
                rate = pick(stats, "attendance_rate")
                s3.metric("Attendance rate", f"{rate * 100:.1f}%" if rate is not None else "—")
                avg_risk = pick(stats, "average_risk_score")
                s4.metric("Avg risk score", f"{avg_risk:.2f}" if avg_risk is not None else "—")

                approved_count = pick(stats, "approved_count", default=(stats.get("by_status") or {}).get("approved"))
                flagged_count = pick(stats, "flagged_count", default=(stats.get("by_status") or {}).get("flagged"))
                avg_dist = pick(stats, "average_distance_meters")
                avg_time = pick(stats, "average_checkin_time_minutes")
                if any(v is not None for v in (approved_count, flagged_count, avg_dist, avg_time)):
                    s5, s6, s7, s8 = st.columns(4)
                    if approved_count is not None:
                        s5.metric("Approved", approved_count)
                    if flagged_count is not None:
                        s6.metric("Flagged", flagged_count)
                    if avg_dist is not None:
                        s7.metric("Avg distance from venue", f"{avg_dist:.0f} m")
                    if avg_time is not None:
                        s8.metric("Avg time to check in", f"{avg_time:.1f} min")

                by_status = stats.get("by_status") or {}
                if not by_status and (approved_count is not None or flagged_count is not None):
                    # Backend didn't provide a full breakdown, but did give us
                    # the two counts tests/public/test_observability.py requires -
                    # build a minimal chart from those instead of showing nothing.
                    by_status = {k: v for k, v in {
                        "approved": approved_count, "flagged": flagged_count,
                    }.items() if v is not None}
                risk_dist = stats.get("risk_distribution") or {}
                timeline = stats.get("checkin_timeline") or []

                cc1, cc2, cc3 = st.columns(3)
                if by_status:
                    df_status = pd.DataFrame({"status": list(by_status.keys()), "count": list(by_status.values())})
                    fig = px.pie(df_status, names="status", values="count", title="By status", hole=0.4)
                    cc1.plotly_chart(fig, use_container_width=True)
                if risk_dist:
                    df_risk = pd.DataFrame({"level": list(risk_dist.keys()), "count": list(risk_dist.values())})
                    fig = px.bar(df_risk, x="level", y="count", title="Risk distribution",
                                 category_orders={"level": ["low", "medium", "high"]})
                    fig.update_yaxes(rangemode="tozero")
                    cc2.plotly_chart(fig, use_container_width=True)
                if timeline:
                    df_tl = pd.DataFrame(timeline)
                    fig = px.line(df_tl, x="minute", y="count", markers=True,
                                  title="Check-ins over time (minutes relative to session start)")
                    fig.update_yaxes(rangemode="tozero")
                    cc3.plotly_chart(fig, use_container_width=True)

            st.divider()

            # ---- Check-ins for this session + review ----
            st.subheader("Check-ins for this session")
            checkins = safe_call(
                client.get, f"/checkins/session/{session_id}", error_prefix="Could not load session check-ins"
            )
            checkins = safe_items(checkins) if isinstance(checkins, dict) else (checkins or [])

            if checkins:
                df = pd.DataFrame(checkins)
                show_cols = [c for c in [
                    "student_name", "student_email", "status", "checked_in_at",
                    "distance_from_venue_meters", "risk_score", "liveness_passed", "device_trusted",
                ] if c in df.columns]
                view = df[show_cols].copy()
                if "checked_in_at" in view:
                    view["checked_in_at"] = view["checked_in_at"].apply(fmt_dt)
                if "status" in view:
                    view["status"] = view["status"].apply(status_badge)
                if "risk_score" in view:
                    view["risk_score"] = view["risk_score"].apply(risk_badge)
                st.dataframe(view, use_container_width=True, hide_index=True)

                export_c1, export_c2, export_c3 = st.columns([1, 1, 1])
                with export_c1:
                    download_csv_button(df, f"session_{session_id}_checkins.csv", key="session_checkins_csv")
                with export_c2:
                    export_fmt = st.radio(
                        "Official export format", ["csv", "json"], horizontal=True, key="session_export_fmt"
                    )
                with export_c3:
                    if current_role() == "ta":
                        st.caption("Official gradebook exports require instructor/admin access.")
                    elif st.button("Generate official export", key="session_export_btn", use_container_width=True):
                        resp = safe_call(
                            client.get_raw, f"/export/session/{session_id}", params={"format": export_fmt},
                            error_prefix="Server-side export failed",
                        )
                        if resp is not None:
                            st.session_state["session_export_ready"] = {
                                "session_id": session_id, "format": export_fmt, "bytes": resp.content
                            }
                    prepared = st.session_state.get("session_export_ready")
                    if (current_role() in ("instructor", "admin") and prepared
                            and prepared["session_id"] == session_id and prepared["format"] == export_fmt):
                        st.download_button(
                            f"⬇ Download official {export_fmt.upper()} export",
                            data=prepared["bytes"],
                            file_name=f"session_{session_id}_export.{export_fmt}",
                            mime="text/csv" if export_fmt == "csv" else "application/json",
                            use_container_width=True, key="official_export_dl",
                        )

                needs_review = df[df["status"].isin(["flagged", "appealed"])] if "status" in df.columns else pd.DataFrame()
                if not needs_review.empty and current_role() in ("instructor", "ta", "admin"):
                    st.subheader("🚩 Needs review")
                    for _, row in needs_review.iterrows():
                        with st.expander(f"{row.get('student_name', row.get('student_id'))} — risk {row.get('risk_score')}"):
                            st.write(f"Status: {row.get('status')} · Checked in: {fmt_dt(row.get('checked_in_at'))}")
                            if row.get("risk_factors"):
                                st.json(row["risk_factors"])
                            notes = st.text_area("Review notes", key=f"notes_{row.get('id')}")
                            ra, rb = st.columns(2)
                            if ra.button("✅ Approve", key=f"approve_{row.get('id')}", use_container_width=True):
                                if not notes.strip():
                                    st.error("Review notes are required (minimum 1 character).")
                                elif safe_call(
                                    client.post, f"/checkins/{row['id']}/review",
                                    json={"status": "approved", "review_notes": notes},
                                ):
                                    st.success("Approved.")
                                    st.rerun()
                            if rb.button("⛔ Reject", key=f"reject_{row.get('id')}", use_container_width=True):
                                if not notes.strip():
                                    st.error("Review notes are required (minimum 1 character).")
                                elif safe_call(
                                    client.post, f"/checkins/{row['id']}/review",
                                    json={"status": "rejected", "review_notes": notes},
                                ):
                                    st.warning("Rejected.")
                                    st.rerun()
            else:
                st.caption("No check-ins recorded for this session yet.")
