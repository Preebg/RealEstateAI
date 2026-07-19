"""API smoke tests (no external services required for health)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

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
