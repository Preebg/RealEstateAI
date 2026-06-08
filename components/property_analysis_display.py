"""Metrics, charts, tabs, and detailed breakdown for property analysis."""

from __future__ import annotations

import datetime
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import tldextract

from components.property_share import render_share_popover
from engine import (
    backfill_year_built_if_needed,
    calculate_property_age_years,
    parse_year_built,
    safe_float,
)
from finance import calculate_10yr_appreciation
from pdf_generator import generate_property_pdf
from ui_theme import style_matplotlib_chart


def get_pretty_label(url: str) -> str:
    try:
        ext = tldextract.extract(url)
        brand = ext.domain.capitalize()
        if brand and brand != "Google":
            return f"{brand}.{ext.suffix}"
        return "View Source"
    except Exception:
        return "View Source"


def render_analysis_results(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
    property_id: str | None,
    from_kb: bool,
    quantum_risk: dict[str, Any],
    assumptions: dict[str, float],
    finance: dict[str, Any],
    loan_params: dict[str, float],
    total_confidence_pct: int | None,
) -> None:
    """Render the full analysis overview: metrics, tabs, charts, and expanders."""
    property_info = backfill_year_built_if_needed(property_info, address)
    final_monthly_rent = assumptions["final_monthly_rent"]
    price = safe_float(property_info.get("price"))
    monthly_HOA = safe_float(property_info.get("hoa"))
    monthly_insurance = safe_float(property_info.get("insurance"))

    predicted_value = safe_float(property_info.get("predicted_value"))
    prediction_reasoning = property_info.get("prediction_reasoning", "No reasoning provided.")
    location_score = safe_float(property_info.get("location_score"))
    market_city = property_info.get("market_city")
    branding_label = property_info.get("property_label", "Balanced")

    monthly_mortgage = finance["monthly_mortgage"]
    monthly_taxes = finance["monthly_taxes"]
    calculated_monthly_maint = finance["calculated_monthly_maint"]
    actual_vacancy_reserve = finance["actual_vacancy_reserve"]
    actual_management_fee = finance["actual_management_fee"]
    total_monthly_expenses = finance["total_monthly_expenses"]
    monthly_net_cash_flow = finance["monthly_net_cash_flow"]
    total_investment = finance["total_investment"]
    cap_rate = finance["cap_rate"]
    cash_on_cash = finance["cash_on_cash"]

    down_payment = loan_params["down_payment"]
    interest_rate = loan_params["interest_rate"]
    loan_term = loan_params["loan_term"]

    st.divider()
    header_col1, header_col2, header_col3 = st.columns([2, 1, 1])
    with header_col1:
        st.subheader("📊 Analysis Overview")
        share_property_id = property_id
        render_share_popover(
            guest_mode=guest_mode,
            share_property_id=share_property_id,
            from_kb=from_kb,
        )

    with header_col2:
        st.metric(
            label="⚛️ Cash Flow Success",
            value=f"{quantum_risk['cashflow_success_pct']:.1f}%",
            help="QAOA alignment with positive cash-flow targets (0–100%).",
        )
    with header_col3:
        st.metric(
            label="📈 Appreciation Success",
            value=f"{quantum_risk['appreciation_success_pct']:.1f}%",
            help="QAOA alignment with appreciation forecast targets (0–100%).",
        )

    qcol1, qcol2 = st.columns(2)
    with qcol1:
        st.metric(
            label="💰 Combined Wealth Success",
            value=f"{quantum_risk['combined_wealth_success_pct']:.1f}%",
            help="Joint cash-flow and appreciation alignment from QAOA (0–100%).",
        )
    with qcol2:
        st.metric(
            label="⚛️ Quantum Alignment Score",
            value=f"{quantum_risk['overall_success_pct']:.1f}%",
            help="Weighted overall QAOA alignment across cash flow, appreciation, and location.",
        )

    tab1 = st.tabs(["📋 Detailed Metrics"])[0]

    with tab1:
        col1, col2, col3 = st.columns(3)
        col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
        col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
        col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")

        st.markdown(f"**Strategy Status:** :blue[{branding_label}]")
        st.subheader("🎯 AI Valuation")
        st.info(
            f"**Predicted Market Value:** ${predicted_value:,.2f}\n\n"
            f"**Reasoning:** {prediction_reasoning}"
        )

        with st.expander("📈 10-Year Appreciation Forecast"):
            live_forecast = calculate_10yr_appreciation(
                predicted_value, location_score, market_city
            )
            end_year = datetime.datetime.now().year + 10
            metro_label = market_city or "National default"
            st.write(
                f"**Median estimated value in {end_year}:** "
                f"${live_forecast['future_value_p50']:,.2f}"
            )
            st.write(
                f"**Uncertainty band (10th–90th percentile):** "
                f"${live_forecast['future_value_p10']:,.0f} – ${live_forecast['future_value_p90']:,.0f}"
            )
            st.write(
                f"**Expected annual growth:** {live_forecast['annual_rate']:.2f}% "
                f"(metro base {live_forecast['metro_base_rate']:.2f}% "
                f"+ location {live_forecast['location_adjustment']:+.2f}%)"
            )
            st.info(
                f"**Methodology:** Forecast starts from **{metro_label}** historical metro CAGR, "
                f"then adjusts ±1.5%/yr max based on Location Score ({location_score}/10). "
                f"Shaded band reflects Monte Carlo uncertainty on the appreciation rate."
            )

            start_year = datetime.datetime.now().year
            years = list(range(start_year, start_year + 11))
            values_p50 = live_forecast["value_schedule_p50"]
            values_p10 = live_forecast["value_schedule_p10"]
            values_p90 = live_forecast["value_schedule_p90"]

            fig, ax = plt.subplots(figsize=(8, 4))
            ax.fill_between(
                years,
                values_p10,
                values_p90,
                alpha=0.25,
                color="#2ecc71",
                label="10th–90th percentile",
            )
            ax.plot(
                years,
                values_p50,
                marker="o",
                color="#2ecc71",
                linewidth=2,
                label="Median forecast",
            )
            ax.set_title("Projected Property Value Growth (Median + Uncertainty)", fontsize=14)
            ax.set_xlabel("Year")
            ax.set_ylabel("Estimated Value ($)")
            ax.ticklabel_format(style="plain", axis="y")
            ax.legend(loc="upper left", fontsize=8)
            style_matplotlib_chart(fig, ax)

            st.pyplot(fig)

    st.markdown("### 📝 AI Property Summary")
    st.write(property_info.get("summary", "No summary available."))

    with st.expander("View Detailed Monthly Breakdown"):
        if total_confidence_pct is not None:
            st.metric(
                label="Data Confidence",
                value=f"{total_confidence_pct}%",
                help=(
                    "Overall confidence in the scraped and inferred data for this property (0–100%). "
                    "Varies by listing quality: source count, stated rent, tax records, and field completeness."
                ),
            )
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("List Price", f"${price:,.2f}")
        metric_col2.metric("Monthly Rent", f"${final_monthly_rent:,.2f}")
        metric_col3.metric("Property Taxes (monthly)", f"${monthly_taxes:,.2f}")
        st.write("Monthly Cash Flow")

        table_data = {
            "Description": [
                "Gross Monthly Rent",
                "Mortgage Payment (P&I)",
                "Property Taxes",
                "Insurance",
                "HOA Fee",
                "Maintenance (CapEx)",
                "Vacancy Reserve",
                "Management Fee",
                "Total Costs",
                "Cash Flow Monthly",
            ],
            "Amount": [
                f"${final_monthly_rent:,.2f}",
                f"-${monthly_mortgage:,.2f}",
                f"-${monthly_taxes:,.2f}",
                f"-${monthly_insurance:,.2f}",
                f"-${monthly_HOA:,.2f}",
                f"-${calculated_monthly_maint:,.2f}",
                f"-${actual_vacancy_reserve:,.2f}",
                f"-${actual_management_fee:,.2f}",
                f"${total_monthly_expenses:,.2f}",
                f"${monthly_net_cash_flow:,.2f}",
            ],
        }
        df = pd.DataFrame(table_data)
        st.table(df)

        year_built = parse_year_built(property_info)
        property_age = calculate_property_age_years(property_info)
        if property_age is not None and year_built is not None:
            st.info(f"Property Age: {property_age} years (built {year_built}).")
        else:
            st.info("Property Age: Unknown")
        st.info(f"Total Investment: ${total_investment:,.2f}")
        st.caption(
            "Disclaimer: This is an AI-powered tool for educational purposes. "
            "Always verify financial data with a professional before making investment decisions."
        )
        st.sidebar.write(f"💸 Total Cash Required: **${total_investment:,.2f}**")

        investment_params = {
            "Down Payment": f"{down_payment}%",
            "Interest Rate": f"{interest_rate}%",
            "Loan Term": f"{loan_term} Years",
        }

        pdf_metrics = {
            "Risk-Adjusted Cap Rate": f"{cap_rate:.2f}%",
            "Cash on Cash Return": f"{cash_on_cash:.2f}%",
            "Monthly Net Cash Flow": f"${monthly_net_cash_flow:,.2f}",
            "Total Cash Required": f"${total_investment:,.2f}",
        }

        st.write("---")
        pdf_bytes = generate_property_pdf(
            address,
            property_info,
            pdf_metrics,
            table_data,
            investment_params,
            location_score,
            quantum_risk=quantum_risk,
        )

        st.download_button(
            label="📩 Download Full PDF Report",
            data=pdf_bytes,
            file_name=f"Analysis_{address.replace(' ', '_')}.pdf",
            mime="application/pdf",
        )
