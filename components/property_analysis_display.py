"""Metrics, charts, tabs, and detailed breakdown for property analysis."""

from __future__ import annotations

import datetime
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import tldextract

from comps_analysis import MIN_COMPS_FOR_SUMMARY, resolve_market_value
from components.property_comps import (
    _markdown_safe_text,
    ensure_comps_analysis,
    render_property_comps_section,
)
from components.property_share import render_pending_share_clipboard_copy
from services.deferred_analysis import is_task_pending
from components.property_share import render_share_popover
from engine import (
    backfill_year_built_if_needed,
    calculate_property_age_years,
    parse_year_built,
    safe_float,
)
from finance import (
    calculate_10yr_appreciation,
    calculate_one_year_roi,
    calculate_one_year_roi_for_purchase,
    simulate_market_crash,
)
from pdf_generator import generate_property_pdf
from ui_theme import style_matplotlib_chart


def _pending_metric(label: str, *, help_text: str = "") -> None:
    st.metric(label=label, value="Computing…", help=help_text or "Running in the background.")


def _render_market_crash_simulation(
    *,
    price: float,
    predicted_value: float,
    market_city: str | None,
    location_score: float,
    loan_params: dict[str, float],
    assumptions: dict[str, float],
    tax_rate: float,
    monthly_insurance: float,
    monthly_hoa: float,
    finance: dict[str, Any],
) -> None:
    """Interactive stress test: sudden market drop and worsened rental assumptions."""
    with st.expander("📉 Market Crash Simulation", expanded=False):
        st.caption(
            "Model a sudden downturn for **this property** — value drop, rent decline, "
            "and higher vacancy — then compare baseline vs stressed outcomes."
        )

        if not st.session_state.get("run_market_crash_sim"):
            st.info(
                "Stress-test simulation is computed on demand so the main analysis "
                "view loads faster."
            )
            if st.button("Run market crash simulation", key="start_market_crash_sim"):
                st.session_state["run_market_crash_sim"] = True
                st.rerun()
            return

        preset_col1, preset_col2, preset_col3 = st.columns(3)
        with preset_col1:
            if st.button("Mild (−15%)", key="crash_preset_mild", use_container_width=True):
                st.session_state["crash_price_drop"] = 15.0
                st.session_state["crash_rent_decline"] = 10.0
                st.session_state["crash_vacancy_spike"] = 3.0
        with preset_col2:
            if st.button("Moderate (−25%)", key="crash_preset_moderate", use_container_width=True):
                st.session_state["crash_price_drop"] = 25.0
                st.session_state["crash_rent_decline"] = 15.0
                st.session_state["crash_vacancy_spike"] = 5.0
        with preset_col3:
            if st.button("Severe (−40%)", key="crash_preset_severe", use_container_width=True):
                st.session_state["crash_price_drop"] = 40.0
                st.session_state["crash_rent_decline"] = 25.0
                st.session_state["crash_vacancy_spike"] = 8.0

        ctrl1, ctrl2 = st.columns(2)
        with ctrl1:
            crash_year = st.slider(
                "Crash timing (year after purchase)",
                min_value=1,
                max_value=5,
                value=int(st.session_state.get("crash_year", 2)),
                key="crash_year",
                help="Year when the sudden price drop occurs.",
            )
            price_drop_pct = st.slider(
                "Property value drop (%)",
                min_value=5.0,
                max_value=50.0,
                value=float(st.session_state.get("crash_price_drop", 25.0)),
                step=1.0,
                key="crash_price_drop",
            )
        with ctrl2:
            rent_decline_pct = st.slider(
                "Rent decline (%)",
                min_value=0.0,
                max_value=40.0,
                value=float(st.session_state.get("crash_rent_decline", 15.0)),
                step=1.0,
                key="crash_rent_decline",
            )
            vacancy_spike_pct = st.slider(
                "Extra vacancy reserve (%)",
                min_value=0.0,
                max_value=15.0,
                value=float(st.session_state.get("crash_vacancy_spike", 5.0)),
                step=0.5,
                key="crash_vacancy_spike",
                help="Added on top of your current vacancy assumption during the downturn.",
            )

        scenario = simulate_market_crash(
            purchase_price=price,
            predicted_value=predicted_value,
            market_city=market_city,
            location_score=location_score,
            down_payment_pct=loan_params["down_payment"],
            interest_rate=loan_params["interest_rate"],
            loan_term=int(loan_params["loan_term"]),
            closing_costs_pct=assumptions["user_closing_costs_pct"],
            tax_rate=tax_rate,
            monthly_insurance=monthly_insurance,
            monthly_hoa=monthly_hoa,
            maint_percent=assumptions["final_maint_percent"],
            monthly_rent=assumptions["final_monthly_rent"],
            vacancy_reserve_pct=assumptions["user_vacancy_reserve"],
            management_fee_pct=assumptions["user_management_fee"],
            crash_year=crash_year,
            price_drop_pct=price_drop_pct,
            rent_decline_pct=rent_decline_pct,
            vacancy_spike_pct=vacancy_spike_pct,
        )

        st.markdown("#### At crash point")
        crash_col1, crash_col2, crash_col3, crash_col4 = st.columns(4)
        crash_col1.metric(
            "Value before crash",
            f"${scenario['pre_crash_value']:,.0f}",
        )
        crash_col2.metric(
            "Value after crash",
            f"${scenario['crash_value']:,.0f}",
            delta=f"−{price_drop_pct:.0f}%",
            delta_color="inverse",
        )
        crash_col3.metric(
            "Equity at crash",
            f"${scenario['equity_at_crash']:,.0f}",
            delta="Underwater" if scenario["is_underwater"] else "Positive",
            delta_color="inverse" if scenario["is_underwater"] else "normal",
        )
        recovery = scenario["recovery_years"]
        recovery_label = f"{recovery} yrs" if recovery is not None else "N/A"
        crash_col4.metric(
            "Recovery to pre-crash",
            recovery_label,
            help=(
                f"Years to regain pre-crash value at "
                f"{scenario['recovery_rate_pct']:.1f}%/yr recovery rate."
            ),
        )

        if scenario["is_underwater"]:
            st.error(
                f"Loan balance (${scenario['loan_balance_at_crash']:,.0f}) exceeds "
                f"post-crash value — you would owe more than the property is worth."
            )

        st.markdown("#### Baseline vs stressed operations")
        base_cf = finance["monthly_net_cash_flow"]
        stressed_cf = scenario["stressed_monthly_net_cash_flow"]
        cf_delta = stressed_cf - base_cf
        cmp1, cmp2, cmp3 = st.columns(3)
        cmp1.metric(
            "Monthly cash flow",
            f"${stressed_cf:,.0f}",
            delta=f"${cf_delta:+,.0f} vs baseline",
            delta_color="inverse",
        )
        cmp2.metric(
            "Cap rate",
            f"{scenario['stressed_cap_rate']:.2f}%",
            delta=f"{scenario['stressed_cap_rate'] - scenario['baseline_cap_rate']:+.2f}%",
            delta_color="inverse",
        )
        cmp3.metric(
            "Cash on cash",
            f"{scenario['stressed_cash_on_cash']:.2f}%",
            delta=f"{scenario['stressed_cash_on_cash'] - scenario['baseline_cash_on_cash']:+.2f}%",
            delta_color="inverse",
        )

        st.markdown("#### 10-year value path")
        start_year = datetime.datetime.now().year
        years = list(range(start_year, start_year + len(scenario["baseline_value_schedule"])))

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(
            years,
            scenario["baseline_value_schedule"],
            marker="o",
            color="#2ecc71",
            linewidth=2,
            label="Baseline forecast",
        )
        ax.plot(
            years,
            scenario["crash_value_schedule"],
            marker="s",
            color="#e74c3c",
            linewidth=2,
            linestyle="--",
            label="Crash scenario",
        )
        crash_x = years[min(crash_year, len(years) - 1)]
        ax.axvline(crash_x, color="#95a5a6", linestyle=":", alpha=0.8, label="Crash year")
        ax.set_title("Property Value: Baseline vs Market Crash", fontsize=14)
        ax.set_xlabel("Year")
        ax.set_ylabel("Estimated Value ($)")
        ax.ticklabel_format(style="plain", axis="y")
        ax.legend(loc="upper left", fontsize=8)
        style_matplotlib_chart(fig, ax)
        st.pyplot(fig)

        st.info(
            f"**Assumptions:** {price_drop_pct:.0f}% value drop in year {crash_year}, "
            f"{rent_decline_pct:.0f}% rent decline, +{vacancy_spike_pct:.1f}% vacancy. "
            f"Recovery grows at {scenario['recovery_rate_pct']:.1f}%/yr (metro baseline). "
            "Mortgage payment unchanged — based on your purchase price and loan terms."
        )


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
    quantum_risk: dict[str, Any] | None,
    assumptions: dict[str, float],
    finance: dict[str, Any],
    loan_params: dict[str, float],
    total_confidence_pct: int | None,
) -> None:
    """Render the full analysis overview: metrics, tabs, charts, and expanders."""
    property_info = backfill_year_built_if_needed(property_info, address)
    property_info = ensure_comps_analysis(property_info)
    final_monthly_rent = assumptions["final_monthly_rent"]
    price = safe_float(property_info.get("price"))
    monthly_HOA = safe_float(property_info.get("hoa"))
    monthly_insurance = safe_float(property_info.get("insurance"))

    predicted_value = safe_float(property_info.get("predicted_value"))
    market_value = resolve_market_value(property_info)
    comps_analysis = property_info.get("comps_analysis") or {}
    has_comp_market_value = (
        isinstance(comps_analysis, dict)
        and int(comps_analysis.get("comp_count") or 0) >= MIN_COMPS_FOR_SUMMARY
        and safe_float(comps_analysis.get("comp_suggested_value")) > 0
    )
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
            property_info=property_info,
            address=address,
        )
    render_pending_share_clipboard_copy()

    quantum_ready = isinstance(quantum_risk, dict) and bool(quantum_risk)
    with header_col2:
        if quantum_ready:
            st.metric(
                label="⚛️ Cash Flow Success",
                value=f"{quantum_risk['cashflow_success_pct']:.1f}%",
                help="QAOA alignment with positive cash-flow targets (0–100%).",
            )
        else:
            _pending_metric(
                "⚛️ Cash Flow Success",
                help_text="QAOA alignment with positive cash-flow targets (0–100%).",
            )
    with header_col3:
        if quantum_ready:
            st.metric(
                label="📈 Appreciation Success",
                value=f"{quantum_risk['appreciation_success_pct']:.1f}%",
                help="QAOA alignment with appreciation forecast targets (0–100%).",
            )
        else:
            _pending_metric(
                "📈 Appreciation Success",
                help_text="QAOA alignment with appreciation forecast targets (0–100%).",
            )

    qcol1, qcol2 = st.columns(2)
    with qcol1:
        if quantum_ready:
            st.metric(
                label="💰 Combined Wealth Success",
                value=f"{quantum_risk['combined_wealth_success_pct']:.1f}%",
                help="Joint cash-flow and appreciation alignment from QAOA (0–100%).",
            )
        else:
            _pending_metric(
                "💰 Combined Wealth Success",
                help_text="Joint cash-flow and appreciation alignment from QAOA (0–100%).",
            )
    with qcol2:
        if quantum_ready:
            st.metric(
                label="⚛️ Quantum Alignment Score",
                value=f"{quantum_risk['overall_success_pct']:.1f}%",
                help="Weighted overall QAOA alignment across cash flow, appreciation, and location.",
            )
        else:
            _pending_metric(
                "⚛️ Quantum Alignment Score",
                help_text="Weighted overall QAOA alignment across cash flow, appreciation, and location.",
            )

    tab1 = st.tabs(["📋 Detailed Metrics"])[0]

    with tab1:
        col1, col2, col3 = st.columns(3)
        col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
        col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
        col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")

        purchase_price = safe_float(assumptions.get("offer_amount")) or price
        forecast_rate = safe_float(property_info.get("forecast_rate"))
        if forecast_rate <= 0:
            live_forecast = property_info.get("_forecast_display_cache")
            if isinstance(live_forecast, dict):
                forecast_rate = safe_float(live_forecast.get("annual_rate"))
        if forecast_rate <= 0:
            forecast_rate = calculate_10yr_appreciation(
                predicted_value or purchase_price,
                location_score,
                market_city,
            )["annual_rate"]

        roi_base_value = predicted_value if predicted_value > 0 else purchase_price
        offer_one_year_roi = calculate_one_year_roi(
            current_price=purchase_price,
            predicted_value=roi_base_value,
            forecast_rate_pct=forecast_rate,
            monthly_net_cash_flow=monthly_net_cash_flow,
            down_payment_pct=down_payment,
            closing_costs_pct=assumptions.get("user_closing_costs_pct", 3.0),
        )
        market_one_year_roi = calculate_one_year_roi_for_purchase(
            purchase_price=market_value,
            predicted_value=roi_base_value,
            forecast_rate_pct=forecast_rate,
            down_payment_pct=down_payment,
            interest_rate=interest_rate,
            loan_term=int(loan_term),
            closing_costs_pct=assumptions.get("user_closing_costs_pct", 3.0),
            tax_rate=safe_float(property_info.get("tax_rate")),
            monthly_insurance=monthly_insurance,
            monthly_hoa=monthly_HOA,
            maint_percent=assumptions.get("final_maint_percent", 0.0),
            monthly_rent=final_monthly_rent,
            vacancy_reserve_pct=assumptions.get("user_vacancy_reserve", 5.0),
            management_fee_pct=assumptions.get("user_management_fee", 10.0),
        )

        roi_col1, roi_col2 = st.columns(2)
        roi_col1.metric(
            "1-Year ROI (Your Offer)",
            f"{offer_one_year_roi:.2f}%",
            help=(
                "Return on cash invested over one year at your offer price: "
                "appreciation gain plus annual cash flow, divided by down payment and closing costs."
            ),
        )
        roi_delta = market_one_year_roi - offer_one_year_roi
        roi_col2.metric(
            "1-Year ROI at Market Value",
            f"{market_one_year_roi:.2f}%",
            delta=f"{roi_delta:+.2f}%" if abs(market_value - purchase_price) >= 1 else None,
            help=(
                "Same calculation assuming you pay comp-implied market value instead of your offer. "
                "Delta shows the impact vs your offer price."
            ),
        )

        st.markdown(f"**Strategy Status:** :blue[{branding_label}]")
        st.subheader("🎯 AI Valuation")
        if has_comp_market_value:
            st.info(
                _markdown_safe_text(
                    f"**Market Value (from comps):** ${market_value:,.2f}\n\n"
                    f"**Reasoning:** {prediction_reasoning}"
                )
            )
        else:
            st.info(
                _markdown_safe_text(
                    f"**Predicted Market Value:** ${predicted_value:,.2f}\n\n"
                    f"**Reasoning:** {prediction_reasoning}\n\n"
                    "_Run **Check Area Comps** below to set market value from nearby sales._"
                )
            )

        render_property_comps_section(
            guest_mode=guest_mode,
            address=address,
            property_info=property_info,
            offer_amount=assumptions.get("offer_amount") or safe_float(property_info.get("price")),
        )

        with st.expander("📈 10-Year Appreciation Forecast"):
            live_forecast = property_info.get("_forecast_display_cache")
            if not isinstance(live_forecast, dict):
                if is_task_pending("forecast_chart"):
                    st.info("Building Monte Carlo appreciation forecast in the background…")
                else:
                    st.info("Forecast chart is not ready yet.")
                live_forecast = None

            if isinstance(live_forecast, dict):
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

        _render_market_crash_simulation(
            price=price,
            predicted_value=predicted_value,
            market_city=market_city,
            location_score=location_score,
            loan_params=loan_params,
            assumptions=assumptions,
            tax_rate=safe_float(property_info.get("tax_rate")),
            monthly_insurance=monthly_insurance,
            monthly_hoa=monthly_HOA,
            finance=finance,
        )

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
            "Offer Amount": f"${assumptions.get('offer_amount', price):,.0f}",
            "Down Payment": loan_params.get("down_payment_label")
            or f"{down_payment:.1f}%",
            "Interest Rate": f"{interest_rate}%",
            "Loan Term": f"{int(loan_term)} Years",
        }

        pdf_metrics = {
            "Risk-Adjusted Cap Rate": f"{cap_rate:.2f}%",
            "Cash on Cash Return": f"{cash_on_cash:.2f}%",
            "Monthly Net Cash Flow": f"${monthly_net_cash_flow:,.2f}",
            "Total Cash Required": f"${total_investment:,.2f}",
        }

        live_forecast = property_info.get("_forecast_display_cache")
        forecast_for_pdf = live_forecast if isinstance(live_forecast, dict) else None

        st.write("---")
        if quantum_ready:
            pdf_bytes = generate_property_pdf(
                address,
                property_info,
                pdf_metrics,
                table_data,
                investment_params,
                location_score,
                quantum_risk=quantum_risk,
                forecast_display=forecast_for_pdf,
            )

            st.download_button(
                label="📩 Download Full PDF Report",
                data=pdf_bytes,
                file_name=f"Analysis_{address.replace(' ', '_')}.pdf",
                mime="application/pdf",
            )
        else:
            st.caption("PDF export unlocks after quantum alignment scores finish computing.")
