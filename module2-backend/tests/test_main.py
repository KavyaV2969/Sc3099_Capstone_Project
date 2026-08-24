"""FastAPI shell tests."""

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_health_reports_healthy_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(main, "database_is_healthy", lambda: True)
    monkeypatch.setattr(main, "redis_is_healthy", lambda: True)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "backend",
        "api": "healthy",
        "database": "healthy",
        "redis": "healthy",
    }


def test_health_reports_unavailable_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(main, "database_is_healthy", lambda: False)
    monkeypatch.setattr(main, "redis_is_healthy", lambda: True)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "unhealthy"


def test_openapi_document_is_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "SAIV Backend API"


def test_week_two_auth_routes_are_exposed() -> None:
    openapi = client.get("/openapi.json").json()

    assert "/api/v1/auth/register" in openapi["paths"]
    assert "/api/v1/auth/login" in openapi["paths"]
    assert "/api/v1/auth/refresh" in openapi["paths"]
    assert "/api/v1/users/me" in openapi["paths"]


def test_frontend_cors_preflight() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_dashboard_cors_preflight() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8501"
