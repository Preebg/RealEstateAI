"""UI for comparable-property valuation cross-check."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from comps_analysis import (
    apply_comp_implied_market_value,
    evaluate_comps_against_subject,
    evaluate_offer_success,
    resolve_market_value,
)
from engine import fetch_comparable_properties, fetch_rental_comparables, safe_float


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


def _rent_comps_table_rows(rentals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rental in rentals:
        sqft = rental.get("square_footage")
        rent = safe_float(rental.get("monthly_rent"))
        rpsf = f"${rent / sqft:,.2f}" if sqft and sqft > 0 and rent > 0 else "—"
        rows.append(
            {
                "Address": rental.get("address", "—"),
                "Monthly Rent": f"${rent:,.0f}" if rent > 0 else "—",
                "Lease Date": rental.get("lease_date") or "—",
                "Sq Ft": f"{sqft:,}" if sqft else "—",
                "$/Sq Ft": rpsf,
                "Beds": rental.get("bedrooms") or "—",
                "Baths": rental.get("bathrooms") or "—",
                "Distance (mi)": rental.get("distance_miles") or "—",
                "Notes": rental.get("comparison_notes") or "—",
            }
        )
    return rows


def _render_sales_comps_section(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
    offer_amount: float,
) -> None:
    st.subheader("🏘️ Comparable Sales Check")
    st.caption(
        "Cross-check the listing against recent nearby sales. When enough comps load, "
        "comp-implied value becomes the property's market value."
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
    market_value = resolve_market_value(property_info)
    list_price = safe_float(comps_analysis.get("list_price")) or safe_float(property_info.get("price"))
    offer_analysis = evaluate_offer_success(offer_amount, market_value, list_price)

    if comps_analysis.get("is_undervalued"):
        gap = comps_analysis.get("predicted_vs_comps_pct") or comps_analysis.get(
            "list_vs_comps_pct"
        )
        gap_text = f" ({abs(gap):.1f}% below comps)" if gap is not None else ""
        st.warning(
            f"**Possible undervaluation{gap_text}.** "
            "The list price may be below recent comparable sales — a strong buy signal "
            "if your offer is accepted near list."
        )
    elif comps_analysis.get("comp_count", 0) >= 2:
        st.success("Valuation appears broadly aligned with area comparable sales.")

    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
    median_sale = safe_float(comps_analysis.get("median_sale_price"))
    comp_implied = safe_float(comps_analysis.get("comp_suggested_value"))

    metric_col1.metric(
        "Market Value (Comps)",
        f"${market_value:,.0f}" if market_value else "—",
        help="Comp-implied value — used as the property's market value when enough comps exist.",
    )
    metric_col2.metric("Median Comp Sale", f"${median_sale:,.0f}" if median_sale else "—")
    metric_col3.metric("List Price", f"${list_price:,.0f}" if list_price else "—")
    metric_col4.metric(
        "Your Offer",
        f"${offer_amount:,.0f}" if offer_amount else "—",
        help="Adjust in the sidebar under Your Assumptions.",
    )
    success_pct = offer_analysis.get("success_pct")
    if success_pct is not None:
        metric_col5.metric(
            "Deal Success",
            f"{success_pct:.1f}%",
            help=(
                "How favorable your offer is vs comp-implied market value. "
                "Higher = better buy (offer at or below market)."
            ),
        )
    else:
        metric_col5.metric("Deal Success", "—")

    if offer_analysis.get("message"):
        st.caption(offer_analysis["message"])

    if comps_analysis.get("summary"):
        st.info(_markdown_safe_text(comps_analysis["summary"]))

    if property_info.get("comps_adjusted_predicted_value") and comp_implied > 0:
        st.caption(
            "Market value and predicted value are set from comp-implied value based on "
            "nearby sales."
        )

    table_rows = _comps_table_rows(comps)
    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    with st.expander("How sales comps work"):
        st.markdown(
            _markdown_safe_text(
                """
            1. **Search** — Grounded search finds 3–5 recent sales near the subject with
               similar beds, baths, sqft, and property type.
            2. **Median** — We compute median sale price and median $/sqft across comps.
            3. **Market value** — With at least 2 comps, comp-implied value becomes the
               property's market value and predicted value.
            4. **Deal success** — Your sidebar offer is scored against comp-implied value;
               offers at or below market score higher.
            """
            )
        )


def _render_rent_comps_section(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
) -> None:
    st.subheader("🏠 Comparable Rentals Check")
    st.caption(
        "Verify the AI rent estimate against recent nearby leases and listings with "
        "similar size and property type."
    )

    rent_comps_analysis = property_info.get("rent_comps_analysis")
    has_rent_comps = bool(
        isinstance(rent_comps_analysis, dict)
        and rent_comps_analysis.get("comparable_rentals")
    )

    rent_col, _ = st.columns([1, 3])
    with rent_col:
        run_rent_comps = st.button(
            "Check Rental Comps",
            disabled=guest_mode,
            help="Search for recent comparable rentals near this property.",
            key="run_rent_comps_check",
        )

    if run_rent_comps and address:
        with st.spinner("Searching for comparable rentals in the area..."):
            updated = fetch_rental_comparables(address, property_info)
            property_info.update(updated)
            property_info["address"] = address
            st.session_state.property_data = property_info
            st.session_state.quantum_finance_sig = None
            queue = list(st.session_state.get("deferred_tasks") or [])
            if "quantum" not in queue:
                queue.append("quantum")
            st.session_state.deferred_tasks = queue
            st.rerun()

    if not has_rent_comps:
        st.info(
            "No rental comps loaded yet. Click **Check Rental Comps** to cross-check "
            "the AI rent estimate against nearby leases."
        )
        return

    assert isinstance(rent_comps_analysis, dict)
    rentals = list(rent_comps_analysis.get("comparable_rentals") or [])

    if rent_comps_analysis.get("is_underrented"):
        gap = rent_comps_analysis.get("rent_vs_comps_pct")
        gap_text = f" ({abs(gap):.1f}% below comps)" if gap is not None else ""
        st.warning(
            f"**Possible under-rented listing{gap_text}.** "
            "AI or listing rent may be below nearby comparable rentals."
        )
    elif rent_comps_analysis.get("comp_count", 0) >= 2:
        st.success("Rent appears broadly aligned with area rental comps.")

    rcol1, rcol2, rcol3, rcol4 = st.columns(4)
    median_rent = safe_float(rent_comps_analysis.get("median_monthly_rent"))
    comp_implied_rent = safe_float(rent_comps_analysis.get("comp_suggested_rent"))
    subject_rent = safe_float(rent_comps_analysis.get("subject_rent")) or safe_float(
        property_info.get("rent")
    )

    rcol1.metric(
        "Comp-Implied Rent",
        f"${comp_implied_rent:,.0f}/mo" if comp_implied_rent else "—",
        help="Median $/sqft × subject sqft when available, else median comp rent.",
    )
    rcol2.metric("Median Comp Rent", f"${median_rent:,.0f}/mo" if median_rent else "—")
    rcol3.metric("AI / Listing Rent", f"${subject_rent:,.0f}/mo" if subject_rent else "—")
    gap_pct = rent_comps_analysis.get("rent_vs_comps_pct")
    rcol4.metric(
        "Rent vs Comps",
        f"{gap_pct:+.1f}%" if gap_pct is not None else "—",
        help="Negative = rent below comp-implied market rent (potential upside).",
    )

    if rent_comps_analysis.get("summary"):
        st.info(_markdown_safe_text(rent_comps_analysis["summary"]))

    if property_info.get("rent_comps_adjusted"):
        st.caption(
            "AI rent was adjusted upward using comp-implied rent because it was "
            "materially below area rentals."
        )

    rent_rows = _rent_comps_table_rows(rentals)
    if rent_rows:
        st.dataframe(pd.DataFrame(rent_rows), use_container_width=True, hide_index=True)


def render_property_comps_section(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
    offer_amount: float = 0.0,
) -> None:
    """Show sales comps, deal success, and rental comps cross-checks."""
    _render_sales_comps_section(
        guest_mode=guest_mode,
        address=address,
        property_info=property_info,
        offer_amount=offer_amount,
    )
    st.divider()
    _render_rent_comps_section(
        guest_mode=guest_mode,
        address=address,
        property_info=property_info,
    )


def ensure_comps_analysis(property_info: dict[str, Any]) -> dict[str, Any]:
    """Recompute summary fields when comps exist but summary is missing."""
    comps = property_info.get("comps_analysis")
    if not isinstance(comps, dict) or not comps.get("comparable_properties"):
        return property_info

    if comps.get("median_sale_price") is not None and comps.get("summary"):
        apply_comp_implied_market_value(property_info, comps)
        return property_info

    refreshed = evaluate_comps_against_subject(
        {
            "comparable_properties": comps.get("comparable_properties"),
            "market_summary": comps.get("market_summary", ""),
        },
        property_info,
    )
    property_info["comps_analysis"] = refreshed
    apply_comp_implied_market_value(property_info, refreshed)
    return property_info
