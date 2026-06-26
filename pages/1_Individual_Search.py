from __future__ import annotations

from typing import Any

import streamlit as st

import app_nav  # noqa: F401 — navigation module registration

from app_nav import consume_map_property_selection
from authenticate import render_auth_page, render_auth_sidebar
from components.address_search import render_property_address_input
from components.property_analysis_display import render_individual_search_analysis_fragment
from components.property_assumptions_sidebar import (
    render_assumption_sliders,
    render_closing_costs_caption,
)
from data_provenance import ensure_data_provenance
from engine import backfill_year_built_if_needed, safe_float
from knowledge_base import (
    get_effective_display_maint,
    get_effective_display_rent,
    render_user_saved_properties_sidebar,
)
from market_pulse import render_market_pulse
from services.deferred_analysis import (
    clear_deferred_analysis_state,
    ensure_deferred_task_queue,
    set_active_analysis_address,
    restore_individual_search_address_input,
)
from services.property_analysis_flow import (
    initialize_hitl_baselines,
    run_finance_analysis,
    run_initial_property_analysis,
)
from share_access import is_guest_viewer, render_guest_sidebar
from ui_theme import render_callout_info, render_flow_steps, render_page_hero


def _load_property_from_kb(address: str) -> dict[str, Any] | None:
    """Hydrate a KB property for the analyzer UI — must live in this page module for Streamlit reruns."""
    from engine import get_final_analysis
    from knowledge_base import lookup_property

    cached = lookup_property(address)
    if not cached:
        return None
    return get_final_analysis(cached, address, None, skip_comps=True)


if not render_auth_page():
    st.stop()

_guest_mode = is_guest_viewer()

_map_address = consume_map_property_selection()
if _map_address:
    set_active_analysis_address(_map_address)
    _map_loaded = _load_property_from_kb(_map_address)
    if _map_loaded:
        _map_loaded["address"] = _map_address
        st.session_state["property_data"] = _map_loaded
        st.toast(f"Loaded {_map_address} from Portfolio Map", icon="🗺️")
    else:
        st.warning(
            f"Could not load cached data for **{_map_address}**. "
            "Run **Analyze Property** to research it."
        )

render_page_hero(
    "Individual Search",
    "Enter an address to see estimated rent, monthly cash flow, and 10-year returns — with optional research simulations.",
)

_has_results = bool(st.session_state.get("property_data"))
render_flow_steps(
    ["Search address", "Run analysis", "Review results"],
    active_index=2 if _has_results else (1 if st.session_state.get("address_input") else 0),
)

with st.sidebar:
    if _guest_mode:
        render_guest_sidebar()
    else:
        render_auth_sidebar()
        render_user_saved_properties_sidebar()
    st.divider()
    render_market_pulse()

if _guest_mode:
    render_callout_info(
        "You're viewing a <strong>shared property link</strong>. Explore the analysis below — "
        "sign in to search new addresses or save your assumptions."
    )

restore_individual_search_address_input()

with st.container(border=True):
    st.markdown("##### Property address")
    st.caption("Start typing to pick from analyzed properties, or enter any new address.")
    address = render_property_address_input(disabled=_guest_mode)

if "property_data" not in st.session_state:
    st.session_state["property_data"] = None

if st.button("Analyze Property", disabled=_guest_mode):
    if address:
        st.warning(
            "**LEGAL DISCLOSURE:** This is an AI-powered educational tool. Quantum-probabilistic "
            "scores are simulations, not financial guarantees. Consult a professional before making "
            "investment decisions in NY, NC, FL, TX, AL,  PA, or SC."
        )
        st.session_state.property_data = None
        clear_deferred_analysis_state()
        st.session_state.pop("quantum_finance_sig", None)
        st.session_state.pop("run_market_crash_sim", None)
        set_active_analysis_address(address)
        
        # New flow: KB -> Scraper -> Research if still not found
        from knowledge_base import lookup_property
        cached = lookup_property(address)
        if cached:
            # KB hit, run analysis directly
            run_initial_property_analysis(address, guest_mode=_guest_mode)
        else:
            # KB miss, try scraper
            from discovery.orchestrator import run_scraper_discovery_async
            import asyncio
            
            with st.status(f"🔍 KB miss. Scraping {address}...", expanded=True) as status:
                try:
                    # In a real app we'd need more specific parameters, 
                    # but for this flow we attempt a targeted scrape.
                    # This might require creating a more specific helper function in discovery/orchestrator.
                    listings = asyncio.run(run_scraper_discovery_async(enrich=True))
                    # Check if found in listings (this is highly simplified)
                    found = next(
                        (listing for listing in listings if listing.get("address") == address),
                        None,
                    )
                    if found:
                        status.update(label="✅ Found via scraper", state="complete")
                        run_initial_property_analysis(address, guest_mode=_guest_mode)
                    else:
                        status.update(label="⚠️ Not found in scrape, falling back to LLM research", state="running")
                        run_initial_property_analysis(address, guest_mode=_guest_mode)
                except Exception as e:
                    st.error(f"Scraper error: {e}")
                    run_initial_property_analysis(address, guest_mode=_guest_mode)

    else:
        st.warning("Please enter a property address.")
elif _guest_mode and not st.session_state.property_data:
    st.caption("Open a property from the **Portfolio Map** or use the link your friend shared.")

if st.session_state.property_data:
    ensure_deferred_task_queue(
        st.session_state.property_data,
        guest_mode=_guest_mode,
    )
    if address:
        set_active_analysis_address(address)

    property_info = backfill_year_built_if_needed(
        st.session_state.property_data,
        address,
    )
    property_info = ensure_data_provenance(property_info)
    st.session_state.property_data = property_info

    price = safe_float(property_info.get("price"))
    monthly_rent = get_effective_display_rent(property_info)
    tax_rate = safe_float(property_info.get("tax_rate"))
    monthly_HOA = safe_float(property_info.get("hoa"))
    monthly_insurance = safe_float(property_info.get("insurance"))
    ai_maint_percent = get_effective_display_maint(property_info)
    initialize_hitl_baselines(property_info, monthly_rent, ai_maint_percent)

    with st.sidebar:
        assumptions = render_assumption_sliders(property_info)
        st.session_state["individual_search_assumptions"] = assumptions

    purchase_price = safe_float(assumptions.get("offer_amount")) or price
    finance = run_finance_analysis(
        price=purchase_price,
        down_payment_pct=assumptions["down_payment_pct"],
        interest_rate=assumptions["interest_rate"],
        loan_term=int(assumptions["loan_term"]),
        closing_costs_pct=assumptions["user_closing_costs_pct"],
        tax_rate=tax_rate,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_HOA,
        maint_percent=assumptions["final_maint_percent"],
        monthly_rent=assumptions["final_monthly_rent"],
        vacancy_reserve_pct=assumptions["user_vacancy_reserve"],
        management_fee_pct=assumptions["user_management_fee"],
    )
    st.session_state["individual_search_finance"] = finance

    with st.sidebar:
        render_closing_costs_caption(finance["user_closing_costs_total"])
        st.write(f"💸 Total Cash Required: **${finance['total_investment']:,.2f}**")

    render_individual_search_analysis_fragment(
        guest_mode=_guest_mode,
        address=address,
        property_info=property_info,
        assumptions=assumptions,
        finance=finance,
    )
