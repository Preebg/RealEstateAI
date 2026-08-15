"""API smoke tests (no external services required for health)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

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


def test_preview_username_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import preview_usernames

    monkeypatch.setattr(preview_usernames, "_db_username_rows", lambda: [])
    monkeypatch.setattr(
        preview_usernames,
        "env_username_map",
        lambda: {"salift": "salifT"},
    )
    assert resolve_preview_username("salifT") == "salifT"
    assert resolve_preview_username("salift") == "salifT"
    assert resolve_preview_username("nope") is None


def test_preview_events_require_auth() -> None:
    response = client.post("/api/preview/events", json={"event_type": "page_view"})
    assert response.status_code == 401


def test_preview_activity_requires_auth() -> None:
    response = client.get("/api/preview/activity")
    assert response.status_code == 401


def test_usage_summary_requires_auth() -> None:
    response = client.get("/api/usage/summary")
    assert response.status_code == 401


def test_usage_activity_requires_auth() -> None:
    response = client.get("/api/usage/activity")
    assert response.status_code == 401


def test_legal_document_is_public() -> None:
    response = client.get("/api/legal/privacy")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "privacy"
    assert "Usage analytics" in body["body"]
    assert body["title"]


def test_legal_document_unknown_slug() -> None:
    response = client.get("/api/legal/cookies")
    assert response.status_code == 404


def test_legal_update_requires_auth() -> None:
    response = client.put("/api/legal/privacy", json={"body": "x" * 50})
    assert response.status_code == 401


def test_actor_for_registered_user() -> None:
    from api.preview_activity import actor_for_user

    label, is_preview = actor_for_user(
        {"id": "abc", "email": "investor@example.com", "app_metadata": {}}
    )
    assert label == "investor@example.com"
    assert is_preview is False


def test_preview_accounts_require_auth() -> None:
    response = client.get("/api/preview/accounts")
    assert response.status_code == 401
    response = client.post("/api/preview/accounts", json={"username": "newDemo"})
    assert response.status_code == 401
    response = client.delete("/api/preview/accounts/newDemo")
    assert response.status_code == 401


def test_removed_username_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import preview_usernames

    monkeypatch.setattr(
        preview_usernames,
        "env_username_map",
        lambda: {"salift": "salifT", "newdemo": "newDemo"},
    )
    monkeypatch.setattr(
        preview_usernames,
        "_db_username_rows",
        lambda: [
            {
                "username_key": "newdemo",
                "username": "newDemo",
                "active": False,
            }
        ],
    )
    assert resolve_preview_username("salifT") == "salifT"
    assert resolve_preview_username("newDemo") is None


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
    assert item["app_view_count"] == 0


def test_property_view_requires_auth() -> None:
    response = client.post(
        "/api/properties/view",
        json={"property_id": "7f35bc1e-9de5-484d-8f73-27fd3da733eb"},
    )
    assert response.status_code == 401


def test_property_of_the_day_requires_auth() -> None:
    response = client.get("/api/property-of-the-day")
    assert response.status_code == 401


def test_legal_document_mentions_property_of_the_day() -> None:
    privacy = client.get("/api/legal/privacy")
    assert privacy.status_code == 200
    assert "Property of the Day" in privacy.json()["body"]
    assert "viewership" in privacy.json()["body"].lower()
    terms = client.get("/api/legal/terms")
    assert terms.status_code == 200
    assert "Property of the Day" in terms.json()["body"]


def test_select_property_of_the_day_prefers_cashflow_low_risk_neighborhood() -> None:
    from datetime import date

    from property_popularity import select_property_of_the_day

    properties = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "address": "Negative CF",
            "monthly_net_cash_flow": -50,
            "quantum_risk_score": 90,
            "location_score": 9,
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "address": "Cashflow but high risk",
            "monthly_net_cash_flow": 400,
            "quantum_risk_score": 20,
            "location_score": 8,
        },
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "address": "Best match",
            "monthly_net_cash_flow": 250,
            "quantum_risk_score": 80,
            "location_score": 8.5,
        },
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "address": "Low risk weaker neighborhood",
            "monthly_net_cash_flow": 300,
            "quantum_risk_score": 85,
            "location_score": 4,
        },
    ]
    chosen = select_property_of_the_day(properties, date(2026, 8, 15))
    assert chosen is not None
    assert chosen["address"] == "Best match"


def test_select_property_of_the_day_is_deterministic_for_a_date() -> None:
    from datetime import date

    from property_popularity import select_property_of_the_day

    properties = [
        {
            "id": f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa{i}",
            "address": f"Deal {i}",
            "monthly_net_cash_flow": 200 + i,
            "quantum_risk_score": 70,
            "location_score": 8,
        }
        for i in range(5)
    ]
    first = select_property_of_the_day(properties, date(2026, 1, 1))
    second = select_property_of_the_day(properties, date(2026, 1, 1))
    other = select_property_of_the_day(properties, date(2026, 1, 2))
    assert first is not None and second is not None
    assert first["id"] == second["id"]
    assert other is not None
    assert other["id"] != first["id"] or len(properties) == 1


def test_select_property_of_the_day_returns_none_without_positive_cashflow() -> None:
    from datetime import date

    from property_popularity import select_property_of_the_day

    chosen = select_property_of_the_day(
        [
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "monthly_net_cash_flow": 0,
                "quantum_risk_score": 99,
                "location_score": 10,
            }
        ],
        date(2026, 8, 15),
    )
    assert chosen is None
