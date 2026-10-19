"""Render all Streamlit page scripts through a fake widget API.

This catches Python/UI control-flow crashes without requiring browser, Docker or
an installed Streamlit wheel. It is not a substitute for an actual AppTest.
"""
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PAGES = sorted((APP_DIR / "pages").glob("*.py"))


class StopPage(Exception):
    pass


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Widget:
    def __init__(self, root):
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, name):
        return getattr(self.root, name)


class FakeStreamlit(types.ModuleType):
    def __init__(self, user):
        super().__init__("streamlit")
        self.session_state = State(access_token="token", refresh_token="refresh", user=user)
        self.sidebar = Widget(self)
        self.cache_data = types.SimpleNamespace(clear=lambda: None)
        self.errors = []

    def _noop(self, *a, **kw):
        return None

    set_page_config = title = subheader = caption = markdown = info = warning = success = write = json = divider = text = code = plotly_chart = dataframe = metric = _noop
    page_link = download_button = _noop

    def error(self, value, *a, **kw):
        self.errors.append(str(value))

    def stop(self):
        raise StopPage()

    def rerun(self):
        raise RuntimeError("Unexpected rerun in passive smoke test")

    def columns(self, sizes, **kw):
        return [Widget(self) for _ in (range(sizes) if isinstance(sizes, int) else sizes)]

    def tabs(self, titles, **kw):
        return [Widget(self) for _ in titles]

    def form(self, *a, **kw):
        return Widget(self)

    def expander(self, *a, **kw):
        return Widget(self)

    def popover(self, *a, **kw):
        return Widget(self)

    def button(self, *a, **kw):
        return False

    form_submit_button = toggle = button

    def checkbox(self, *a, **kw):
        return kw.get("value", False)

    def text_input(self, *a, **kw):
        return kw.get("value", "")

    text_area = text_input

    def selectbox(self, label, options, **kw):
        opts = list(options)
        if not opts:
            raise AssertionError("Empty selectbox: " + label)
        return opts[kw.get("index", 0)]

    def radio(self, label, options, **kw):
        return self.selectbox(label, options, **kw)

    def slider(self, *a, **kw):
        return kw["value"] if "value" in kw else a[3] if len(a) > 3 else a[1]

    def number_input(self, *a, **kw):
        return kw.get("value", 0)

    def date_input(self, *a, **kw):
        return kw.get("value")

    def time_input(self, *a, **kw):
        return kw.get("value")


def make_client(nonempty=True, role="admin"):
    course = {"id": "c1", "name": "Research Methods", "code": "SC3099", "semester": "AY26", "risk_threshold": 0.5,
              "geofence_radius_meters": 100, "venue_name": "LT1"}
    session = {"id": "s1", "course_id": "c1", "course_code": "SC3099", "name": "Lecture 1", "status": "scheduled",
               "session_type": "lecture", "scheduled_start": "2026-10-20T10:00:00+00:00", "scheduled_end": "2026-10-20T11:00:00+00:00",
               "checkin_opens_at": "2026-10-20T09:45:00+00:00", "checkin_closes_at": "2026-10-20T10:30:00+00:00"}
    ci = {"id": "i1", "student_id": "u1", "student_name": "Student", "student_email": "s@example.edu",
          "session_id": "s1", "session_name": "Lecture 1", "status": "flagged", "risk_score": .65,
          "checked_in_at": "2026-10-20T10:00:00+00:00", "risk_factors": [], "appeal_reason": None}
    user = {"id": "u1", "role": "student", "email": "s@example.edu", "full_name": "Student", "is_active": True}
    client = Mock()

    def get(path, params=None):
        if path == "/sessions/my-sessions": return [session] if nonempty else []
        if path == "/sessions/":
            if role == "ta": raise AssertionError("TA cannot access global session endpoint")
            return {"items": [session] if nonempty else [], "total": int(nonempty)}
        if path == "/courses/": return {"items": [course] if nonempty else [], "total": int(nonempty)}
        if path == "/checkins/":
            if role == "ta": raise AssertionError("TA cannot access global checkins")
            return {"items": [ci] if nonempty else [], "total": int(nonempty)}
        if path == "/checkins/flagged": return [ci] if nonempty else []
        if path.startswith("/checkins/session/"): return [ci] if nonempty else []
        if path.startswith("/sessions/"): return session
        if path == "/stats/overview":
            if role == "ta": raise AssertionError("TA cannot access overview stats")
            return {"total_sessions": 1, "active_sessions": 0, "total_checkins_today": 1,
                    "total_checkins_week": 1, "approval_rate": .5, "average_attendance_rate": .8,
                    "flagged_pending_review": 1, "average_risk_score": .6, "high_risk_checkins_today": 1,
                    "trends": {"checkins_by_day": [{"date": "2026-10-20", "count": 1}],
                               "attendance_rate_by_day": [{"date": "2026-10-20", "rate": .8}]}}
        if path.startswith("/stats/sessions/"):
            return {"total_enrolled": 1, "checked_in": 1, "attendance_rate": 1., "by_status": {"flagged": 1, "approved": 0},
                    "average_risk_score": .65, "risk_distribution": {"low": 0, "medium": 0, "high": 1},
                    "checkin_timeline": [{"minute": 5, "count": 1}]}
        if path.startswith("/stats/courses/"):
            if role == "ta": raise AssertionError("TA cannot access course stats")
            return {"total_sessions": 1, "total_enrolled": 1, "overall_attendance_rate": 1.,
                    "sessions": [{"name": "Lecture 1", "attendance_rate": 1.}], "low_attendance_alerts": [],
                    "student_attendance": [{"student_name": "Student", "attendance_rate": 1.}]}
        if path.startswith("/enrollments/course/"):
            return {"students": [{"id": "e1", "student_id": "u1", "student_name": "Student", "student_email": "s@example.edu"}] if nonempty else [],
                    "total_enrolled": int(nonempty)}
        if path == "/audit/": return {"items": [{"id": "a1", "timestamp": "2026-10-19T00:00:00Z", "action": "login_success"}] if nonempty else [],
                                     "total": int(nonempty)}
        if path == "/users/": return {"items": [user] if nonempty else [], "total": int(nonempty)}
        raise AssertionError("Unrecognized backend route " + path)

    client.get.side_effect = get
    return client


@pytest.mark.parametrize("role", ["admin", "instructor", "ta"])
@pytest.mark.parametrize("nonempty", [True, False])
def test_all_pages_without_button_clicks(monkeypatch, role, nonempty):
    fake = FakeStreamlit({"id": "staff1", "role": role, "email": "staff@example.edu", "full_name": "Staff"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "metrics", "utils"):
        sys.modules.pop(name, None)
    import auth
    monkeypatch.setattr(auth, "get_client", lambda: make_client(nonempty, role))
    import metrics
    for key in ("prometheus_reachable", "targets_up", "get_latency_p95_ms", "get_request_rate", "get_error_rate_pct",
                "get_request_rate_series", "get_checkin_success_rate_pct"):
        value = False if key == "prometheus_reachable" else {} if key == "targets_up" else ([], []) if key == "get_request_rate_series" else None
        monkeypatch.setattr(metrics, key, lambda *a, result=value, **kw: result)
    for file in PAGES:
        # Admin-only pages must not execute for TA and instructor.
        try:
            runpy.run_path(str(file), run_name="__main__")
        except StopPage:
            assert (file.name.startswith("8_") or file.name.startswith("4_")
                    or file.name.startswith("7_")  # no courses or TA edit gate
                    or (role != "admin" and file.name.startswith("5_"))
                    or (role == "ta" and file.name.startswith("6_")))
    expected_errors = ("Could not reach Prometheus", "This page requires one of these roles")
    unexpected = [e for e in fake.errors if not e.startswith(expected_errors)]
    assert not unexpected, "Unexpected UI API errors: " + "; ".join(unexpected)


def test_create_session_action_uses_singapore_offset(monkeypatch):
    fake = FakeStreamlit({"role": "instructor", "id": "i1", "email": "i@example.edu"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth
    client = make_client(nonempty=True, role="instructor")
    client.post.return_value = {"name": "Practice Lab", "status": "scheduled"}
    monkeypatch.setattr(auth, "get_client", lambda: client)
    fake.form_submit_button = lambda label, **kw: label == "Create session"
    previous_text = fake.text_input
    fake.text_input = lambda label, **kw: "Practice Lab" if label == "Session name" else previous_text(label, **kw)
    runpy.run_path(str(APP_DIR / "pages/2_Sessions.py"))
    args, kwargs = client.post.call_args
    assert args == ("/sessions/",)
    assert kwargs["json"]["scheduled_start"].endswith("+08:00")
    assert kwargs["json"]["scheduled_end"].endswith("+08:00")


def test_approve_flagged_queue_requires_review_notes(monkeypatch):
    fake = FakeStreamlit({"role": "instructor", "id": "i1", "email": "i@example.edu"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth
    client = make_client(nonempty=True, role="instructor")
    client.post.return_value = {"status": "approved"}
    monkeypatch.setattr(auth, "get_client", lambda: client)
    fake.button = lambda label, **kw: label == "✅ Approve"
    fake.text_area = lambda label, **kw: "Reviewed and verified against class record"
    with pytest.raises(RuntimeError, match="rerun"):
        runpy.run_path(str(APP_DIR / "pages/3_Checkins.py"))
    args, kwargs = client.post.call_args
    assert args == ("/checkins/i1/review",)
    assert kwargs["json"] == {"status": "approved", "review_notes": "Reviewed and verified against class record"}


def test_empty_review_notes_do_not_submit(monkeypatch):
    fake = FakeStreamlit({"role": "instructor", "id": "i1", "email": "i@example.edu"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth
    client = make_client(nonempty=True, role="instructor")
    monkeypatch.setattr(auth, "get_client", lambda: client)
    fake.button = lambda label, **kw: label == "✅ Approve"
    runpy.run_path(str(APP_DIR / "pages/3_Checkins.py"))
    client.post.assert_not_called()
    assert any("Review notes are required" in x for x in fake.errors)
