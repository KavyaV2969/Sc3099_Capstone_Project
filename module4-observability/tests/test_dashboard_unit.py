"""Offline regression tests for the dashboard REST client and display helpers.

These tests intentionally use a minimal Streamlit double so they also run on
machines without Streamlit/Docker. Execute from module4-observability with
`python -m pytest tests/ -v` after installing pytest + pandas + requests.
"""
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))


class SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


@pytest.fixture
def streamlit_double(monkeypatch):
    fake = types.ModuleType("streamlit")
    fake.session_state = SessionState()
    fake.error = Mock()
    fake.caption = Mock()
    fake.download_button = Mock()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in ("api_client", "auth", "utils"):
        sys.modules.pop(name, None)
    yield fake
    for name in ("api_client", "auth", "utils"):
        sys.modules.pop(name, None)


def response(status=200, data=None, body=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = data if data is not None else {}
    r.content = (b'{}' if status != 204 else b'') if body is None else body
    return r


def test_staff_login_stores_tokens(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    monkeypatch.setattr(api.requests, "post", lambda *args, **kwargs: response(data={
        "access_token": "at", "refresh_token": "rt", "user": {"role": "instructor", "id": "id"}
    }))
    assert api.APIClient().login("t@ntu.edu.sg", "testpass") == (True, None)
    assert streamlit_double.session_state["access_token"] == "at"


def test_student_is_denied_and_tokens_removed(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    monkeypatch.setattr(api.requests, "post", lambda *args, **kwargs: response(data={
        "access_token": "at", "refresh_token": "rt", "user": {"role": "student"}
    }))
    ok, error = api.APIClient().login("t@ntu.edu.sg", "testpass")
    assert not ok and "portal" in error
    assert "access_token" not in streamlit_double.session_state


def test_login_without_embedded_user_fetches_identity(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    monkeypatch.setattr(api.requests, "post", lambda *a, **kw: response(data={"access_token": "at"}))
    monkeypatch.setattr(api.requests, "request", lambda *a, **kw: response(data={"role": "ta"}))
    assert api.APIClient().login("ta@ntu.edu.sg", "password")[0]
    assert streamlit_double.session_state["user"]["role"] == "ta"


def test_invalid_login_json_is_reported(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    bad = response()
    bad.json.side_effect = ValueError()
    monkeypatch.setattr(api.requests, "post", lambda *a, **kw: bad)
    assert not api.APIClient().login("a", "b")[0]


def test_refresh_and_retry_after_401(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    state = streamlit_double.session_state
    state.update(access_token="expired", refresh_token="refresh", user={"role": "instructor"})
    calls = []

    def req(method, url, **kwargs):
        calls.append(kwargs["headers"].get("Authorization"))
        return response(401, {"detail": "expired"}) if len(calls) == 1 else response(data={"ok": True})

    monkeypatch.setattr(api.requests, "request", req)
    monkeypatch.setattr(api.requests, "post", lambda *a, **k: response(data={"access_token": "fresh", "refresh_token": "rotated"}))
    assert api.APIClient().get("/stats/overview") == {"ok": True}
    assert calls == ["Bearer expired", "Bearer fresh"]
    assert state["refresh_token"] == "rotated"


def test_failed_refresh_clears_credentials(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    state = streamlit_double.session_state
    state.update(access_token="expired", refresh_token="rt", user={"role": "instructor"},
                 session_export_ready={"bytes": b"private"}, course_export_ready={"bytes": b"private"})
    monkeypatch.setattr(api.requests, "request", lambda *a, **kw: response(401, {"detail": "expired"}))
    monkeypatch.setattr(api.requests, "post", lambda *a, **kw: response(401, {"detail": "denied"}))
    with pytest.raises(api.APIError) as exc:
        api.APIClient().get("/stats/overview")
    assert exc.value.status_code == 401
    assert "access_token" not in state
    assert "session_export_ready" not in state
    assert "course_export_ready" not in state


@pytest.mark.parametrize("path", ["https://foreign.com/x", "//evil.com", "relative", "/bad\\path"])
def test_external_urls_are_rejected(streamlit_double, path):
    api = importlib.import_module("api_client")
    with pytest.raises(api.APIError):
        api.APIClient().get(path)


def test_delete_204_is_success(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    monkeypatch.setattr(api.requests, "request", lambda *a, **k: response(status=204))
    assert api.safe_delete(api.APIClient(), "/enrollments/123")


def test_api_422_error_is_human_readable(streamlit_double, monkeypatch):
    api = importlib.import_module("api_client")
    monkeypatch.setattr(api.requests, "request", lambda *a, **k: response(422, {
        "detail": [{"loc": ["body", "name"], "msg": "Field required"}]
    }))
    with pytest.raises(api.APIError, match="Field required"):
        api.APIClient().post("/sessions/", {})


def test_no_data_csv_is_limited_and_formula_safe(streamlit_double):
    utils = importlib.import_module("utils")
    df = pd.DataFrame([{"student_name": "=HYPERLINK(\"evil\")", "latitude": 1.1,
                        "longitude": 100.0, "status": "approved", "risk_score": 0.2}])
    csv = utils.df_to_csv_bytes(df).decode("utf-8-sig")
    assert "latitude" not in csv and "longitude" not in csv
    assert "'=HYPERLINK" in csv
    assert "approved" in csv


def test_timestamp_is_rendered_in_singapore_timezone(streamlit_double):
    utils = importlib.import_module("utils")
    assert utils.fmt_dt("2026-10-18T00:00:00Z") == "18 Oct 2026, 08:00 SGT"


def test_status_bands_and_api_response_parsers(streamlit_double):
    utils = importlib.import_module("utils")
    assert utils.risk_level(0.2) == "low"
    assert utils.risk_level(0.6) == "high"
    assert utils.safe_items({"items": [{"id": 1}]}) == [{"id": 1}]
    assert utils.safe_total({"items": [], "total": 52}) == 52
    assert utils.pick({"checked_in": 5}, "checked_in_count", "checked_in") == 5


def test_infra_mounts_preserved():
    repo = APP.parents[1]
    module = APP.parent
    compose = (repo / "docker-compose.yml").read_text()
    for path in ["prometheus.yml", "otel-collector-config.yml", "grafana/provisioning/dashboards.yml",
                 "grafana/provisioning/datasources.yml"]:
        assert (module / path).is_file()
    assert "./module4-observability/prometheus.yml" in compose
    assert "./module4-observability/grafana/provisioning" in compose


def test_no_unsupported_audit_summary_or_direct_db_paths():
    module = APP.parent
    content = "\n".join(f.read_text() for f in (APP / "pages").glob("*.py"))
    assert '"/audit/summary"' not in content
    assert "import db" not in content
    assert not (APP / "db.py").exists()
