from typing import Any

import streamlit as st

from authenticate import render_auth_page, render_auth_sidebar
from components.address_search import render_property_address_input
from components.property_analysis_display import get_pretty_label, render_analysis_results
from components.property_assumptions_sidebar import (
    render_assumption_sliders,
    render_closing_costs_caption,
    render_hitl_save_section,
)
from data_provenance import ensure_data_provenance
from engine import backfill_year_built_if_needed, safe_float
from knowledge_base import (
    get_effective_display_maint,
    get_effective_display_rent,
    get_property_id_by_address,
    render_user_saved_properties_sidebar,
)
from market_pulse import render_market_pulse
from property_nav import consume_map_property_selection, load_property_from_kb
from services.deferred_analysis import (
    clear_deferred_analysis_state,
    ensure_deferred_task_queue,
    pending_tasks,
    render_deferred_progress_fragment,
    set_active_analysis_address,
    store_deferred_finance_context,
    restore_individual_search_address_input,
    sync_quantum_recompute_queue,
)
from services.property_analysis_flow import (
    initialize_hitl_baselines,
    resolve_quantum_risk,
    run_finance_analysis,
    run_initial_property_analysis,
)
from ui_theme import render_callout_info, render_flow_steps, render_page_hero

if not render_auth_page():
    st.stop()

from share_access import is_guest_viewer, render_guest_sidebar

_guest_mode = is_guest_viewer()

_map_address = consume_map_property_selection()
if _map_address:
    set_active_analysis_address(_map_address)
    _map_loaded = load_property_from_kb(_map_address)
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
        run_initial_property_analysis(address, guest_mode=_guest_mode)
    else:
        st.warning("Please enter a property address.")
elif _guest_mode and not st.session_state.property_data:
    st.caption("Open a property from the **Portfolio Map** or use the link your friend shared.")

@st.fragment
def _render_property_underwriting(
    *,
    guest_mode: bool,
    address: str,
    property_info: dict[str, Any],
) -> None:
    """Assumption sliders, finance metrics, and analysis — fragment-scoped reruns."""
    total_confidence_pct = property_info.get("total_confidence_pct")

    price = safe_float(property_info.get("price"))
    monthly_rent = get_effective_display_rent(property_info)
    tax_rate = safe_float(property_info.get("tax_rate"))
    monthly_HOA = safe_float(property_info.get("hoa"))
    monthly_insurance = safe_float(property_info.get("insurance"))
    ai_maint_percent = get_effective_display_maint(property_info)

    initialize_hitl_baselines(property_info, monthly_rent, ai_maint_percent)

    location_score = safe_float(property_info.get("location_score"))
    appreciation_forecast = safe_float(property_info.get("appreciation_forecast"))
    forecast_rate = safe_float(property_info.get("forecast_rate"))
    sources = property_info.get("sources", [])
    from_kb = property_info.get("from_kb", False)
    property_id = property_info.get("id") or get_property_id_by_address(address)
    branding_label = property_info.get("property_label", "Balanced")

    with st.sidebar:
        assumptions = render_assumption_sliders(property_info)

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
    with st.sidebar:
        render_closing_costs_caption(finance["user_closing_costs_total"])
        st.write(f"💸 Total Cash Required: **${finance['total_investment']:,.2f}**")

    sync_quantum_recompute_queue(
        property_info,
        monthly_net_cash_flow=finance["monthly_net_cash_flow"],
        forecast_rate=forecast_rate,
        location_score=location_score,
    )
    store_deferred_finance_context(
        monthly_net_cash_flow=finance["monthly_net_cash_flow"],
        forecast_rate=forecast_rate,
        location_score=location_score,
    )
    st.session_state.property_data = property_info

    if pending_tasks():
        render_deferred_progress_fragment()

    quantum_risk = resolve_quantum_risk(property_info)

    render_analysis_results(
        guest_mode=guest_mode,
        address=address,
        property_info=property_info,
        property_id=property_id,
        from_kb=from_kb,
        quantum_risk=quantum_risk,
        assumptions=assumptions,
        finance=finance,
        loan_params={
            "down_payment": assumptions["down_payment_pct"],
            "interest_rate": assumptions["interest_rate"],
            "loan_term": assumptions["loan_term"],
            "down_payment_label": assumptions.get("down_payment_label"),
        },
        total_confidence_pct=total_confidence_pct,
    )

    render_hitl_save_section(
        guest_mode=guest_mode,
        property_info=property_info,
        address=address,
        property_id=property_id,
        from_kb=from_kb,
        sources=sources,
        assumptions=assumptions,
        location_score=location_score,
        appreciation_forecast=appreciation_forecast,
        branding_label=branding_label,
        get_pretty_label=get_pretty_label,
    )


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

    _render_property_underwriting(
        guest_mode=_guest_mode,
        address=address,
        property_info=property_info,
    )
