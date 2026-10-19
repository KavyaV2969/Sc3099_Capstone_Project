import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

from auth import require_role, sidebar_user_box, get_client
from api_client import safe_call
from utils import fmt_dt, safe_items, safe_total, pagination_controls, download_csv_button

st.set_page_config(page_title="Admin · Users · SAIV Dashboard", page_icon="🛠️", layout="wide")
require_role("admin")
sidebar_user_box()

st.title("🛠️ Admin — Users")
client = get_client()

tab_list, tab_new = st.tabs(["All users", "Register new account"])

with tab_list:
    if "users_offset" not in st.session_state:
        st.session_state.users_offset = 0

    c1, c2, c3, c4 = st.columns(4)
    role_f = c1.selectbox("Role", ["(any)", "student", "ta", "instructor", "admin"], key="user_role_f")
    active_f = c2.selectbox("Active", ["(any)", "true", "false"], key="user_active_f")
    search = c3.text_input("Search name/email", key="user_search_f")
    limit = c4.selectbox("Page size", [25, 50, 100], index=0, key="user_limit_f")

    params = {"limit": limit, "offset": st.session_state.users_offset}
    if role_f != "(any)":
        params["role"] = role_f
    if active_f != "(any)":
        params["is_active"] = active_f == "true"
    if search.strip():
        params["search"] = search.strip()

    result = safe_call(client.get, "/users/", params=params, error_prefix="Could not load users")
    items = safe_items(result)
    total = safe_total(result, fallback=len(items))

    if items:
        df = pd.DataFrame(items)
        cols = [c for c in ["email", "full_name", "role", "is_active", "face_enrolled", "created_at"] if c in df.columns]
        view = df[cols].copy()
        if "created_at" in view:
            view["created_at"] = view["created_at"].apply(fmt_dt)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.session_state.users_offset = pagination_controls(total, limit, st.session_state.users_offset, "users")
        download_csv_button(df, "users.csv", key="users_csv")

        st.divider()
        st.markdown("#### Manage a user")
        label_to_user = {f"{u.get('full_name')} ({u.get('email')}) — {u.get('role')}": u for u in items}
        pick = st.selectbox("User", list(label_to_user.keys()), key="user_manage_pick")
        user = label_to_user[pick]

        m1, m2, m3 = st.columns(3)
        with m1:
            if user.get("is_active"):
                if st.button("🚫 Deactivate", use_container_width=True):
                    if safe_call(client.patch, f"/admin/users/{user['id']}/deactivate", error_prefix="Could not deactivate"):
                        st.warning("User deactivated.")
                        st.rerun()
            else:
                if st.button("✅ Activate", use_container_width=True):
                    if safe_call(client.patch, f"/admin/users/{user['id']}/activate", error_prefix="Could not activate"):
                        st.success("User activated.")
                        st.rerun()
        with m2:
            new_role = st.selectbox(
                "Change role", ["student", "ta", "instructor", "admin"],
                index=["student", "ta", "instructor", "admin"].index(user.get("role", "student")),
                key="user_role_change",
            )
        with m3:
            if st.button("Save role", use_container_width=True):
                if safe_call(client.patch, f"/users/{user['id']}", json={"role": new_role}, error_prefix="Could not update role"):
                    st.success("Role updated.")
                    st.rerun()
    else:
        st.caption("No users match these filters.")

with tab_new:
    st.caption("Creates an account directly (e.g. for a new instructor or TA).")
    with st.form("register_user_form"):
        c1, c2 = st.columns(2)
        email = c1.text_input("Email")
        full_name = c2.text_input("Full name")
        c3, c4 = st.columns(2)
        password = c3.text_input("Temporary password", type="password", help="Minimum 8 characters")
        role = c4.selectbox("Role", ["student", "ta", "instructor", "admin"])
        submitted = st.form_submit_button("Create account", type="primary")

    if submitted:
        if not email.strip() or not full_name.strip() or len(password) < 8:
            st.error("Email, full name are required, and password must be at least 8 characters.")
        else:
            payload = {"email": email.strip(), "password": password, "full_name": full_name.strip(), "role": role}
            created = safe_call(client.post, "/auth/register", json=payload, error_prefix="Could not create account")
            if created:
                st.success(f"Account created for {created.get('email')}.")
