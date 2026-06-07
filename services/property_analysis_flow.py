"""Orchestrates KB/AI research, finance underwriting, and quantum risk simulation."""

from __future__ import annotations

import datetime
from typing import Any

import streamlit as st

from engine import calculate_quantum_risk, get_final_analysis, get_initial_analysis, safe_float
from finance import analyze_investment, calculate_10yr_appreciation
from knowledge_base import lookup_property


def run_initial_property_analysis(address: str) -> bool:
    """
    Run KB instant-pull or full AI research for *address*.

    Updates ``st.session_state.property_data`` on success. Returns False when
    analysis cannot proceed (missing price, etc.).
    """
    with st.status("🔍 Researching property and estimating value...") as status:
        cached = lookup_property(address)
        if cached:
            status.update(
                label="⚡ Instant Pull from Knowledge Base",
                state="running",
            )
            initial_data = cached
            from_kb = True
            research_results = None
        else:
            status.update(
                label="🔍 No cache hit — running AI research...",
                state="running",
            )
            initial_data, from_kb, research_results = get_initial_analysis(address)

        if not from_kb and safe_float(initial_data.get("price")) == 0:
            st.error(
                "Error Fetching Property Data... The AI could not find a valid listing "
                "price. Please verify the address and try again."
            )
            st.stop()

        st.markdown("### 📝 AI Property Summary")
        st.write(initial_data.get("summary", "No summary available."))

        loc_score = safe_float(initial_data.get("location_score"))
        pred_val = safe_float(initial_data.get("predicted_value"))
        market_city = initial_data.get("market_city")
        forecast = calculate_10yr_appreciation(pred_val, loc_score, market_city)

        st.subheader("📈 10-Year Appreciation Forecast")
        end_year = datetime.datetime.now().year + 10
        st.write(
            f"**Median estimated value in {end_year}:** "
            f"${forecast['future_value_p50']:,.2f} "
            f"(${forecast['future_value_p10']:,.0f}–${forecast['future_value_p90']:,.0f} range)"
        )
        st.write(
            f"**Expected annual growth (metro + location):** {forecast['annual_rate']:.2f}% "
            f"(10th–90th: {forecast['annual_rate_p10']:.2f}%–{forecast['annual_rate_p90']:.2f}%)"
        )

        status.update(label="✅ Verifying data and calculating ROI...", state="running")
        final_result = get_final_analysis(initial_data, address, research_results)
        st.session_state.property_data = final_result
        done_label = (
            "✅ Loaded from Knowledge Base (Instant Pull)"
            if from_kb
            else "✅ Analysis Complete!"
        )
        status.update(label=done_label, state="complete")
    return True


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


def run_quantum_simulation(
    property_info: dict[str, Any],
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> dict[str, Any]:
    """Run quantum risk simulation and attach results to *property_info*."""
    with st.spinner("⚛️ Running Quantum Simulation..."):
        quantum_risk = calculate_quantum_risk(
            monthly_net_cash_flow,
            forecast_rate,
            location_score,
        )
        property_info["quantum_risk_score"] = quantum_risk["overall_success_pct"]
        property_info["quantum_risk"] = quantum_risk
    return quantum_risk
