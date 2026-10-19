"""
Thin wrapper around the SAIV Backend REST API (Module 2).

Kept deliberately dependency-light (plain `requests`) since the backend is
technology-agnostic - this dashboard only ever talks to it over HTTP/JSON,
exactly like the automated test suite does. See docs/API-SPECIFICATION.md
for the full contract.
"""
from __future__ import annotations

import streamlit as st
import requests

from config import API_BASE, REQUEST_TIMEOUT


class APIError(Exception):
    """Raised for any non-2xx response or network failure."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:  # nice for st.error(str(e))
        base = super().__str__()
        return f"{base} (HTTP {self.status_code})" if self.status_code else base


class APIClient:
    """
    Stateless-ish REST client. Tokens are mirrored into `st.session_state` so
    they survive Streamlit's per-page-script reruns, and a fresh APIClient()
    instance always picks up whatever is currently in session_state.
    """

    def __init__(self):
        self.access_token = st.session_state.get("access_token")
        self.refresh_token = st.session_state.get("refresh_token")

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #
    def login(self, email: str, password: str) -> tuple[bool, str | None]:
        """Returns (success, error_message)."""
        try:
            resp = requests.post(
                f"{API_BASE}/auth/login",
                json={"email": email, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            return False, f"Could not reach backend at {API_BASE} ({exc})"

        if resp.status_code != 200:
            return False, self._extract_detail(resp)

        try:
            data = resp.json()
        except ValueError:
            return False, "Backend returned an invalid login response"
        if not isinstance(data, dict) or not data.get("access_token"):
            return False, "Backend did not issue an access token"
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        st.session_state.access_token = self.access_token
        st.session_state.refresh_token = self.refresh_token
        st.session_state.user = data.get("user") or {}

        # Some minimal backends might not embed the user object in the
        # login response even though the spec asks for it - fall back to
        # GET /users/me so the dashboard still has a role to check.
        if not st.session_state.user:
            try:
                st.session_state.user = self.get("/users/me") or {}
            except APIError:
                st.session_state.user = {}
        # Only verified staff users may retain tokens in dashboard state.
        from config import DASHBOARD_ROLES
        if st.session_state.user.get("role") not in DASHBOARD_ROLES:
            self.clear_tokens()
            return False, "This portal is for TAs, instructors, and administrators"


        return True, None

    def clear_tokens(self) -> None:
        self.access_token = None
        self.refresh_token = None
        for key in ("access_token", "refresh_token", "user",
                    "pending_export", "session_export_ready", "course_export_ready"):
            st.session_state.pop(key, None)

    def _refresh(self) -> bool:
        if not self.refresh_token:
            return False
        try:
            resp = requests.post(
                f"{API_BASE}/auth/refresh",
                json={"refresh_token": self.refresh_token},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            return False
        if resp.status_code != 200:
            return False
        try:
            data = resp.json()
        except ValueError:
            return False
        if not isinstance(data, dict) or not data.get("access_token"):
            return False
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        st.session_state.access_token = self.access_token
        st.session_state.refresh_token = self.refresh_token
        return True

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    @staticmethod
    def _extract_detail(resp: requests.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            return f"HTTP {resp.status_code}"
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, list):  # 422 validation errors
            return "; ".join(str(d.get("msg", d)) for d in detail)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or f"HTTP {resp.status_code}")
        return str(detail) if detail else f"HTTP {resp.status_code}"

    # ------------------------------------------------------------------ #
    # Generic request plumbing
    # ------------------------------------------------------------------ #
    def request(self, method: str, path: str, retry: bool = True, raw: bool = False, **kwargs):
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            raise APIError("Invalid API path")
        url = f"{API_BASE}{path}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)

        try:
            resp = requests.request(method, url, headers=self._headers(), **kwargs)
        except requests.RequestException as exc:
            raise APIError(f"Network error contacting backend: {exc}") from exc

        if resp.status_code == 401 and retry and self.refresh_token:
            if self._refresh():
                try:
                    resp = requests.request(method, url, headers=self._headers(), **kwargs)
                except requests.RequestException as exc:
                    raise APIError("Network error retrying backend request") from exc
            else:
                self.clear_tokens()
        if resp.status_code == 401:
            self.clear_tokens()

        if resp.status_code >= 400:
            raise APIError(self._extract_detail(resp), status_code=resp.status_code)

        if raw:
            return resp
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path: str, params: dict | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None):
        return self.request("POST", path, json=json)

    def patch(self, path: str, json: dict | None = None):
        return self.request("PATCH", path, json=json)

    def put(self, path: str, json: dict | None = None):
        return self.request("PUT", path, json=json)

    def delete(self, path: str):
        return self.request("DELETE", path)

    def get_raw(self, path: str, params: dict | None = None) -> requests.Response:
        """For file downloads (CSV export) where we need headers/bytes, not JSON."""
        return self.request("GET", path, params=params, raw=True)


def safe_call(fn, *args, error_prefix: str = "Request failed", **kwargs):
    """
    Call `fn(*args, **kwargs)`, catching APIError and showing it as a
    st.error instead of crashing the page. Returns None on failure.
    """
    try:
        return fn(*args, **kwargs)
    except APIError as exc:
        st.error(f"{error_prefix}: {exc}")
        return None


def safe_delete(client: APIClient, path: str, *, error_prefix: str = "Could not delete") -> bool:
    """DELETE commonly succeeds with HTTP 204 and no JSON body (None)."""
    try:
        client.delete(path)
        return True
    except APIError as exc:
        st.error(f"{error_prefix}: {exc}")
        return False
