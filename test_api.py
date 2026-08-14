"""API smoke tests (no external services required for health)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth_demo import resolve_preview_username

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "capeigen-api"


def test_me_requires_auth() -> None:
    response = client.get("/api/me")
    assert response.status_code == 401


def test_preview_login_rejects_unknown_username() -> None:
    response = client.post("/api/auth/demo", json={"username": "notARealUser"})
    assert response.status_code == 403
    assert "Unknown" in response.json()["detail"]


def test_preview_login_rejects_invalid_username() -> None:
    response = client.post("/api/auth/demo", json={"username": "bad name!"})
    assert response.status_code in {403, 422}


def test_preview_username_allowlist() -> None:
    assert resolve_preview_username("salifT") == "salifT"
    assert resolve_preview_username("salift") == "salifT"
    assert resolve_preview_username("nope") is None


def test_preview_events_require_auth() -> None:
    response = client.post("/api/preview/events", json={"event_type": "page_view"})
    assert response.status_code == 401


def test_preview_activity_requires_auth() -> None:
    response = client.get("/api/preview/activity")
    assert response.status_code == 401
