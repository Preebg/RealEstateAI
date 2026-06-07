import streamlit as st

from authenticate import render_auth_page, render_auth_sidebar
from components.property_analysis_display import get_pretty_label, render_analysis_results
from components.property_assumptions_sidebar import (
    render_assumption_sliders,
    render_closing_costs_caption,
    render_hitl_save_section,
)
from data_provenance import ensure_data_provenance
from engine import safe_float
from knowledge_base import (
    get_effective_display_maint,
    get_effective_display_rent,
    get_property_id_by_address,
    render_user_saved_properties_sidebar,
)
from market_pulse import render_market_pulse
from property_nav import consume_map_property_selection, load_property_from_kb
from services.property_analysis_flow import (
    initialize_hitl_baselines,
    run_finance_analysis,
    run_initial_property_analysis,
    run_quantum_simulation,
)
from share_access import is_guest_viewer, render_guest_sidebar
from ui_theme import render_page_hero

if not render_auth_page():
    st.stop()

_guest_mode = is_guest_viewer()

_map_address = consume_map_property_selection()
if _map_address:
    st.session_state["address_input"] = _map_address
    _map_loaded = load_property_from_kb(_map_address)
    if _map_loaded:
        st.session_state["property_data"] = _map_loaded
        st.toast(f"Loaded {_map_address} from Portfolio Map", icon="🗺️")
    else:
        st.warning(
            f"Could not load cached data for **{_map_address}**. "
            "Run **Analyze Property** to research it."
        )

render_page_hero(
    "🔍 Individual Property Search",
    "Research any address with AI underwriting, quantum alignment scores, and exportable reports.",
)

with st.sidebar:
    if _guest_mode:
        render_guest_sidebar()
    else:
        render_auth_sidebar()
        render_user_saved_properties_sidebar()
    st.divider()
    render_market_pulse()
    st.divider()
    st.header("Investment Parameters")
    down_payment = st.number_input("Expected Down Payment (%)", value=25)
    loan_term = st.number_input("Loan Term (yrs)", value=30)
    interest_rate = st.number_input("Your Mortgage Rate (%)", value=6.000)

if _guest_mode:
    st.info(
        "You're viewing via a shared link. Browse and explore read-only — "
        "sign in to run new AI research or save assumptions."
    )

address = st.text_input(
    label="Property Address",
    key="address_input",
    placeholder="123 Main St, New York, NY",
    disabled=_guest_mode,
    help="Guests can open properties from the Portfolio Map. Sign in to search new addresses.",
)

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
        run_initial_property_analysis(address)
    else:
        st.warning("Please enter a property address.")
elif _guest_mode and not st.session_state.property_data:
    st.caption("Open a property from the **Portfolio Map** or use the link your friend shared.")

if st.session_state.property_data:
    property_info = ensure_data_provenance(st.session_state.property_data)
    st.session_state.property_data = property_info
    field_confidence = property_info.get("confidence_score") or {}

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

    assumptions = render_assumption_sliders(property_info)

    finance = run_finance_analysis(
        price=price,
        down_payment_pct=down_payment,
        interest_rate=interest_rate,
        loan_term=int(loan_term),
        closing_costs_pct=assumptions["user_closing_costs_pct"],
        tax_rate=tax_rate,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_HOA,
        maint_percent=assumptions["final_maint_percent"],
        monthly_rent=assumptions["final_monthly_rent"],
        vacancy_reserve_pct=assumptions["user_vacancy_reserve"],
        management_fee_pct=assumptions["user_management_fee"],
    )
    render_closing_costs_caption(finance["user_closing_costs_total"])

    quantum_risk = run_quantum_simulation(
        property_info,
        finance["monthly_net_cash_flow"],
        forecast_rate,
        location_score,
    )

    render_analysis_results(
        guest_mode=_guest_mode,
        address=address,
        property_info=property_info,
        property_id=property_id or get_property_id_by_address(address),
        from_kb=from_kb,
        quantum_risk=quantum_risk,
        assumptions=assumptions,
        finance=finance,
        loan_params={
            "down_payment": down_payment,
            "interest_rate": interest_rate,
            "loan_term": loan_term,
        },
        field_confidence=field_confidence,
    )

    render_hitl_save_section(
        guest_mode=_guest_mode,
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
