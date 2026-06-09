"""Orchestrates KB/AI research, finance underwriting, and quantum risk simulation."""

from __future__ import annotations

from typing import Any

import streamlit as st

from engine import get_final_analysis, get_initial_analysis, safe_float
from finance import analyze_investment
from knowledge_base import lookup_property
from services.deferred_analysis import (
    build_deferred_task_queue,
    set_active_analysis_address,
)


def run_initial_property_analysis(address: str, *, guest_mode: bool = False) -> None:
    """
    Fast path: AI research or KB pull, then defer comps / quantum / charts.

    Sets ``st.session_state.property_data`` and queues background work, then reruns
    so the main analysis page can render before heavy simulations run.
    """
    with st.status("🔍 Researching property and estimating value...", expanded=True) as status:
        cached = lookup_property(address)
        if cached:
            status.update(label="⚡ Instant Pull from Knowledge Base", state="running")
            initial_data = cached
            from_kb = True
            research_results = None
        else:
            status.update(label="🔍 No cache hit — running AI research...", state="running")
            initial_data, from_kb, research_results = get_initial_analysis(address)

        if not from_kb and safe_float(initial_data.get("price")) == 0:
            st.error(
                "Error Fetching Property Data... The AI could not find a valid listing "
                "price. Please verify the address and try again."
            )
            st.stop()

        status.update(label="📋 Preparing analysis view...", state="running")
        final_result = get_final_analysis(
            initial_data,
            address,
            research_results,
            skip_comps=True,
        )
        final_result["from_kb"] = from_kb
        final_result["address"] = address
        set_active_analysis_address(address)

        queue = build_deferred_task_queue(final_result, guest_mode=guest_mode)
        st.session_state.property_data = final_result
        st.session_state.deferred_tasks = queue
        st.session_state.deferred_tasks_total = len(queue)

        done_label = (
            "✅ Loaded from Knowledge Base — opening analysis..."
            if from_kb
            else "✅ Research complete — opening analysis..."
        )
        status.update(label=done_label, state="complete")

    st.rerun()


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
