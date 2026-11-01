"""Regression checks for the new session and course creation inputs."""

import sys
from datetime import date, time, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from form_helpers import clicked_coordinates, current_semester, semester_options, sgt_datetime


def test_sgt_picker_to_iso8601_handles_midnight_rollover():
    start = sgt_datetime(date(2026, 11, 1), time(0, 5))
    assert start.isoformat() == "2026-11-01T00:05:00+08:00"
    assert (start - timedelta(minutes=15)).isoformat() == "2026-10-31T23:50:00+08:00"


def test_semester_dropdown_has_current_and_future_options():
    now = date(2026, 11, 1)
    choices = semester_options(now)
    assert current_semester(now) == "AY2026-27 Sem 1"
    assert current_semester(date(2027, 2, 1)) == "AY2026-27 Sem 2"
    assert "AY2026-27 Sem 1" in choices and "AY2029-30 Sem 2" in choices
    assert all(len(value) <= 20 for value in choices)


def test_map_click_coordinates_are_validated_and_rounded():
    assert clicked_coordinates({"last_clicked": {"lat": 1.34830036, "lng": 103.6831009}}) == (1.3483, 103.683101)
    assert clicked_coordinates(None) is None
    assert clicked_coordinates({"last_clicked": None}) is None
    assert clicked_coordinates({"last_clicked": {"lat": 200, "lng": 100}}) is None
    assert clicked_coordinates({"last_clicked": {"lat": "garbage", "lng": 100}}) is None
