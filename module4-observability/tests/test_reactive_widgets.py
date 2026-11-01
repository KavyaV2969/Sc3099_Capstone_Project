"""Use real Streamlit widget semantics to guard against the form-refresh bug."""

from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest


APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_override_window_rerenders_immediately(monkeypatch):
    import sys
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth

    client = Mock()
    course = {"id": "c1", "code": "CS3099", "name": "Capstone", "instructor_id": "i1",
              "geofence_radius_meters": 100.0}

    def get(path, params=None):
        if path == "/courses/":
            return {"items": [course], "total": 1}
        return {"items": [], "total": 0}

    client.get.side_effect = get
    monkeypatch.setattr(auth, "get_client", lambda: client)
    app = AppTest.from_file(str(APP_DIR / "pages/2_Sessions.py"), default_timeout=15)
    app.session_state["access_token"] = "test-token"
    app.session_state["user"] = {"id": "i1", "role": "instructor", "full_name": "Test Instructor"}

    app.run()
    assert not app.exception
    override = next(x for x in app.checkbox if x.label.startswith("Override check-in window"))
    assert not any(x.label == "Check-in opens — date" for x in app.date_input)
    assert next(x for x in app.checkbox if x.label == "Require face match").value is True

    override.check().run()
    assert not app.exception
    assert any(x.label == "Check-in opens — date" for x in app.date_input)
    assert any(x.label == "Check-in closes — date" for x in app.date_input)
    client.post.assert_not_called()


def test_course_semester_dropdown_and_optional_map_mount(monkeypatch):
    import sys
    sys.path.insert(0, str(APP_DIR))
    for name in ("auth", "api_client", "utils"):
        sys.modules.pop(name, None)
    import auth

    client = Mock()
    client.get.return_value = {"items": [], "total": 0}
    monkeypatch.setattr(auth, "get_client", lambda: client)
    app = AppTest.from_file(str(APP_DIR / "pages/6_Courses.py"), default_timeout=15)
    app.session_state["access_token"] = "test-token"
    app.session_state["user"] = {"id": "a1", "role": "admin", "full_name": "Test Admin"}

    app.run()
    assert not app.exception
    semester = next(x for x in app.selectbox if x.label == "Semester")
    assert semester.value.startswith("AY")
    assert "Other / custom semester" in semester.options
    assert next(x for x in app.number_input if x.label == "Venue latitude").value == 1.3483

    next(x for x in app.checkbox if x.label.startswith("🗺️")).check().run()
    assert not app.exception
    client.post.assert_not_called()
