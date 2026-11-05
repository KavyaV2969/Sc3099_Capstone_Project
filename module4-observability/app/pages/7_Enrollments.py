import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

from auth import require_role, sidebar_user_box, get_client, current_role
from api_client import safe_call, safe_delete
from utils import safe_items, download_csv_button, pick, fmt_dt, flash, show_flash

st.set_page_config(page_title="Enrollments · SAIV Dashboard", page_icon="👥", layout="wide")
require_role("instructor", "ta", "admin")
sidebar_user_box()

st.title("👥 Enrollments")
client = get_client()

courses_resp = safe_call(client.get, "/courses/", params={"limit": 100}, error_prefix="Could not load courses")
courses = safe_items(courses_resp)

if not courses:
    st.caption("No courses yet — create one on the **Courses** page first.")
    st.stop()

label_to_course = {f"{c['code']} — {c['name']}": c for c in courses}
course_pick = st.selectbox("Course", list(label_to_course.keys()))
course = label_to_course[course_pick]

roster = safe_call(
    client.get, f"/enrollments/course/{course['id']}", error_prefix="Could not load roster"
)

st.subheader(f"Roster — {roster.get('total_enrolled', 0) if roster else 0} student(s)")
students = (roster or {}).get("students", [])

if students:
    df = pd.DataFrame(students)
    cols = [c for c in ["student_name", "student_email", "enrolled_at", "is_active", "face_enrolled"] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    download_csv_button(df, f"{course['code']}_roster.csv", key="roster_csv")

    if current_role() in ("instructor", "admin"):
        st.markdown("#### Remove a student")
    label_to_enrollment = {f"{row.get('student_name')} ({row.get('student_email')})": row for row in students}
    if current_role() in ("instructor", "admin"):
        remove_pick = st.selectbox("Student to remove", list(label_to_enrollment), key="remove_pick")
        confirm_remove = st.checkbox("I confirm this student should be removed from the course", key="confirm_remove")
        if st.button("Remove from course", type="secondary", disabled=not confirm_remove):
            enrollment = label_to_enrollment[remove_pick]
            if safe_delete(client, f"/enrollments/{enrollment['id']}", error_prefix="Could not remove enrollment"):
                flash("Student removed.", "success")
                st.rerun()

    st.markdown("#### Individual student attendance")
    student_pick = st.selectbox("Student", list(label_to_enrollment.keys()), key="student_stats_pick")
    if current_role() == "ta":
        st.caption("Per-student aggregate analytics are only available to instructors and admins.")
    elif st.button("Load attendance", key="load_student_stats"):
        enrollment = label_to_enrollment[student_pick]
        student_id = enrollment.get("student_id") or enrollment.get("id")
        student_stats = safe_call(
            client.get, f"/stats/students/{student_id}", error_prefix="Could not load student stats"
        )
        if student_stats:
            sc1, sc2, sc3, sc4 = st.columns(4)
            course_stats = student_stats.get("courses") or []
            enrolled_courses = pick(student_stats, "total_enrolled_courses", default=len(course_stats))
            attended = pick(student_stats, "attended_sessions",
                            default=sum(item.get("sessions_attended", 0) for item in course_stats))
            scheduled = pick(student_stats, "total_sessions",
                             default=sum(item.get("total_sessions", 0) for item in course_stats))
            sc1.metric("Enrolled courses", enrolled_courses)
            sc2.metric("Sessions attended", attended)
            sc3.metric("Sessions scheduled", scheduled)
            avg_risk = pick(student_stats, "average_risk_score")
            if avg_risk is None and course_stats:
                avg_risk = sum(item.get("average_risk_score", 0) for item in course_stats) / len(course_stats)
            sc4.metric("Average risk", f"{avg_risk:.2f}" if avg_risk is not None else "—")

            recent = student_stats.get("recent_checkins") or student_stats.get("recent_sessions") or []
            if recent:
                df_recent = pd.DataFrame(recent)
                for column in ("checked_in_at", "date"):
                    if column in df_recent.columns:
                        df_recent[column] = df_recent[column].apply(fmt_dt)
                st.dataframe(df_recent, use_container_width=True, hide_index=True)
else:
    st.caption("No students enrolled in this course yet.")

st.divider()
if current_role() == "ta":
    st.stop()

st.subheader("Add students")

add_tab, bulk_tab = st.tabs(["Add one", "Bulk enroll by email"])

with add_tab:
    with st.form("add_enrollment_form"):
        student_id = st.text_input("Student user ID (uuid)")
        submitted = st.form_submit_button("Enroll", type="primary")
    if submitted:
        if not student_id.strip():
            st.error("Enter a student ID.")
        else:
            payload = {"student_id": student_id.strip(), "course_id": course["id"]}
            if safe_call(client.post, "/enrollments/", json=payload, error_prefix="Could not enroll student"):
                flash("Student enrolled.", "success")
                st.rerun()

with bulk_tab:
    with st.form("bulk_enroll_form"):
        emails_text = st.text_area(
            "Student emails (one per line, or comma-separated)",
            placeholder="alice@e.ntu.edu.sg\nbob@e.ntu.edu.sg",
            height=150,
        )
        st.caption("Accounts must already exist; the current backend does not support creating accounts during bulk enrollment.")
        create_accounts = False
        submitted = st.form_submit_button("Bulk enroll", type="primary")
    if submitted:
        emails = [e.strip() for chunk in emails_text.splitlines() for e in chunk.split(",") if e.strip()]
        if not emails:
            st.error("Paste at least one email address.")
        else:
            payload = {"course_id": course["id"], "student_emails": emails, "create_accounts": create_accounts}
            result = safe_call(client.post, "/enrollments/bulk", json=payload, error_prefix="Bulk enroll failed")
            if result:
                st.success(
                    f"Enrolled: {result.get('enrolled', 0)} · "
                    f"Already enrolled: {result.get('already_enrolled', 0)} · "
                    f"Not found: {result.get('not_found', 0)} · "
                    f"Created: {result.get('created', 0)}"
                )
                details = result.get("details")
                if details:
                    st.dataframe(pd.DataFrame(details), use_container_width=True, hide_index=True)
    

show_flash()
