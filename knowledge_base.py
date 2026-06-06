# knowledge_base.py
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app_logging import configure_logging, report_error
from authenticate import get_db_client, get_logged_in_user

log = configure_logging("knowledge_base")

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[misc, assignment]


def is_valid_uuid(value: str | None) -> bool:
    """Return True when value is a well-formed UUID (Supabase auth user id)."""
    if not value or not str(value).strip():
        return False
    try:
        UUID(str(value).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _get_secret(name: str) -> str:
    """Resolve credentials from environment first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    if st is not None and name in st.secrets:
        return str(st.secrets[name])
    raise EnvironmentError(
        f"{name} not set. Export it or add to Streamlit secrets."
    )


def get_admin_uid() -> str | None:
    """
    Admin UID — can read all harvested rows in addition to their own.
    Set ADMIN_USER_ID in Streamlit secrets or environment.
    """
    uid = os.getenv("ADMIN_USER_ID", "").strip()
    if uid:
        return uid if is_valid_uuid(uid) else None
    if st is not None and "ADMIN_USER_ID" in st.secrets:
        secret_uid = str(st.secrets["ADMIN_USER_ID"]).strip()
        return secret_uid if is_valid_uuid(secret_uid) else None
    return None


def get_client():
    """Returns a Supabase client (authenticated when user is logged in)."""
    return get_db_client()


def _resolve_user_id(user_id: str | None) -> str | None:
    if user_id and is_valid_uuid(user_id):
        return str(user_id).strip()
    if os.environ.get("STREAMLIT_RUNTIME_ENV"):
        user = get_logged_in_user()
        return user["id"] if user else None
    return None


def _fetch_properties(user_id: str | None = None) -> list[dict[str, Any]]:
    """Query properties scoped to current user + optional admin UID."""
    uid = _resolve_user_id(user_id)
    if not uid:
        return []

    supabase = get_client()
    admin_uid = get_admin_uid()

    query = supabase.table("properties").select("*")
    if admin_uid and admin_uid != uid:
        query = query.or_(f"user_id.eq.{uid},user_id.eq.{admin_uid}")
    else:
        query = query.eq("user_id", uid)

    try:
        response = query.execute()
    except APIError as exc:
        report_error(log, "kb_fetch_failed", exc, user_id=uid)
        return []
    return response.data or []


def get_kb_raw_data(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Fetch properties for the logged-in user (plus admin rows if configured)."""
    rows = _fetch_properties(user_id)
    if not rows:
        return {}
    return {item["address"]: item for item in rows if item.get("address")}


def lookup_property(address: str, user_id: str | None = None) -> dict[str, Any] | None:
    """Instant Pull: return a cached property for this address if it exists."""
    if not address or not address.strip():
        return None
    normalized = address.strip()
    data = get_kb_raw_data(user_id)
    hit = data.get(normalized)
    if hit:
        record = dict(hit)
        record["from_kb"] = True
        return record
    return None


RENT_OUTLIER_DEVIATION_PCT = 50.0


def compute_rent_deviation_pct(ai_rent: float, user_rent: float) -> float:
    """Percent absolute difference between AI rent and user-adjusted rent."""
    ai = float(ai_rent or 0)
    user = float(user_rent or 0)
    if ai <= 0:
        return 100.0 if user != 0 else 0.0
    return abs(user - ai) / ai * 100.0


def is_rent_outlier(
    ai_rent: float,
    user_rent: float,
    *,
    threshold_pct: float = RENT_OUTLIER_DEVIATION_PCT,
) -> bool:
    return compute_rent_deviation_pct(ai_rent, user_rent) > threshold_pct


def _clean_numeric(payload: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if key not in payload:
            continue
        val = str(payload[key]).replace("$", "").replace(",", "").strip()
        if not val:
            payload[key] = 0.0
            continue
        try:
            payload[key] = float(val)
        except (ValueError, TypeError):
            payload[key] = 0.0


def save_knowledge_base(
    property_data: dict[str, Any],
    user_id: str,
    *,
    show_errors: bool = True,
):
    """Saves or updates a property in Supabase for the given user."""
    if not user_id:
        raise ValueError("user_id is required to save a property.")
    if not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")

    supabase = get_client()
    payload = property_data.copy()
    payload["user_id"] = user_id

    _clean_numeric(
        payload,
        [
            "price",
            "rent",
            "original_ai_rent",
            "original_ai_maint",
            "tax_rate",
            "location_score",
            "predicted_value",
            "quantum_risk_score",
            "square_footage",
            "appreciation_forecast",
            "forecast_rate",
            "forecast_growth",
            "ai_vacancy_rate",
            "ai_management_fee",
            "monthly_net_cash_flow",
        ],
    )

    payload.setdefault("is_outlier", False)
    payload.setdefault("from_kb", False)
    if payload.get("override_notes") is None:
        payload["override_notes"] = ""

    if "year" in payload and "year_built" not in payload:
        payload["year_built"] = payload.pop("year")

    allowed_columns = [
        "address",
        "user_id",
        "price",
        "year_built",
        "rent",
        "tax_rate",
        "hoa",
        "insurance",
        "summary",
        "maint_percent",
        "predicted_value",
        "prediction_reasoning",
        "location_score",
        "property_label",
        "property_category",
        "from_kb",
        "quantum_risk_score",
        "sources",
        "market_city",
        "square_footage",
        "property_condition",
        "appreciation_forecast",
        "forecast_rate",
        "forecast_growth",
        "ai_vacancy_rate",
        "ai_management_fee",
        "monthly_net_cash_flow",
        "original_ai_rent",
        "original_ai_maint",
        "is_outlier",
        "override_notes",
    ]

    filtered_payload = {k: v for k, v in payload.items() if k in allowed_columns}

    try:
        response = (
            supabase.table("properties")
            .upsert(filtered_payload, on_conflict="address")
            .execute()
        )
    except APIError as exc:
        report_error(
            log,
            "kb_save_failed",
            exc,
            user_id=user_id,
            address=filtered_payload.get("address"),
        )
        if show_errors and st is not None:
            st.error(f"Failed to save to Supabase: {exc}")
        return None

    log.info(
        "kb_save_success",
        user_id=user_id,
        address=filtered_payload.get("address"),
    )
    return response


def save_harvest_property(
    property_data: dict[str, Any], user_id: str | None = None
) -> Any:
    """
    Persist a harvested property (Stage 3 output + quantum score).
    Pass user_id=get_admin_uid() from the harvester for explicit admin attribution.
    """
    uid = _resolve_user_id(user_id) or get_admin_uid()
    if not uid:
        log.warning("harvest_save_skipped", reason="no_user_id")
        return None

    payload = property_data.copy()
    payload.setdefault("from_kb", True)
    payload.setdefault("property_category", payload.get("property_label", ""))
    return save_knowledge_base(payload, user_id=uid, show_errors=False)


def get_kb_context(user_id: str | None = None) -> str:
    """Pull recent examples for the LLM (scoped to current user)."""
    rows = _fetch_properties(user_id)[:3]
    if not rows:
        return ""

    context = "\n--- RECENT ANALYSES ---\n"
    for item in rows:
        market = item.get("market_city") or "Unknown"
        context += (
            f"Address: {item['address']} | Market: {market} | "
            f"Predicted: {item.get('predicted_value')}\n"
        )
    return context


def _infer_market_city(record: dict[str, Any]) -> str | None:
    explicit = record.get("market_city")
    if explicit in ("Rochester", "Syracuse"):
        return explicit
    address = str(record.get("address", "")).lower()
    if "rochester" in address:
        return "Rochester"
    if "syracuse" in address:
        return "Syracuse"
    return None


def get_market_pulse(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Aggregate Rochester vs Syracuse stats for UI 'Market Pulse'.
    """
    empty = {
        "count": 0,
        "avg_price": 0.0,
        "avg_quantum": 0.0,
        "avg_rent": 0.0,
        "top_label": "—",
    }
    pulse = {"Rochester": dict(empty), "Syracuse": dict(empty)}

    raw = get_kb_raw_data(user_id)
    buckets: dict[str, list[dict[str, Any]]] = {"Rochester": [], "Syracuse": []}

    for record in raw.values():
        city = _infer_market_city(record)
        if city in buckets:
            buckets[city].append(record)

    for city, records in buckets.items():
        if not records:
            continue
        prices = [float(r.get("price") or 0) for r in records]
        quantums = [float(r.get("quantum_risk_score") or 0) for r in records]
        rents = [float(r.get("rent") or 0) for r in records]
        labels = [
            str(r.get("property_label") or "") for r in records if r.get("property_label")
        ]

        pulse[city] = {
            "count": len(records),
            "avg_price": sum(prices) / len(prices) if prices else 0.0,
            "avg_quantum": sum(quantums) / len(quantums) if quantums else 0.0,
            "avg_rent": sum(rents) / len(rents) if rents else 0.0,
            "top_label": max(set(labels), key=labels.count) if labels else "—",
        }

    return pulse


def get_telemetry_stats(user_id: str | None = None) -> dict[str, Any]:
    """
    HITL accuracy: mean absolute error between original_ai_rent and final saved rent.
    Rows flagged is_outlier are excluded.
    """
    rows = _fetch_properties(user_id)
    errors: list[float] = []
    outlier_count = 0
    skipped_no_baseline = 0

    for row in rows:
        if row.get("is_outlier"):
            outlier_count += 1
            continue
        ai_rent = row.get("original_ai_rent")
        final_rent = row.get("rent")
        if ai_rent is None or final_rent is None:
            skipped_no_baseline += 1
            continue
        try:
            errors.append(abs(float(final_rent) - float(ai_rent)))
        except (TypeError, ValueError):
            skipped_no_baseline += 1

    sample_count = len(errors)
    mae_rent = sum(errors) / sample_count if sample_count else None

    return {
        "mae_rent": mae_rent,
        "sample_count": sample_count,
        "outlier_count": outlier_count,
        "skipped_no_baseline": skipped_no_baseline,
        "total_rows": len(rows),
    }


def render_auth_page() -> bool:
    """
    Login / sign-up screen for the app.
    Returns True when the user is authenticated (caller may continue rendering).
    """
    if st is None:
        raise RuntimeError("render_auth_page requires Streamlit.")

    from authenticate import render_login_page

    return render_login_page()


__all__ = [
    "RENT_OUTLIER_DEVIATION_PCT",
    "compute_rent_deviation_pct",
    "is_rent_outlier",
    "is_valid_uuid",
    "get_client",
    "get_admin_uid",
    "get_kb_raw_data",
    "lookup_property",
    "save_knowledge_base",
    "save_harvest_property",
    "get_kb_context",
    "get_market_pulse",
    "get_telemetry_stats",
    "render_auth_page",
]
