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


def test_portfolio_requires_auth() -> None:
    response = client.get("/api/portfolio")
    assert response.status_code == 401


def test_property_detail_requires_auth() -> None:
    response = client.get("/api/properties/detail", params={"address": "1 Main St"})
    assert response.status_code == 401


def test_portfolio_list_item_uses_ai_rent_and_timestamp() -> None:
    from api.routes.properties import _portfolio_list_item

    item = _portfolio_list_item(
        {
            "id": "7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            "address": "1 Oak St",
            "original_ai_rent": 1400,
            "monthly_net_cash_flow": 250,
            "square_footage": 1200,
            "timestamp": "2026-08-14T12:00:00+00:00",
        }
    )
    assert item["rent"] == 1400
    assert item["monthly_cash_flow"] == 250
    assert item["sqft"] == 1200
    assert item["added_at"] == "2026-08-14T12:00:00+00:00"
