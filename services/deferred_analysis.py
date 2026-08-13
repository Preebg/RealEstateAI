"""Deferred heavy computations for property analysis (headless / FastAPI jobs)."""

from __future__ import annotations

from typing import Any

from comps_analysis import property_has_existing_comps
from engine import calculate_quantum_risk, fetch_comparable_properties, safe_float
from finance import calculate_10yr_appreciation

TASK_LABELS: dict[str, str] = {
    "comps": "Checking comparable sales",
    "quantum": "Running quantum alignment simulation",
    "forecast_chart": "Building appreciation forecast chart",
}


def finance_context_from_property(property_info: dict[str, Any]) -> dict[str, Any] | None:
    """Build quantum finance inputs from stored KB / analysis fields."""
    forecast_rate = safe_float(property_info.get("forecast_rate"))
    location_score = safe_float(property_info.get("location_score"))
    monthly_net_cash_flow = safe_float(property_info.get("monthly_net_cash_flow"))
    if forecast_rate or location_score or monthly_net_cash_flow:
        return {
            "monthly_net_cash_flow": monthly_net_cash_flow,
            "forecast_rate": forecast_rate,
            "location_score": location_score,
        }
    return None


def build_deferred_task_queue(
    property_data: dict[str, Any],
    *,
    guest_mode: bool = False,
) -> list[str]:
    """Return ordered list of background tasks still needed for *property_data*."""
    tasks: list[str] = []
    if not guest_mode and not property_has_existing_comps(property_data):
        tasks.append("comps")
    if not property_data.get("quantum_risk"):
        # KB rows store only quantum_risk_score. Hydrate a display stub so the UI
        # is responsive; finance recalc can re-queue a full QAOA refresh later.
        score = safe_float(property_data.get("quantum_risk_score"))
        if score > 0:
            property_data["quantum_risk"] = {
                "overall_success_pct": score,
                "cashflow_success_pct": score,
                "appreciation_success_pct": score,
                "combined_wealth_success_pct": score,
            }
        else:
            tasks.append("quantum")
    if not property_data.get("_forecast_display_cache"):
        tasks.append("forecast_chart")
    return tasks


def finance_task_signature(
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> str:
    return f"{monthly_net_cash_flow:.2f}|{forecast_rate:.4f}|{location_score:.2f}"


def _run_comps_task(address: str, property_info: dict[str, Any]) -> list[str]:
    """Run comps fetch. Returns any newly required follow-up task names."""
    from comps_analysis import ensure_comps_analysis_field

    ensure_comps_analysis_field(property_info)
    updated = fetch_comparable_properties(address, property_info)
    property_info.update(updated)
    property_info["address"] = address
    from knowledge_base import persist_comps_to_canonical

    persist_comps_to_canonical(property_info)
    follow_ups: list[str] = []
    if property_info.pop("_forecast_display_cache", None) is not None:
        follow_ups.append("forecast_chart")
    return follow_ups


def run_comps_task(address: str, property_info: dict[str, Any]) -> list[str]:
    """Public headless comps runner. Mutates *property_info*."""
    return _run_comps_task(address, property_info)


def _run_quantum_task(
    property_info: dict[str, Any],
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> str:
    quantum = calculate_quantum_risk(
        monthly_net_cash_flow,
        forecast_rate,
        location_score,
    )
    property_info["quantum_risk"] = quantum
    property_info["quantum_risk_score"] = quantum["overall_success_pct"]
    return finance_task_signature(
        monthly_net_cash_flow=monthly_net_cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )


def run_quantum_task(
    property_info: dict[str, Any],
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> str:
    """Public headless quantum runner. Returns finance signature string."""
    return _run_quantum_task(
        property_info,
        monthly_net_cash_flow=monthly_net_cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )


def _run_forecast_chart_task(property_info: dict[str, Any]) -> None:
    predicted_value = safe_float(property_info.get("predicted_value"))
    location_score = safe_float(property_info.get("location_score"))
    market_city = property_info.get("market_city")
    property_info["_forecast_display_cache"] = calculate_10yr_appreciation(
        predicted_value,
        location_score,
        market_city,
    )


def run_forecast_chart_task(property_info: dict[str, Any]) -> None:
    """Public headless forecast chart runner."""
    _run_forecast_chart_task(property_info)


def execute_deferred_task(
    task: str,
    *,
    address: str,
    property_info: dict[str, Any],
    finance_context: dict[str, Any] | None,
) -> list[str]:
    """
    Run one deferred task without UI state. Mutates *property_info*.

    Returns follow-up task names that should be appended to the queue.
    """
    if task == "comps":
        return _run_comps_task(address, property_info)
    if task == "quantum":
        ctx = finance_context or finance_context_from_property(property_info)
        if ctx is None:
            raise ValueError("finance_context is required for quantum task")
        _run_quantum_task(
            property_info,
            monthly_net_cash_flow=ctx["monthly_net_cash_flow"],
            forecast_rate=ctx["forecast_rate"],
            location_score=ctx["location_score"],
        )
        return []
    if task == "forecast_chart":
        _run_forecast_chart_task(property_info)
        return []
    raise ValueError(f"Unknown deferred task: {task}")
