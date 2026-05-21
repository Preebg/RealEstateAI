# knowledge_base.py
from __future__ import annotations

import os
from typing import Any

import pandas as pd

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

from supabase import create_client


def _get_secret(name: str) -> str:
    """Resolve credentials from environment first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    if st is not None:
        try:
            return st.secrets[name]
        except Exception:
            pass
    raise EnvironmentError(
        f"{name} not set. Export it or add to Streamlit secrets."
    )


def get_client():
    """Returns a Supabase client."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    return create_client(url, key)


def get_kb_raw_data() -> dict[str, dict[str, Any]]:
    """Fetches all properties from Supabase."""
    try:
        supabase = get_client()
        response = supabase.table("properties").select("*").execute()
        data = response.data

        if not data:
            return {}

        return {item["address"]: item for item in data}
    except Exception as e:
        print(f"Supabase Fetch Error: {e}")
        return {}


def _clean_numeric(payload: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if key not in payload:
            continue
        val = str(payload[key]).replace("$", "").replace(",", "").strip()
        try:
            payload[key] = float(val)
        except (ValueError, TypeError):
            payload[key] = 0.0


def save_knowledge_base(property_data: dict[str, Any], *, show_errors: bool = True):
    """Saves or updates a property in Supabase."""
    try:
        supabase = get_client()
        payload = property_data.copy()

        _clean_numeric(
            payload,
            [
                "price",
                "rent",
                "tax_rate",
                "location_score",
                "predicted_value",
                "quantum_risk_score",
                "square_footage",
            ],
        )

        if "year" in payload and "year_built" not in payload:
            payload["year_built"] = payload.pop("year")

        allowed_columns = [
            "address",
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
            "quantum_risk_score",
            "sources",
            "market_city",
            "square_footage",
            "property_condition",
        ]

        filtered_payload = {k: v for k, v in payload.items() if k in allowed_columns}

        response = (
            supabase.table("properties")
            .upsert(filtered_payload, on_conflict="address")
            .execute()
        )

        print(f"DEBUG: Success! Row added: {response.data}")
        return response
    except Exception as e:
        print(f"Full Error Detail: {e}")
        if show_errors and st is not None:
            st.error(f"Failed to save to Supabase: {e}")
        return None


def save_harvest_property(property_data: dict[str, Any]) -> Any:
    """Persist a harvested property (Stage 3 output + quantum score)."""
    payload = property_data.copy()
    payload.setdefault("from_kb", True)
    payload.setdefault("property_category", payload.get("property_label", ""))
    return save_knowledge_base(payload, show_errors=False)


def get_kb_context() -> str:
    """Pulls recent examples for the LLM."""
    try:
        supabase = get_client()
        response = (
            supabase.table("properties")
            .select("address, rent, predicted_value, market_city")
            .limit(3)
            .execute()
        )
        if not response.data:
            return ""

        context = "\n--- RECENT ANALYSES ---\n"
        for item in response.data:
            market = item.get("market_city") or "Unknown"
            context += (
                f"Address: {item['address']} | Market: {market} | "
                f"Predicted: {item.get('predicted_value')}\n"
            )
        return context
    except Exception:
        return ""


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


def get_market_pulse() -> dict[str, dict[str, Any]]:
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

    raw = get_kb_raw_data()
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
        labels = [str(r.get("property_label") or "") for r in records if r.get("property_label")]

        pulse[city] = {
            "count": len(records),
            "avg_price": sum(prices) / len(prices) if prices else 0.0,
            "avg_quantum": sum(quantums) / len(quantums) if quantums else 0.0,
            "avg_rent": sum(rents) / len(rents) if rents else 0.0,
            "top_label": max(set(labels), key=labels.count) if labels else "—",
        }

    return pulse


def render_market_pulse() -> None:
    """Streamlit Market Pulse widget (Rochester vs Syracuse)."""
    if st is None:
        return

    st.subheader("📡 Hot Market Pulse")
    pulse = get_market_pulse()
    col_r, col_s = st.columns(2)

    for col, city in ((col_r, "Rochester"), (col_s, "Syracuse")):
        stats = pulse[city]
        with col:
            st.markdown(f"**{city}, NY**")
            st.metric("Properties Tracked", stats["count"])
            st.metric("Avg List Price", f"${stats['avg_price']:,.0f}")
            st.metric("Avg Quantum Score", f"{stats['avg_quantum']:.1f}%")
            st.caption(f"Top strategy: {stats['top_label']}")
