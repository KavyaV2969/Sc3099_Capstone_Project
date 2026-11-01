import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import require_role, sidebar_user_box, current_role, get_client
from api_client import safe_call
from form_helpers import clicked_coordinates, current_semester, semester_options
from utils import safe_items, download_csv_button, pick

st.set_page_config(page_title="Courses · SAIV Dashboard", page_icon="🎓", layout="wide")
require_role("instructor", "ta", "admin")
sidebar_user_box()

st.title("🎓 Courses")
client = get_client()

tab_browse, tab_create, tab_stats = st.tabs(["Browse", "Create / edit course", "Course analytics"])

# ======================================================================= #
with tab_browse:
    courses_resp = safe_call(client.get, "/courses/", params={"limit": 100}, error_prefix="Could not load courses")
    courses = safe_items(courses_resp)
    if courses:
        df = pd.DataFrame(courses)
        cols = [c for c in [
            "code", "name", "semester", "instructor_name", "venue_name",
            "geofence_radius_meters", "risk_threshold", "is_active",
        ] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
    else:
        st.caption("No courses yet — create one in the next tab.")

# ======================================================================= #
with tab_create:
    if current_role() != "admin":
        st.info(
            "Only administrators can create or edit courses in the current backend."
        )
    else:
        # The map sends clicks to Python immediately, so this creation section
        # must not be enclosed in a form (which batches widget updates).
        with st.container(border=True):
            c1, c2 = st.columns(2)
            code = c1.text_input("Course code", placeholder="CS6101")
            name = c2.text_input("Course name", placeholder="Advanced Topics in CS")
            today_sgt = datetime.now(ZoneInfo("Asia/Singapore")).date()
            available_semesters = semester_options(today_sgt)
            semester_choice = st.selectbox("Semester", available_semesters + ["Other / custom semester"],
                                           index=available_semesters.index(current_semester(today_sgt)))
            semester = (st.text_input("Custom semester", max_chars=20, placeholder="AY2025-26 ST 1")
                        if semester_choice == "Other / custom semester" else semester_choice)

            venue_name = st.text_input("Venue name", placeholder="LT1")
            if "course_venue_lat" not in st.session_state:
                st.session_state["course_venue_lat"] = 1.348300  # NTU default
            if "course_venue_lng" not in st.session_state:
                st.session_state["course_venue_lng"] = 103.683100

            if st.checkbox("🗺️ Choose venue on an interactive map", key="course_pick_map"):
                st.caption("Click the map to place the venue pin. The coordinates below will update automatically.")
                try:
                    import folium
                    from streamlit_folium import st_folium
                except ImportError:
                    st.warning("Map dependencies are unavailable. Install the Module 4 requirements, or enter coordinates below.")
                else:
                    position = (st.session_state["course_venue_lat"], st.session_state["course_venue_lng"])
                    map_view = folium.Map(location=position, zoom_start=16, control_scale=True)
                    folium.Marker(position, tooltip="Selected venue").add_to(map_view)
                    map_data = st_folium(
                        map_view, height=360, use_container_width=True,
                        returned_objects=["last_clicked"], key="course_venue_map",
                    )
                    selected = clicked_coordinates(map_data)
                    if selected is not None and selected != st.session_state.get("course_last_map_click"):
                        st.session_state["course_last_map_click"] = selected
                        st.session_state["course_venue_lat"], st.session_state["course_venue_lng"] = selected
                        st.rerun()  # Refresh the pin after the new selection.

            c3, c4 = st.columns(2)
            venue_lat = c3.number_input("Venue latitude", min_value=-90.0, max_value=90.0,
                                        format="%.6f", key="course_venue_lat")
            venue_lng = c4.number_input("Venue longitude", min_value=-180.0, max_value=180.0,
                                        format="%.6f", key="course_venue_lng")

            c6, c7 = st.columns(2)
            radius = c6.number_input("Geofence radius (m)", min_value=10.0, value=100.0, step=10.0)
            risk_threshold = c7.slider("Default risk threshold", 0.0, 1.0, 0.5, 0.05)

            submitted = st.button("Create course", type="primary", use_container_width=True)

        if submitted:
            if not code.strip() or not name.strip() or not semester.strip():
                st.error("Code, name, and semester are required.")
            else:
                payload = {
                    "code": code.strip(),
                    "name": name.strip(),
                    "semester": semester.strip(),
                    "venue_name": venue_name.strip() or None,
                    "venue_latitude": venue_lat,
                    "venue_longitude": venue_lng,
                    "geofence_radius_meters": radius,
                    "risk_threshold": risk_threshold,
                }
                created = safe_call(client.post, "/courses/", json=payload, error_prefix="Could not create course")
                if created:
                    st.success(f"Course `{created.get('code')}` created.")

    if current_role() == "admin":
        st.divider()
        st.markdown("#### Update an existing course")
        courses_resp = safe_call(client.get, "/courses/", params={"limit": 100}, error_prefix="Could not load courses")
        courses = safe_items(courses_resp)
        if courses:
            label_to_course = {f"{c['code']} — {c['name']}": c for c in courses}
            edit_pick = st.selectbox("Course to edit", list(label_to_course.keys()), key="course_edit_pick")
            course = label_to_course[edit_pick]
            with st.form("edit_course_form"):
                new_name = st.text_input("Name", value=course.get("name", ""))
                new_venue = st.text_input("Venue name", value=course.get("venue_name") or "")
                new_radius = st.number_input(
                    "Geofence radius (m)", min_value=10.0, value=float(course.get("geofence_radius_meters") or 100.0)
                )
                new_threshold = st.slider(
                    "Risk threshold", 0.0, 1.0, float(course.get("risk_threshold") if course.get("risk_threshold") is not None else 0.5), 0.05
                )
                save = st.form_submit_button("Save changes", use_container_width=True)
            if save:
                payload = {
                    "name": new_name,
                    "venue_name": new_venue or None,
                    "geofence_radius_meters": new_radius,
                    "risk_threshold": new_threshold,
                }
                if safe_call(client.put, f"/courses/{course['id']}", json=payload, error_prefix="Could not update course"):
                    st.success("Course updated.")

# ======================================================================= #
with tab_stats:
    if current_role() == "ta":
        st.info("Course-wide analytics are for instructors and admins. TAs can review their assigned sessions on the Sessions page.")
        st.stop()
    courses_resp = safe_call(client.get, "/courses/", params={"limit": 100}, error_prefix="Could not load courses")
    courses = safe_items(courses_resp)
    if not courses:
        st.caption("No courses yet.")
    else:
        label_to_id = {f"{c['code']} — {c['name']}": c["id"] for c in courses}
        stats_pick = st.selectbox("Course", list(label_to_id.keys()), key="course_stats_pick")
        course_id = label_to_id[stats_pick]

        stats = safe_call(client.get, f"/stats/courses/{course_id}", error_prefix="Could not load course stats")
        if stats:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total sessions", pick(stats, "total_sessions", default="—"))
            c2.metric("Total enrolled", pick(stats, "total_enrolled", default="—"))
            rate = pick(stats, "average_attendance_rate", "overall_attendance_rate")
            c3.metric("Avg attendance rate", f"{rate * 100:.1f}%" if rate is not None else "—")
            flagged = pick(stats, "flagged_checkins")
            c4.metric("Flagged check-ins", flagged if flagged is not None else "—")

            sessions = stats.get("sessions") or []
            if sessions:
                df = pd.DataFrame(sessions)
                fig = px.bar(df, x="name", y="attendance_rate", title="Attendance rate by session")
                fig.update_yaxes(rangemode="tozero", tickformat=".0%", range=[0, 1])
                st.plotly_chart(fig, use_container_width=True)

            alerts = stats.get("low_attendance_alerts") or []
            if alerts:
                st.subheader("⚠️ Low-attendance alerts")
                st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)

            student_attendance = stats.get("student_attendance") or []
            if student_attendance:
                st.subheader("Per-student attendance")
                df_students = pd.DataFrame(student_attendance)
                st.dataframe(df_students, use_container_width=True, hide_index=True)
                download_csv_button(df_students, f"course_{course_id}_attendance.csv", key="course_attendance_csv")

        st.divider()
        st.markdown("#### Export attendance for gradebook")
        fmt = st.radio("Format", ["csv", "json"], horizontal=True, key="course_export_fmt")
        if st.button("Generate export", key="course_export_btn"):
            resp = safe_call(
                client.get_raw, f"/export/attendance/{course_id}", params={"format": fmt},
                error_prefix="Export failed",
            )
            if resp is not None:
                st.session_state["course_export_ready"] = {
                    "course_id": course_id, "format": fmt, "bytes": resp.content
                }
        prepared = st.session_state.get("course_export_ready")
        if prepared and prepared["course_id"] == course_id and prepared["format"] == fmt:
            st.download_button(
                f"⬇ Download {fmt.upper()}", data=prepared["bytes"],
                file_name=f"course_{course_id}_attendance.{fmt}",
                mime="text/csv" if fmt == "csv" else "application/json",
                key="course_export_dl",
            )
