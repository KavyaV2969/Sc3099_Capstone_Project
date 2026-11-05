import secrets
import threading
import time

import streamlit as st
import streamlit.components.v1 as components

from config import SESSION_COOKIE, SESSION_TTL_HOURS

_lock = threading.Lock()


@st.cache_resource
def _store() -> dict:
    return {}


def create(refresh_token: str) -> str:
    sid = secrets.token_urlsafe(32)
    with _lock:
        _purge()
        _store()[sid] = {"refresh_token": refresh_token, "expires": time.time() + SESSION_TTL_HOURS * 3600}
    return sid


def refresh_token_for(sid: str | None) -> str | None:
    if not sid:
        return None
    with _lock:
        entry = _store().get(sid)
        if entry is None:
            return None
        if entry["expires"] < time.time():
            _store().pop(sid, None)
            return None
        return entry["refresh_token"]


def update(sid: str | None, refresh_token: str | None) -> None:
    if not sid or not refresh_token:
        return
    with _lock:
        entry = _store().get(sid)
        if entry is not None:
            entry["refresh_token"] = refresh_token


def drop(sid: str | None) -> None:
    if not sid:
        return
    with _lock:
        _store().pop(sid, None)


def _purge() -> None:
    now = time.time()
    for key in [k for k, v in _store().items() if v["expires"] < now]:
        _store().pop(key, None)


def cookie_sid() -> str | None:
    try:
        return st.context.cookies.get(SESSION_COOKIE)
    except Exception:
        return None


def write_cookie(value: str | None) -> None:
    max_age = int(SESSION_TTL_HOURS * 3600) if value else 0
    safe_value = value or ""
    components.html(
        "<script>"
        "(function(){var d;try{d=window.parent.document;}catch(e){d=document;}"
        f"var c='{SESSION_COOKIE}={safe_value}; path=/; max-age={max_age}; SameSite=Strict';"
        "if(d.location&&d.location.protocol==='https:'){c+='; Secure';}"
        "d.cookie=c;})();"
        "</script>",
        height=0,
    )
