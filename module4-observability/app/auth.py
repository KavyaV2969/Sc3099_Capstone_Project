"""
Authentication + RBAC helpers shared by every page of the dashboard.

Streamlit re-runs the whole script on every interaction and each page under
app/pages/ is its own script, so all shared state lives in
`st.session_state` and every page starts by calling `require_login()` or
`require_role(...)`.
"""
import streamlit as st

import session_store
from api_client import APIClient
from config import DASHBOARD_ROLES


def get_client() -> APIClient:
    """A fresh client per rerun, always in sync with session_state tokens."""
    return APIClient()


def restore_session() -> None:
    if st.session_state.get("restore_attempted"):
        return
    st.session_state["restore_attempted"] = True
    sid = session_store.cookie_sid()
    refresh = session_store.refresh_token_for(sid)
    if not refresh:
        if sid:
            st.session_state["cookie_action"] = ("clear", None)
        return
    client = APIClient()
    client.refresh_token = refresh
    if not client._refresh():
        session_store.drop(sid)
        st.session_state["cookie_action"] = ("clear", None)
        return
    try:
        user = client.get("/users/me") or {}
    except Exception:
        user = {}
    if user.get("role") not in DASHBOARD_ROLES:
        session_store.drop(sid)
        client.clear_tokens()
        st.session_state["cookie_action"] = ("clear", None)
        return
    st.session_state["user"] = user
    st.session_state["sid"] = sid
    session_store.update(sid, st.session_state.get("refresh_token"))


def flush_cookie_action() -> None:
    action = st.session_state.pop("cookie_action", None)
    if action is None:
        return
    kind, value = action
    session_store.write_cookie(value if kind == "set" else None)


def is_authenticated() -> bool:
    if not st.session_state.get("access_token"):
        restore_session()
    return bool(st.session_state.get("access_token")) and bool(st.session_state.get("user"))


def current_user() -> dict:
    return st.session_state.get("user", {}) or {}


def current_role() -> str | None:
    return current_user().get("role")


def logout():
    session_store.drop(st.session_state.get("sid"))
    st.session_state["cookie_action"] = ("clear", None)
    for key in ("access_token", "refresh_token", "user", "sid", "pending_export", "session_export_ready", "course_export_ready"):
        st.session_state.pop(key, None)


def login_form():
    """Renders the login form. Call from the Home page only."""
    st.subheader("Instructor / TA / Admin sign in")
    st.caption(
        "Students should use the SAIV mobile/web check-in app (Module 1), "
        "not this dashboard."
    )

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="instructor@ntu.edu.sg")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", use_container_width=True, type="primary")

    if not submitted:
        return

    if not email or not password:
        st.error("Please enter both email and password.")
        return

    client = get_client()
    ok, err = client.login(email, password)
    if not ok:
        st.error(err or "Login failed. Please check your credentials.")
        return

    role = current_role()
    if role not in DASHBOARD_ROLES:
        logout()
        st.error(
            f"This dashboard is for instructors, TAs, and admins only "
            f"(your account role is `{role}`)."
        )
        return

    sid = session_store.create(st.session_state.get("refresh_token"))
    st.session_state["sid"] = sid
    st.session_state["cookie_action"] = ("set", sid)
    st.rerun()


def require_login():
    """Stop rendering the page unless someone is logged in."""
    if not is_authenticated():
        st.warning("Please log in from the **Home** page first.")
        st.stop()
    if current_role() not in DASHBOARD_ROLES:
        st.error("Your account role does not have access to this dashboard.")
        st.stop()


def require_role(*roles: str):
    """Stop rendering the page unless the current user has one of `roles`."""
    require_login()
    if current_role() not in roles:
        st.error(
            f"This page requires one of these roles: {', '.join(roles)}. "
            f"Your role is `{current_role()}`."
        )
        st.stop()


def sidebar_user_box():
    """Small account card + logout button, shown at the bottom of the sidebar."""
    user = current_user()
    flush_cookie_action()
    with st.sidebar:
        st.markdown("---")
        st.caption("Signed in as")
        st.text(f"{user.get('full_name', '—')}\n{user.get('email', '')}\nRole: {user.get('role', '—')}")
        if st.button("Log out", use_container_width=True):
            logout()
            st.rerun()
