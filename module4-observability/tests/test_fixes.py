import datetime as dt
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import api_client
import metrics
import utils


def test_has_value_treats_pandas_nan_as_missing():
    df = pd.DataFrame([{"id": 1, "risk_factors": [{"category": "device"}]}, {"id": 2}])
    assert utils.has_value(df.iloc[0]["risk_factors"])
    assert not utils.has_value(df.iloc[1].get("risk_factors"))
    assert not utils.has_value(None) and not utils.has_value([]) and not utils.has_value({})


def test_risk_factors_df_accepts_list_and_dict():
    listed = utils.risk_factors_df([{"category": "device", "type": "unknown_device", "severity": "high",
                                     "weight": 0.2, "risk": 1.0, "critical": False}])
    assert list(listed.columns) == ["category", "type", "severity", "contribution to score", "signal risk"]
    assert not utils.risk_factors_df({"device": 0.2, "network": 0.03}).empty
    assert utils.risk_factors_df(None).empty


def test_reset_offset_on_change(monkeypatch):
    state = {}
    monkeypatch.setattr(utils.st, "session_state", state, raising=False)
    state["offset"] = 50
    utils.reset_offset_on_change("offset", ("a", 25))
    assert state["offset"] == 0
    state["offset"] = 50
    utils.reset_offset_on_change("offset", ("a", 25))
    assert state["offset"] == 50
    utils.reset_offset_on_change("offset", ("b", 25))
    assert state["offset"] == 0


def test_fetch_all_pages_through_capped_endpoints():
    rows = [{"id": i} for i in range(230)]
    client = Mock()
    client.get.side_effect = lambda path, params=None: rows[params["offset"]: params["offset"] + params["limit"]]
    items, total = api_client.fetch_all(client, "/checkins/session/x")
    assert len(items) == 230 and total == 230
    assert client.get.call_count == 3


def test_fetch_all_uses_backend_total_for_dict_payloads():
    rows = [{"id": i} for i in range(120)]
    client = Mock()
    client.get.side_effect = lambda path, params=None: {
        "items": rows[params["offset"]: params["offset"] + params["limit"]], "total": 120}
    items, total = api_client.fetch_all(client, "/checkins/flagged")
    assert (len(items), total) == (120, 120)


def _prom(responses):
    def fake(promql):
        for needle, value in responses.items():
            if needle in promql:
                return {"data": {"result": [] if value is None else [{"value": [0, str(value)]}]}}
        return {"data": {"result": []}}
    return fake


def test_request_and_error_rate_fall_back_to_duration_count(monkeypatch):
    monkeypatch.setattr(metrics, "query_prometheus", _prom({
        'http_request_duration_seconds_count{job="saiv-backend", status=~"5.."}': 0.1,
        "http_request_duration_seconds_count": 2.0,
    }))
    assert metrics.get_request_rate("saiv-backend") == 2.0
    assert round(metrics.get_error_rate_pct("saiv-backend"), 2) == 5.0


def test_nan_results_are_reported_as_no_data(monkeypatch):
    monkeypatch.setattr(metrics, "query_prometheus", _prom({"checkin": "NaN"}))
    assert metrics.get_checkin_success_rate_pct() is None


def test_session_form_defaults_do_not_reset_when_the_clock_advances(monkeypatch):
    from streamlit.testing.v1 import AppTest
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth

    client = Mock()
    course = {"id": "c1", "code": "CS", "name": "Cap", "instructor_id": "i1", "geofence_radius_meters": 100.0}
    client.get.side_effect = lambda path, params=None: (
        {"items": [course], "total": 1} if path == "/courses/" else {"items": [], "total": 0})
    monkeypatch.setattr(auth, "get_client", lambda: client)

    real = dt.datetime

    class Clock(real):
        offset = 0

        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + dt.timedelta(minutes=cls.offset)

    monkeypatch.setattr(dt, "datetime", Clock)
    app = AppTest.from_file(str(APP_DIR / "pages/2_Sessions.py"), default_timeout=20)
    app.session_state["access_token"] = "t"
    app.session_state["user"] = {"id": "i1", "role": "instructor", "full_name": "T"}
    app.run()
    next(x for x in app.time_input if x.label == "Scheduled start time").set_value(dt.time(15, 45)).run()
    Clock.offset = 2
    app.run()
    assert next(x for x in app.time_input if x.label == "Scheduled start time").value == dt.time(15, 45)
