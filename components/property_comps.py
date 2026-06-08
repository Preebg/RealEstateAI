"""UI for comparable-property valuation cross-check."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from comps_analysis import evaluate_comps_against_subject
from engine import fetch_comparable_properties, safe_float
from services.deferred_analysis import is_task_pending


def _markdown_safe_text(text: str) -> str:
    """Escape ``$`` so Streamlit info/warning boxes render currency as plain text."""
    return text.replace("$", r"\$")


def _comps_table_rows(comps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for comp in comps:
        sqft = comp.get("square_footage")
        price = safe_float(comp.get("sale_price"))
        ppsf = f"${price / sqft:,.0f}" if sqft and sqft > 0 and price > 0 else "—"
        rows.append(
            {
                "Address": comp.get("address", "—"),
                "Sale Price": f"${price:,.0f}" if price > 0 else "—",
                "Sale Date": comp.get("sale_date") or "—",
                "Sq Ft": f"{sqft:,}" if sqft else "—",
                "$/Sq Ft": ppsf,
                "Beds": comp.get("bedrooms") or "—",
                "Baths": comp.get("bathrooms") or "—",
                "Distance (mi)": comp.get("distance_miles") or "—",
                "Notes": comp.get("comparison_notes") or "—",
            }
        )
    return rows


def render_property_comps_section(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
) -> None:
    """Show area comps, valuation gap metrics, and optional refresh."""
    st.subheader("🏘️ Comparable Properties Check")
    st.caption(
        "Cross-check the AI valuation against recent nearby sales with similar size, "
        "age, and property type."
    )

    comps_analysis = property_info.get("comps_analysis")
    has_comps = bool(
        isinstance(comps_analysis, dict)
        and comps_analysis.get("comparable_properties")
    )

    refresh_col, _ = st.columns([1, 3])
    with refresh_col:
        run_comps = st.button(
            "Check Area Comps",
            disabled=guest_mode,
            help="Search for recent comparable sales near this property.",
            key="run_area_comps_check",
        )

    if run_comps and address:
        with st.spinner("Searching for comparable sales in the area..."):
            updated = fetch_comparable_properties(address, property_info)
            property_info.update(updated)
            property_info["address"] = address
            property_info.pop("_forecast_display_cache", None)
            property_info.pop("quantum_risk", None)
            property_info.pop("quantum_risk_score", None)
            from knowledge_base import persist_comps_to_canonical

            persist_comps_to_canonical(property_info, show_errors=True)
            st.session_state.property_data = property_info
            st.session_state.quantum_finance_sig = None
            queue = list(st.session_state.get("deferred_tasks") or [])
            for task in ("quantum", "forecast_chart"):
                if task not in queue:
                    queue.append(task)
            st.session_state.deferred_tasks = queue
            st.rerun()

    if not has_comps:
        if is_task_pending("comps"):
            st.info("Searching for comparable sales in the area…")
        else:
            st.info(
                "No comparable sales loaded yet. Click **Check Area Comps** to research "
                "recent nearby sales and verify the AI valuation."
            )
        return

    assert isinstance(comps_analysis, dict)
    comps = list(comps_analysis.get("comparable_properties") or [])

    if comps_analysis.get("is_undervalued"):
        gap = comps_analysis.get("predicted_vs_comps_pct") or comps_analysis.get(
            "list_vs_comps_pct"
        )
        gap_text = f" ({abs(gap):.1f}% below comps)" if gap is not None else ""
        st.warning(
            f"**Possible undervaluation{gap_text}.** "
            "The list price or AI predicted value may be below recent comparable sales. "
            "Review comps below before relying on cash-flow or appreciation metrics."
        )
    elif comps_analysis.get("comp_count", 0) >= 2:
        st.success("Valuation appears broadly aligned with area comparable sales.")

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    median_sale = safe_float(comps_analysis.get("median_sale_price"))
    comp_implied = safe_float(comps_analysis.get("comp_suggested_value"))
    list_price = safe_float(comps_analysis.get("list_price"))
    predicted = safe_float(comps_analysis.get("predicted_value"))

    metric_col1.metric("Median Comp Sale", f"${median_sale:,.0f}" if median_sale else "—")
    metric_col2.metric(
        "Comp-Implied Value",
        f"${comp_implied:,.0f}" if comp_implied else "—",
        help="Median $/sqft × subject sqft when available, else median comp sale price.",
    )
    metric_col3.metric("List Price", f"${list_price:,.0f}" if list_price else "—")
    metric_col4.metric("AI Predicted Value", f"${predicted:,.0f}" if predicted else "—")

    if comps_analysis.get("summary"):
        st.info(_markdown_safe_text(comps_analysis["summary"]))

    if property_info.get("comps_adjusted_predicted_value"):
        st.caption(
            "AI predicted value was adjusted upward using comp-implied value because "
            "it was materially below area sales."
        )

    table_rows = _comps_table_rows(comps)
    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    with st.expander("How this check works"):
        st.markdown(
            _markdown_safe_text(
                """
            1. **Search** — Grounded search finds 3–5 recent sales near the subject with
               similar beds, baths, sqft, and property type.
            2. **Median** — We compute median sale price and median $/sqft across comps.
            3. **Cross-check** — List price and AI `predicted_value` are compared to the
               comp-implied value. A gap **≥ 8% below** comps flags possible undervaluation.
            4. **Adjustment** — When flagged, `predicted_value` is raised to the comp-implied
               value so appreciation and ROI metrics reflect market reality.
            """
            )
        )


def ensure_comps_analysis(property_info: dict[str, Any]) -> dict[str, Any]:
    """Recompute summary fields when comps exist but summary is missing."""
    comps = property_info.get("comps_analysis")
    if not isinstance(comps, dict) or not comps.get("comparable_properties"):
        return property_info

    if comps.get("median_sale_price") is not None and comps.get("summary"):
        return property_info

    refreshed = evaluate_comps_against_subject(
        {
            "comparable_properties": comps.get("comparable_properties"),
            "market_summary": comps.get("market_summary", ""),
        },
        property_info,
    )
    property_info["comps_analysis"] = refreshed
    return property_info
