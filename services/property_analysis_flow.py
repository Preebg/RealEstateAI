"""Orchestrates KB/AI research, finance underwriting, and quantum risk simulation."""

from __future__ import annotations

from typing import Any

from engine import get_final_analysis, get_initial_analysis, safe_float
from finance import analyze_investment
from knowledge_base import lookup_property
from services.deferred_analysis import build_deferred_task_queue


class AnalysisError(Exception):
    """Raised when property research cannot produce a usable listing."""


def start_property_analysis(
    address: str,
    *,
    guest_mode: bool = False,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Headless fast path: KB pull or AI research, then prepare deferred task list.

    Returns ``{property_data, deferred_tasks, from_kb}`` without UI state.
    """
    cleaned = str(address or "").strip()
    if not cleaned:
        raise AnalysisError("Address is required")

    cached = lookup_property(cleaned, user_id=user_id)
    if cached:
        initial_data = cached
        from_kb = True
        research_results = None
    else:
        initial_data, from_kb, research_results = get_initial_analysis(cleaned)

    if not from_kb and safe_float(initial_data.get("price")) == 0:
        raise AnalysisError(
            "The AI could not find a valid listing price. "
            "Please verify the address and try again."
        )

    final_result = get_final_analysis(
        initial_data,
        cleaned,
        research_results,
        skip_comps=True,
    )
    final_result["from_kb"] = from_kb
    final_result["address"] = cleaned
    queue = build_deferred_task_queue(final_result, guest_mode=guest_mode)
    return {
        "property_data": final_result,
        "deferred_tasks": queue,
        "from_kb": from_kb,
    }


def initialize_hitl_baselines(property_info: dict[str, Any], monthly_rent: float, ai_maint_percent: float) -> None:
    """Preserve AI rent/maint baselines on first render (mutates *property_info*)."""
    if property_info.get("original_ai_rent") is None:
        property_info["original_ai_rent"] = monthly_rent
    if property_info.get("original_ai_maint") is None:
        property_info["original_ai_maint"] = ai_maint_percent


def run_finance_analysis(
    *,
    price: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term: int,
    closing_costs_pct: float,
    tax_rate: float,
    monthly_insurance: float,
    monthly_hoa: float,
    maint_percent: float,
    monthly_rent: float,
    vacancy_reserve_pct: float,
    management_fee_pct: float,
) -> dict[str, Any]:
    """Run ``analyze_investment`` and return flattened metrics for display."""
    analysis = analyze_investment(
        price=price,
        down_payment_pct=down_payment_pct,
        interest_rate=interest_rate,
        loan_term=loan_term,
        closing_costs_pct=closing_costs_pct,
        tax_rate=tax_rate,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_hoa,
        maint_percent=maint_percent,
        monthly_rent=monthly_rent,
        vacancy_reserve_pct=vacancy_reserve_pct,
        management_fee_pct=management_fee_pct,
    )
    op_ex = analysis["operating_expenses"]
    return {
        "analysis": analysis,
        "monthly_mortgage": analysis["monthly_mortgage"],
        "user_closing_costs_total": analysis["closing_costs_total"],
        "operating_expenses": op_ex,
        "monthly_taxes": op_ex["monthly_taxes"],
        "calculated_monthly_maint": op_ex["monthly_maintenance"],
        "actual_vacancy_reserve": op_ex["vacancy_reserve"],
        "actual_management_fee": op_ex["management_fee"],
        "total_monthly_expenses": analysis["total_monthly_expenses"],
        "monthly_net_cash_flow": analysis["monthly_net_cash_flow"],
        "total_investment": analysis["total_investment"],
        "cap_rate": analysis["cap_rate"],
        "cash_on_cash": analysis["cash_on_cash"],
    }


def resolve_quantum_risk(property_info: dict[str, Any]) -> dict[str, Any] | None:
    """Return cached quantum scores or None while the background task is pending."""
    cached = property_info.get("quantum_risk")
    if isinstance(cached, dict) and cached:
        return cached
    return None
