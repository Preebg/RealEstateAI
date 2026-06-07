"""Side-by-side comparison of up to four user-saved properties."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from authenticate import get_logged_in_user, render_auth_sidebar
from engine import CLASSICAL_QAOA_DIVERGENCE_HELP, calculate_quantum_risk, safe_float
from finance import analyze_investment, calculate_10yr_appreciation, calculate_one_year_roi
from knowledge_base import (
    get_effective_display_maint,
    get_effective_display_management_fee,
    get_effective_display_rent,
    get_effective_display_vacancy,
    get_user_saved_properties,
    render_user_saved_properties_sidebar,
)
from market_pulse import render_market_pulse
from share_access import is_guest_viewer, render_guest_sidebar
from ui_theme import render_page_hero, style_matplotlib_chart

MAX_COMPARE_PROPERTIES = 4
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
    ("Overall Success (Classical)", "classical_overall", "percent", True),
    ("Overall Success (QAOA)", "quantum_overall", "percent", True),
    ("Cash Flow Success (Classical)", "classical_cashflow", "percent", True),
    ("Cash Flow Success (QAOA)", "quantum_cashflow", "percent", True),
    ("Appreciation Success (Classical)", "classical_appreciation", "percent", True),
    ("Appreciation Success (QAOA)", "quantum_appreciation", "percent", True),
    ("Combined Wealth (Classical)", "classical_combined", "percent", True),
    ("Combined Wealth (QAOA)", "quantum_combined", "percent", True),
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
        "classical_overall": quantum["classical_overall_success_pct"],
        "classical_cashflow": quantum["classical_cashflow_success_pct"],
        "classical_appreciation": quantum["classical_appreciation_success_pct"],
        "classical_combined": quantum["classical_combined_wealth_success_pct"],
        "strategy": strategy,
    }


def _short_address(address: str, max_len: int = 32) -> str:
    text = str(address or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _build_comparison_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Metrics as rows, properties as columns (formatted strings)."""
    columns = [_short_address(row["address"]) for row in rows]
    data: dict[str, list[str]] = {"Metric": []}
    for col in columns:
        data[col] = []

    for label, field_key, fmt_kind, _ in COMPARISON_METRICS:
        data["Metric"].append(label)
        for row in rows:
            data[_short_address(row["address"])].append(
                _format_metric_value(row.get(field_key), fmt_kind)
            )

    return pd.DataFrame(data).set_index("Metric")


def _style_comparison_table(display_df: pd.DataFrame, rows: list[dict[str, Any]]):
    """Green-highlight the winning value on each numeric metric row."""

    def _row_style(row: pd.Series) -> list[str]:
        metric_label = row.name
        spec = next((s for s in COMPARISON_METRICS if s[0] == metric_label), None)
        if not spec or spec[2] == "text":
            return [""] * len(row)

        _, field_key, _, higher_is_better = spec
        values: list[float | None] = []
        for item in rows:
            try:
                values.append(float(item.get(field_key)))
            except (TypeError, ValueError):
                values.append(None)

        valid = [v for v in values if v is not None]
        if not valid or len(set(valid)) == 1:
            return [""] * len(row)

        target = max(valid) if higher_is_better else min(valid)
        return [
            "background-color: rgba(46, 204, 113, 0.28); font-weight: 600;"
            if v is not None and v == target
            else ""
            for v in values
        ]

    return display_df.style.apply(_row_style, axis=1)


def _render_comparison_charts(rows: list[dict[str, Any]]) -> None:
    chart_specs = [
        ("Monthly Net Cash Flow ($)", "monthly_net_cash_flow", "currency"),
        ("1-Year ROI (%)", "one_year_roi", "percent"),
        ("Quantum Alignment Score (%)", "quantum_overall", "percent"),
        ("10-Yr Growth Rate (%)", "forecast_rate", "percent"),
    ]
    labels = [_short_address(row["address"], 24) for row in rows]

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    fig.suptitle("Saved Property Comparison", fontsize=14, fontweight="bold")

    for ax, (title, key, _) in zip(axes.flatten(), chart_specs):
        values = [safe_float(row.get(key)) for row in rows]
        colors = ["#3498db", "#2ecc71", "#9b59b6", "#e67e22"][: len(values)]
        bars = ax.bar(labels, values, color=colors)
        ax.set_title(title, fontsize=11)
        ax.tick_params(axis="x", rotation=20, labelsize=8)
        for bar, val in zip(bars, values):
            if key == "monthly_net_cash_flow":
                label = f"${val:,.0f}"
            else:
                label = f"{val:.1f}%"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                label,
                ha="center",
                va="bottom",
                fontsize=8,
            )
        style_matplotlib_chart(fig, ax)

    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render_property_compare_page() -> None:
    """Compare up to four saved properties on cash flow, appreciation, and alignment scores."""
    render_page_hero(
        "⚖️ Compare Saved Properties",
        "Pick up to four bookmarks and compare cash flow, appreciation, and hybrid optimization scores side by side.",
    )

    if is_guest_viewer():
        st.info("Sign in to compare properties saved to your personal account.")
        return

    user = get_logged_in_user()
    if not user:
        st.warning("Sign in to compare your saved properties.")
        return

    with st.sidebar:
        render_auth_sidebar()
        render_user_saved_properties_sidebar()
        st.divider()
        render_market_pulse()
        st.divider()
        st.header("Comparison Assumptions")
        down_payment = st.number_input(
            "Down Payment (%)", value=25.0, min_value=0.0, max_value=100.0, key="compare_down"
        )
        loan_term = st.number_input(
            "Loan Term (yrs)", value=30, min_value=1, max_value=40, key="compare_term"
        )
        interest_rate = st.number_input(
            "Mortgage Rate (%)", value=6.0, min_value=0.0, max_value=20.0, key="compare_rate"
        )
        closing_costs = st.number_input(
            "Closing Costs (%)",
            value=DEFAULT_CLOSING_COSTS_PCT,
            min_value=0.0,
            max_value=10.0,
            key="compare_closing",
        )

    saved = get_user_saved_properties(user["id"])
    if not saved:
        st.info(
            "You have no saved properties yet. Analyze a property on **Individual Search** "
            "and use **Save to My Account** to build your comparison list."
        )
        return

    address_options = {
        str(prop.get("address") or "Unknown"): prop for prop in saved if prop.get("address")
    }
    option_labels = list(address_options.keys())

    st.subheader("Select properties")
    selected_addresses = st.multiselect(
        f"Choose up to {MAX_COMPARE_PROPERTIES} saved properties",
        options=option_labels,
        default=option_labels[: min(len(option_labels), MAX_COMPARE_PROPERTIES)],
        help=f"Maximum {MAX_COMPARE_PROPERTIES} properties can be compared at once.",
        key="compare_property_picks",
    )

    if len(selected_addresses) > MAX_COMPARE_PROPERTIES:
        st.warning(
            f"Only the first {MAX_COMPARE_PROPERTIES} selections are shown. "
            f"Remove extras to compare fewer properties."
        )
        selected_addresses = selected_addresses[:MAX_COMPARE_PROPERTIES]

    if not selected_addresses:
        st.caption("Select at least one property to compare.")
        return

    selected_props = [address_options[addr] for addr in selected_addresses]
    comparison_rows = [
        build_property_comparison_metrics(
            prop,
            down_payment_pct=down_payment,
            interest_rate=interest_rate,
            loan_term=int(loan_term),
            closing_costs_pct=closing_costs,
        )
        for prop in selected_props
    ]

    table_tab, chart_tab = st.tabs(["📊 Metrics Table", "📈 Charts"])

    with table_tab:
        st.caption(
            "Green highlights show the best value in each row "
            "(higher is better for returns and alignment scores). "
            + CLASSICAL_QAOA_DIVERGENCE_HELP
        )
        display_df = _build_comparison_dataframe(comparison_rows)
        styled = _style_comparison_table(display_df, comparison_rows)
        st.dataframe(styled, use_container_width=True)

        best_cash = max(comparison_rows, key=lambda r: r["monthly_net_cash_flow"])
        best_roi = max(comparison_rows, key=lambda r: r["one_year_roi"])
        best_classical = max(comparison_rows, key=lambda r: r["classical_overall"])
        best_quantum = max(comparison_rows, key=lambda r: r["quantum_overall"])
        st.markdown("**Quick picks**")
        st.markdown(
            f"- **Highest cash flow:** {_short_address(best_cash['address'], 48)} "
            f"(${best_cash['monthly_net_cash_flow']:,.0f}/mo)\n"
            f"- **Best 1-year ROI:** {_short_address(best_roi['address'], 48)} "
            f"({best_roi['one_year_roi']:.2f}%)\n"
            f"- **Highest hybrid optimization (classical):** {_short_address(best_classical['address'], 48)} "
            f"({best_classical['classical_overall']:.1f}%)\n"
            f"- **Highest quantum alignment (QAOA):** {_short_address(best_quantum['address'], 48)} "
            f"({best_quantum['quantum_overall']:.1f}%)"
        )

    with chart_tab:
        _render_comparison_charts(comparison_rows)
