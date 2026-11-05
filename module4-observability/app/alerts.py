from datetime import datetime, timedelta, timezone

import streamlit as st

from api_client import safe_call
from config import FAILED_LOGIN_ALERT_COUNT, FAILED_LOGIN_WINDOW_HOURS, FLAGGED_RATE_ALERT

MIN_SAMPLE = 5


def failed_login_count(client) -> int | None:
    since = (datetime.now(timezone.utc) - timedelta(hours=FAILED_LOGIN_WINDOW_HOURS)).isoformat()
    result = safe_call(
        client.get, "/audit/",
        params={"action": "login_failed", "start_date": since, "limit": 1},
        error_prefix="Could not check failed logins",
    )
    if not isinstance(result, dict):
        return None
    return int(result.get("total", len(result.get("items", []))))


def flagged_rate(items) -> tuple[float, int, int]:
    total = len(items)
    flagged = sum(1 for item in items if item.get("status") in ("flagged", "appealed"))
    return (flagged / total if total else 0.0), flagged, total


def render_flagged_alert(items) -> None:
    rate, flagged, total = flagged_rate(items)
    if total >= MIN_SAMPLE and rate >= FLAGGED_RATE_ALERT:
        st.warning(
            f"🚩 High flagged rate: {flagged} of {total} check-ins today ({rate * 100:.0f}%) are flagged or appealed "
            f"(alert threshold {FLAGGED_RATE_ALERT * 100:.0f}%). This may point to a venue, device or network issue."
        )


def render_failed_login_alert(client) -> None:
    count = failed_login_count(client)
    if count is not None and count >= FAILED_LOGIN_ALERT_COUNT:
        hours = FAILED_LOGIN_WINDOW_HOURS
        st.error(
            f"🔐 {count} failed logins in the last {hours} hour{'s' if hours != 1 else ''} "
            f"(alert threshold {FAILED_LOGIN_ALERT_COUNT}). Possible credential attack: review the Audit Logs."
        )
