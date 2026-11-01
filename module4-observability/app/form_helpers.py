"""Small, testable helpers for staff-facing creation controls."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


SGT = ZoneInfo("Asia/Singapore")


def sgt_datetime(day: date, clock: time) -> datetime:
    """Interpret a date/time picker as Singapore local time, not server time."""
    return datetime.combine(day, clock, tzinfo=SGT)


def semester_options(today: date) -> list[str]:
    """Offer the previous, current and next three academic years."""
    current_ay = today.year if today.month >= 8 else today.year - 1
    return [
        f"AY{year}-{(year + 1) % 100:02d} Sem {sem}"
        for year in range(current_ay - 1, current_ay + 4)
        for sem in (1, 2)
    ]


def current_semester(today: date) -> str:
    """Select the current NTU semester by default (users may change it)."""
    current_ay = today.year if today.month >= 8 else today.year - 1
    term = 1 if today.month >= 8 else 2
    return f"AY{current_ay}-{(current_ay + 1) % 100:02d} Sem {term}"


def clicked_coordinates(map_data: dict | None) -> tuple[float, float] | None:
    """Accept only valid latitude/longitude returned by the map component."""
    if not isinstance(map_data, dict) or not isinstance(map_data.get("last_clicked"), dict):
        return None
    clicked = map_data["last_clicked"]
    try:
        lat, lng = float(clicked["lat"]), float(clicked["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 6), round(lng, 6)
