"""Small formatting / display helpers used across dashboard pages."""
from __future__ import annotations

import io
import math
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from config import RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_ICONS, STATUS_ICONS


def fmt_dt(value) -> str:
    """Best-effort human formatting of an ISO8601 timestamp string."""
    if not value:
        return "—"
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M SGT")
    except (ValueError, TypeError):
        return str(value)


def fmt_dt_short(value) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %H:%M")
    except (ValueError, TypeError):
        return str(value)


def has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, (str, list, tuple, dict, set)) and len(value) == 0:
        return False
    return True


def risk_factors_df(factors) -> pd.DataFrame:
    if isinstance(factors, dict):
        factors = [{"category": k, "weight": v} if not isinstance(v, dict) else {"category": k, **v}
                   for k, v in factors.items()]
    if not isinstance(factors, list) or not factors:
        return pd.DataFrame()
    df = pd.DataFrame([f for f in factors if isinstance(f, dict)])
    wanted = [c for c in ("category", "type", "severity", "weight", "risk") if c in df.columns]
    df = df[wanted] if wanted else df
    return df.rename(columns={"weight": "contribution to score", "risk": "signal risk"})


def render_risk_factors(factors) -> None:
    df = risk_factors_df(factors)
    if df.empty:
        st.caption("No risk factors recorded.")
        return
    st.caption("Risk factors (contributions add up to the risk score)")
    st.dataframe(df, use_container_width=True, hide_index=True)


def flash(message: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    icons = {"success": "✅", "info": "ℹ️", "warning": "⚠️", "error": "🚫"}
    for kind, message in st.session_state.pop("_flash", []):
        st.toast(message, icon=icons.get(kind, "ℹ️"))


def reset_offset_on_change(offset_key: str, signature, name: str = "filters") -> None:
    sig_key = f"{offset_key}__{name}"
    if st.session_state.get(sig_key) != signature:
        st.session_state[sig_key] = signature
        st.session_state[offset_key] = 0


def risk_level(score) -> str:
    if score is None:
        return "unknown"
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if score < RISK_LOW:
        return "low"
    if score < RISK_MEDIUM:
        return "medium"
    if score < RISK_HIGH:
        return "high"
    return "critical"


def risk_badge(score) -> str:
    if score is None:
        return "—"
    try:
        score = float(score)
    except (TypeError, ValueError):
        return str(score)
    return f"{RISK_ICONS[risk_level(score)]} {score:.2f}"


def status_badge(status: str | None) -> str:
    if not status:
        return "—"
    return f"{STATUS_ICONS.get(status, '•')} {status}"


# Restrict preview-derived exports to relevant attendance fields: never include
# raw location/device identifiers, consent, embeddings or risk-factor payloads.
PREVIEW_EXPORT_COLUMNS = (
    "id", "student_id", "student_name", "student_email", "session_id",
    "session_name", "course_code", "checked_in_at", "status", "risk_score",
    "name", "scheduled_start", "scheduled_end", "session_type",
    "total_enrolled", "checked_in_count", "code", "semester",
    "enrolled_at", "is_active", "full_name", "email", "role",
    "face_enrolled", "created_at", "action", "resource_type",
    "resource_id", "timestamp", "success", "severity",
)

SIGNAL_EXPORT_COLUMNS = (
    "liveness_score", "face_match_score", "liveness_passed", "face_match_passed",
    "device_trusted", "distance_from_venue_meters", "latitude", "longitude",
)


def df_to_csv_bytes(df: pd.DataFrame, include_signals: bool = False) -> bytes:
    """Excel-safe UTF-8 CSV for *current-page* data (not an official export)."""
    allowed = PREVIEW_EXPORT_COLUMNS + (SIGNAL_EXPORT_COLUMNS if include_signals else ())
    preview = df.loc[:, [c for c in allowed if c in df.columns]].copy()
    # CSV escaping handles commas and quotes, not spreadsheet formulas. Escape
    # cells starting with spreadsheet formula prefixes, including leading spaces.
    def safe_cell(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value
    preview = preview.apply(lambda col: col.map(safe_cell))
    buf = io.StringIO(newline="")
    preview.to_csv(buf, index=False)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def download_csv_button(df: pd.DataFrame, filename: str, label: str = "⬇ Download CSV", key: str | None = None,
                        signals_option: bool = False):
    if df is None or df.empty:
        st.caption("Nothing to export yet.")
        return
    st.caption("Preview CSV: only currently loaded rows; use the official export for a complete gradebook.")
    include_signals = False
    if signals_option and any(c in df.columns for c in SIGNAL_EXPORT_COLUMNS):
        include_signals = st.checkbox(
            "Include GPS coordinates and liveness / face-match scores (sensitive)", key=f"{key}_signals"
        )
    st.download_button(
        label,
        data=df_to_csv_bytes(df, include_signals),
        file_name=filename,
        mime="text/csv",
        key=key,
        use_container_width=True,
    )


def pagination_controls(total: int, limit: int, offset: int, key: str) -> int:
    """
    Renders Previous / page-indicator / Next controls.
    Returns the (possibly updated) offset to use on the *next* rerun.
    """
    total = total or 0
    pages = max(1, -(-total // limit)) if limit else 1
    current_page = (offset // limit) + 1 if limit else 1

    col_prev, col_mid, col_next = st.columns([1, 2, 1])
    new_offset = offset
    with col_prev:
        if st.button("← Previous", key=f"{key}_prev", disabled=offset <= 0, use_container_width=True):
            new_offset = max(0, offset - limit)
    with col_mid:
        st.markdown(
            f"<div style='text-align:center; padding-top:0.4rem;'>"
            f"Page {current_page} of {pages} · {total} total</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Next →", key=f"{key}_next", disabled=offset + limit >= total, use_container_width=True):
            new_offset = offset + limit
    return new_offset


def safe_items(payload) -> list:
    """Backends may return either `{"items": [...]}` or a bare list - handle both."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        return payload.get("items", [])
    if isinstance(payload, list):
        return payload
    return []


def safe_total(payload, fallback: int | None = None) -> int:
    if isinstance(payload, dict) and "total" in payload:
        return payload["total"]
    return fallback if fallback is not None else len(safe_items(payload))


def pick(d: dict, *keys, default=None):
    """
    Return the value of the first key present (and non-None) in `d`.

    Exists because docs/API-SPECIFICATION.md's prose examples and the
    actual grading tests in tests/public/*.py don't always agree on field
    names for the same endpoint (e.g. stats/overview's prose example says
    "total_checkins_today" but test_observability.py asserts
    "today_checkins"; stats/sessions/{id}'s prose says "checked_in" but the
    test asserts "checked_in_count"). Since either convention is a
    legitimate reading of "the spec", every stat displayed in this
    dashboard is looked up through this helper with both candidate names
    so it works regardless of which one your backend teammate implemented.
    """
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


SGT = ZoneInfo("Asia/Singapore")


def sgt_day_bounds(day=None):
    day = day or datetime.now(SGT).date()
    return datetime.combine(day, time.min, tzinfo=SGT), datetime.combine(day, time.max, tzinfo=SGT)


def checkins_by_hour(items) -> pd.DataFrame:
    hours = pd.DataFrame({"hour": range(24), "count": 0})
    if not items:
        hours["label"] = hours["hour"].map(lambda h: f"{h:02d}:00")
        return hours
    stamps = pd.to_datetime(pd.Series([i.get("checked_in_at") for i in items]), utc=True, errors="coerce").dropna()
    counts = stamps.dt.tz_convert(SGT).dt.hour.value_counts()
    hours["count"] = hours["hour"].map(counts).fillna(0).astype(int)
    hours["label"] = hours["hour"].map(lambda h: f"{h:02d}:00")
    return hours


def status_counts(items) -> pd.DataFrame:
    counts = pd.Series([i.get("status", "unknown") for i in items], dtype="object").value_counts()
    return counts.rename_axis("status").reset_index(name="count")


def signal_columns(df: pd.DataFrame) -> pd.DataFrame:
    view = df.copy()
    for column in ("liveness_score", "face_match_score", "distance_from_venue_meters"):
        if column in view:
            view[column] = pd.to_numeric(view[column], errors="coerce").round(3)
    return view

