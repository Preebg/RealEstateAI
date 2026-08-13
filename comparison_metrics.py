"""Property comparison metric builders (shared by API PDF export and tests)."""

from __future__ import annotations

from typing import Any

from engine import calculate_quantum_risk, safe_float
from finance import analyze_investment, calculate_10yr_appreciation, calculate_one_year_roi
from knowledge_base import (
    get_effective_display_maint,
    get_effective_display_management_fee,
    get_effective_display_rent,
    get_effective_display_vacancy,
)

DEFAULT_CLOSING_COSTS_PCT = 3.0

COMPARISON_METRICS: list[tuple[str, str, str, bool]] = [
    # (label, field_key, format_kind, higher_is_better)
    ("List Price", "price", "currency", False),
    ("Monthly Rent", "monthly_rent", "currency", True),
    ("Monthly Net Cash Flow", "monthly_net_cash_flow", "currency", True),
    ("Cap Rate", "cap_rate", "percent", True),
    ("Cash on Cash", "cash_on_cash", "percent", True),
    ("1-Year ROI", "one_year_roi", "percent", True),
    ("10-Yr Growth Rate", "forecast_rate", "percent", True),
    ("10-Yr Forecast Value", "appreciation_forecast", "currency", True),
    ("Location Score", "location_score", "score", True),
    ("Quantum Alignment Score", "quantum_overall", "percent", True),
    ("Cash Flow Success", "quantum_cashflow", "percent", True),
    ("Appreciation Success", "quantum_appreciation", "percent", True),
    ("Combined Wealth Success", "quantum_combined", "percent", True),
    ("Strategy", "strategy", "text", False),
]


def _format_metric_value(value: Any, kind: str) -> str:
    if value is None or value == "":
        return "—"
    if kind == "text":
        return str(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "currency":
        return f"${num:,.0f}"
    if kind == "percent":
        return f"{num:.2f}%"
    if kind == "score":
        return f"{num:.1f}/10"
    return f"{num:,.2f}"


def build_property_comparison_metrics(
    prop: dict[str, Any],
    *,
    down_payment_pct: float = 25.0,
    interest_rate: float = 6.0,
    loan_term: int = 30,
    closing_costs_pct: float = DEFAULT_CLOSING_COSTS_PCT,
) -> dict[str, Any]:
    """Compute underwriting metrics for one saved property using user assumptions."""
    price = safe_float(prop.get("price"))
    monthly_rent = get_effective_display_rent(prop)
    maint_percent = get_effective_display_maint(prop)
    vacancy_rate = get_effective_display_vacancy(prop)
    management_fee = get_effective_display_management_fee(prop)
    tax_rate = safe_float(prop.get("tax_rate"))
    monthly_insurance = safe_float(prop.get("insurance"))
    monthly_hoa = safe_float(prop.get("hoa"))
    location_score = safe_float(prop.get("location_score"), 5.0)
    predicted_value = safe_float(prop.get("predicted_value")) or price

    analysis = analyze_investment(
        price=price,
        down_payment_pct=down_payment_pct,
        interest_rate=interest_rate,
        loan_term=int(loan_term),
        closing_costs_pct=closing_costs_pct,
        tax_rate=tax_rate,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_hoa,
        maint_percent=maint_percent,
        monthly_rent=monthly_rent,
        vacancy_reserve_pct=vacancy_rate,
        management_fee_pct=management_fee,
    )

    forecast = calculate_10yr_appreciation(
        predicted_value,
        location_score,
        prop.get("market_city"),
    )
    forecast_rate = safe_float(prop.get("forecast_rate")) or forecast["annual_rate"]
    appreciation_forecast = (
        safe_float(prop.get("appreciation_forecast")) or forecast["future_value"]
    )

    monthly_net_cash_flow = analysis["monthly_net_cash_flow"]
    quantum = calculate_quantum_risk(
        monthly_net_cash_flow,
        forecast_rate,
        location_score,
    )
    one_year_roi = calculate_one_year_roi(
        current_price=price,
        predicted_value=predicted_value,
        forecast_rate_pct=forecast_rate,
        monthly_net_cash_flow=monthly_net_cash_flow,
        down_payment_pct=down_payment_pct,
        closing_costs_pct=closing_costs_pct,
    )

    strategy = (
        prop.get("property_category")
        or prop.get("property_label")
        or "—"
    )

    return {
        "address": str(prop.get("address") or "Unknown"),
        "property_id": str(prop.get("id") or ""),
        "price": price,
        "monthly_rent": monthly_rent,
        "monthly_net_cash_flow": monthly_net_cash_flow,
        "cap_rate": analysis["cap_rate"],
        "cash_on_cash": analysis["cash_on_cash"],
        "one_year_roi": one_year_roi,
        "forecast_rate": forecast_rate,
        "appreciation_forecast": appreciation_forecast,
        "location_score": location_score,
        "quantum_overall": quantum["overall_success_pct"],
        "quantum_cashflow": quantum["cashflow_success_pct"],
        "quantum_appreciation": quantum["appreciation_success_pct"],
        "quantum_combined": quantum["combined_wealth_success_pct"],
        "strategy": strategy,
    }
