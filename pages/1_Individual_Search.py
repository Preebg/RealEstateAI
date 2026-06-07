import streamlit as st
import datetime 
import pandas as pd 
from engine import (
    calculate_property_age_years,
    calculate_quantum_risk,
    get_initial_analysis,
    get_final_analysis,
    safe_float,
)
from finance import (
    analyze_investment,
    calculate_10yr_appreciation,
    project_value_schedule,
)
from authenticate import get_logged_in_user, render_auth_sidebar
from knowledge_base import (
    compute_rent_deviation_pct,
    get_ai_baseline_maint,
    get_ai_baseline_rent,
    get_effective_display_maint,
    get_effective_display_management_fee,
    get_effective_display_rent,
    get_effective_display_vacancy,
    get_property_id_by_address,
    is_rent_outlier,
    lookup_property,
    render_auth_page,
    save_knowledge_base,
    save_user_property_override,
    user_has_override_changes,
)
from market_pulse import render_market_pulse
from property_nav import consume_map_property_selection, load_property_from_kb
import matplotlib.pyplot as plt
from pdf_generator import generate_property_pdf
import tldextract

if not render_auth_page():
    st.stop()

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

#Helper function to clean source names for display

def get_pretty_label(url):
    try:
        # Peel back the brand name (Zillow, Redfin, etc.)
        ext = tldextract.extract(url)
        brand = ext.domain.capitalize()
        if brand and brand != "Google":
            return f"{brand}.{ext.suffix}"
        return "View Source"
    except Exception:
        return "View Source"

# 1. Setup the Web Interface
st.title("🔍 Individual Property Search")
st.write("Enter an address below to get an AI-calculated Risk-Adjusted ROI.")

# 2. Sidebar for Inputs (Instead of hardcoded variables)
with st.sidebar:
    render_auth_sidebar()
    st.divider()
    render_market_pulse()
    st.divider()
    st.header("Investment Parameters")
    down_payment=st.number_input("Expected Down Payment (%)", value=25)
    loan_term=st.number_input("Loan Term (yrs)", value=30)
    interest_rate=st.number_input("Your Mortgage Rate (%)", value=6.000)
address = st.text_input(label='Property Address', key='address_input', placeholder="123 Main St, New York, NY")# 3. The Analysis Logic
if "property_data" not in st.session_state:
    st.session_state["property_data"] = None

if st.button("Analyze Property"):
    if address:
        st.warning(
            "**LEGAL DISCLOSURE:** This is an AI-powered educational tool. Quantum-probabilistic scores are simulations, not financial guarantees. Consult a professional before making investment decisions in NY, NC, FL, TX, AL,  PA, or SC."
        )
        st.session_state.property_data = None

        with st.status("🔍 Researching property and estimating value...") as status:
            # Instant Pull: check Knowledge Base before any AI engine calls
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

            # Exception Case: Price is 0
            if not from_kb and safe_float(initial_data.get("price")) == 0:
                st.error("Error Fetching Property Data... The AI could not find a valid listing price. Please verify the address and try again.")
                st.stop()

            # Immediate Display of Summary and Forecast
            st.markdown("### 📝 AI Property Summary")
            st.write(initial_data.get("summary", "No summary available."))

            loc_score = safe_float(initial_data.get("location_score"))
            pred_val = safe_float(initial_data.get("predicted_value"))
            forecast = calculate_10yr_appreciation(pred_val, loc_score)

            st.subheader("📈 10-Year Appreciation Forecast")
            st.write(f"**Estimated Value in 2034:** ${forecast['future_value']:,.2f}")
            st.write(f"**Projected Annual Growth:** {forecast['annual_rate']:.2f}%")

            status.update(label="✅ Verifying data and calculating ROI...", state="running")
            final_result = get_final_analysis(initial_data, address, research_results)
            st.session_state.property_data = final_result
            done_label = (
                "✅ Loaded from Knowledge Base (Instant Pull)"
                if from_kb
                else "✅ Analysis Complete!"
            )
            status.update(label=done_label, state="complete")

    else:
        st.warning("Please enter a property address.")
if st.session_state.property_data:
    property_info=st.session_state.property_data

        
    # Extract values from the dictionary 
    price=safe_float(property_info.get("price"))
    monthly_rent=get_effective_display_rent(property_info)
    tax_rate=safe_float(property_info.get("tax_rate"))
    monthly_HOA=safe_float(property_info.get("hoa"))
    monthly_insurance=safe_float(property_info.get("insurance"))
    ai_maint_percent=get_effective_display_maint(property_info)

    # HITL: preserve AI baselines; official rent/maint are written on user save.
    if property_info.get("original_ai_rent") is None:
        property_info["original_ai_rent"] = monthly_rent
    if property_info.get("original_ai_maint") is None:
        property_info["original_ai_maint"] = ai_maint_percent
    original_ai_rent = get_ai_baseline_rent(property_info)
    original_ai_maint = get_ai_baseline_maint(property_info)
    
    # New Predicted Value Fields
    predicted_value = safe_float(property_info.get("predicted_value"))
    prediction_reasoning = property_info.get("prediction_reasoning", "No reasoning provided.")
    location_score = safe_float(property_info.get("location_score"))
    
    ai_vacancy_baseline = safe_float(property_info.get("ai_vacancy_rate"))
    ai_mgmt_baseline = safe_float(property_info.get("ai_management_fee"))
    appreciation_forecast = safe_float(property_info.get("appreciation_forecast"))
    forecast_rate = safe_float(property_info.get("forecast_rate"))
    
    sources=property_info.get("sources", [])
    from_kb = property_info.get("from_kb", False)
    property_id = property_info.get("id") or get_property_id_by_address(address)

    st.sidebar.markdown("---")
    st.sidebar.write("### 🤖 AI Baselines (read-only)")
    st.sidebar.caption(f"Rent: ${original_ai_rent:,.0f}/mo")
    st.sidebar.caption(f"Maintenance: {original_ai_maint:.1f}%")
    st.sidebar.caption(f"Vacancy: {ai_vacancy_baseline:.1f}%")
    st.sidebar.caption(f"Management: {ai_mgmt_baseline:.1f}%")

    # Personal assumptions — each user can adjust without changing shared AI data.
    st.sidebar.markdown("---")
    st.sidebar.write("### 🛠️ Your Assumptions")
    
    rent_min, rent_max = 800.0, 4000.0
    clamped_rent = max(rent_min, min(rent_max, float(get_effective_display_rent(property_info))))
    final_monthly_rent = st.sidebar.slider(
        "Adjust Monthly Rent ($)", 
        rent_min, rent_max, 
        value = clamped_rent,
        step=25.0,
        help="The AI suggested the initial value, but you can override it here."
    )
    
    maint_min, maint_max = 1.0, 15.0
    clamped_maint = max(maint_min, min(maint_max, float(ai_maint_percent)))
    final_maint_percent = st.sidebar.slider(
        "Adjust Maintenance %", 
        maint_min, maint_max, 
        value = clamped_maint,
        step=0.1,
        help="The AI suggested the initial value, but you can override it here."
    )

    vac_min, vac_max = 1.0, 10.0
    clamped_vac = max(vac_min, min(vac_max, get_effective_display_vacancy(property_info)))
    user_vacancy_reserve = st.sidebar.slider(
        "Your Vacancy Reserve %", 
        vac_min, vac_max, 
        value = clamped_vac,
        step=0.1,         
        help="Your personal vacancy assumption (AI baseline shown above)."
    )

    mgmt_min, mgmt_max = 8.0, 12.0
    clamped_mgmt = max(mgmt_min, min(mgmt_max, get_effective_display_management_fee(property_info)))
    user_management_fee = st.sidebar.slider(
        "Your Management Fee %", 
        mgmt_min, mgmt_max, 
        value = clamped_mgmt,
        step=0.1,           
        help="Your personal management fee assumption (AI baseline shown above)."
    )

    closing_min, closing_max = 0.0, 10.0
    clamped_closing = max(closing_min, min(closing_max, 3.0))
    user_closing_costs_pct = st.sidebar.slider(
        "Adjust Closing Costs (%)",
        closing_min, closing_max,
        value=clamped_closing,
        step=0.1,
        help = "Standard closing costs are around 3-5% of the purchase price."
    )
        
    analysis = analyze_investment(
        price=price,
        down_payment_pct=down_payment,
        interest_rate=interest_rate,
        loan_term=int(loan_term),
        closing_costs_pct=user_closing_costs_pct,
        tax_rate=tax_rate,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_HOA,
        maint_percent=final_maint_percent,
        monthly_rent=final_monthly_rent,
        vacancy_reserve_pct=user_vacancy_reserve,
        management_fee_pct=user_management_fee,
    )
    monthly_mortgage = analysis["monthly_mortgage"]
    user_closing_costs_total = analysis["closing_costs_total"]
    op_ex = analysis["operating_expenses"]
    operating_expenses = op_ex["total"]
    monthly_taxes = op_ex["monthly_taxes"]
    calculated_monthly_maint = op_ex["monthly_maintenance"]
    actual_vacancy_reserve = op_ex["vacancy_reserve"]
    actual_management_fee = op_ex["management_fee"]
    total_monthly_expenses = analysis["total_monthly_expenses"]
    monthly_net_cash_flow = analysis["monthly_net_cash_flow"]
    total_investment = analysis["total_investment"]
    cap_rate = analysis["cap_rate"]
    cash_on_cash = analysis["cash_on_cash"]

    st.sidebar.caption(f"Estimated Closing Costs: ${user_closing_costs_total:,.2f}")

    branding_label = property_info.get("property_label", "Balanced")

    with st.spinner("⚛️ Running Quantum Simulation..."):
        quantum_risk = calculate_quantum_risk(
            monthly_net_cash_flow,
            forecast_rate,
            location_score,
        )
        property_info["quantum_risk_score"] = quantum_risk["overall_success_pct"]
        property_info["quantum_risk"] = quantum_risk

    # 4. Display Results
    st.divider()
    header_col1, header_col2, header_col3 = st.columns([2, 1, 1])
    with header_col1:
        st.subheader("📊 Analysis Overview")

    with header_col2:
        st.metric(
            label="⚛️ Cash Flow Success",
            value=f"{quantum_risk['cashflow_success_pct']:.1f}%",
            help="Quantum probability of positive monthly cash-flow returns.",
        )
    with header_col3:
        st.metric(
            label="📈 Appreciation Success",
            value=f"{quantum_risk['appreciation_success_pct']:.1f}%",
            help="Quantum probability of appreciation-driven wealth growth.",
        )

    qcol1, qcol2 = st.columns(2)
    with qcol1:
        st.metric(
            label="💰 Combined Wealth Success",
            value=f"{quantum_risk['combined_wealth_success_pct']:.1f}%",
            help="Chance of making money from both cash flow and appreciation together.",
        )
    with qcol2:
        st.metric(
            label="⚛️ Overall Quantum Success",
            value=f"{quantum_risk['overall_success_pct']:.1f}%",
            help="Full QAOA alignment across cash flow, appreciation, and location.",
        )

    tab1 = st.tabs(["📋 Detailed Metrics"])[0]

    with tab1:
        col1, col2, col3 = st.columns(3)
        col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
        col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
        col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")
        
        st.markdown(f"**Strategy Status:** :blue[{branding_label}]")
        st.subheader("🎯 AI Valuation")
        st.info(f"**Predicted Market Value:** ${predicted_value:,.2f}\n\n**Reasoning:** {prediction_reasoning}")
        
        with st.expander("📈 10-Year Appreciation Forecast"):
            st.write(f"**Estimated Value in 2036:** ${appreciation_forecast:,.2f}")
            st.write(f"**Projected Annual Growth:** {forecast_rate:.2f}%")
            st.info(f"**Logic:** The forecast uses a compound growth formula. The rate is dynamically adjusted based on the Location Score ({location_score}/10).")
            st.markdown("**Methodology:** This app utilizes a Compound Growth Model to project future value based on historical neighborhood trends and location-weighted growth rates.")
            
            start_year = datetime.datetime.now().year
            years = list(range(start_year, start_year + 11))
            values = project_value_schedule(predicted_value, forecast_rate)
            
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.plot(years, values, marker='o', color='#2ecc71', linewidth=2)
            ax.set_title("Projected Property Value Growth", fontsize=14)
            ax.set_xlabel("Year")
            ax.set_ylabel("Estimated Value ($)")
            ax.grid(True, linestyle='--', alpha=0.6)
            ax.ticklabel_format(style='plain', axis='y')
            
            st.pyplot(fig)

    # Display the summary from the AI search
    st.markdown("### 📝 AI Property Summary")
    st.write(property_info.get("summary", "No summary available."))
    
    # 5. The Cash Flow Table (Hidden by Default)
    with st.expander("View Detailed Monthly Breakdown"):
        st.write("Property Listed Price: ${:,.2f}".format(price))
        st.write("Monthly Cash Flow")

        table_data={
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
                "Cash Flow Monthly"             
                            
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
                f"${monthly_net_cash_flow:,.2f}"

            ]
        }
        df= pd.DataFrame(table_data)
        st.table(df)

        property_age = calculate_property_age_years(property_info)
        if property_age is not None:
            st.info(f"Property Age: {property_age} years.")
        else:
            st.info("Property Age: Unknown")
        st.info(f"Total Investment: ${total_investment:,.2f}")
        st.caption("Disclaimer: This is an AI-powered tool for educational purposes. Always verify financial data with a professional before making investment decisions.")
        st.sidebar.write(f"💸 Total Cash Required: **${total_investment:,.2f}**")
        
        investment_params = {
            "Down Payment": f"{down_payment}%",
            "Interest Rate": f"{interest_rate}%",
            "Loan Term": f"{loan_term} Years"
        }

        pdf_metrics = {
            "Risk-Adjusted Cap Rate": f"{cap_rate:.2f}%",
            "Cash on Cash Return": f"{cash_on_cash:.2f}%",
            "Monthly Net Cash Flow": f"${monthly_net_cash_flow:,.2f}",
            "Total Cash Required": f"${total_investment:,.2f}"
        }

        # The PDF Button
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
            mime="application/pdf"
        )

    has_assumption_changes = user_has_override_changes(
        property_info,
        rent=final_monthly_rent,
        maint_percent=final_maint_percent,
        vacancy_rate=user_vacancy_reserve,
        management_fee=user_management_fee,
    )

    st.divider()
    if from_kb:
        st.subheader("💾 Your Saved Assumptions")
        if property_info.get("has_user_override"):
            st.info("You have saved personal assumptions for this property.")
        else:
            st.info(
                "Shared AI property data is loaded. Adjust sliders and save "
                "**your** rent, fees, and maintenance assumptions below."
            )
    else:
        st.subheader("Improve the Algorithm")
        st.info(
            "Save this property to the shared catalog and store **your** "
            "personal underwriting assumptions."
        )
        sources = property_info.get("sources", [])
        with st.popover("View Data Sources 🔗"):
            if not sources:
                st.write("No sources found.")
            else:
                for link in set(sources):
                    pretty_name = get_pretty_label(link)
                    st.markdown(f"- [{pretty_name}]({link})")

    rent_deviation = compute_rent_deviation_pct(original_ai_rent, final_monthly_rent)
    hitl_is_outlier = is_rent_outlier(original_ai_rent, final_monthly_rent)
    if hitl_is_outlier:
        st.warning(
            f"Your rent (${final_monthly_rent:,.0f}) differs from the AI suggestion "
            f"(${original_ai_rent:,.0f}) by **{rent_deviation:.0f}%**. "
            "Please add a brief **Override Note** below so we can learn from expert judgment."
        )
    override_notes = st.text_area(
        "Override Note (required for large rent changes)",
        value=property_info.get("override_notes") or "",
        placeholder="e.g. Section 8 contract, major renovation, or comp mismatch in AI research.",
        disabled=not hitl_is_outlier,
        help="Required when your rent override is more than 50% away from the AI estimate.",
    )

    save_label = (
        "💾 Save My Assumptions"
        if from_kb
        else "✅ Save Property + My Assumptions"
    )
    if st.button(save_label, disabled=from_kb and not has_assumption_changes):
        if hitl_is_outlier and not str(override_notes).strip():
            st.error("An override note is required when rent differs by more than 50% from the AI.")
            st.stop()

        user = get_logged_in_user()
        if not user:
            st.error("You must be signed in to save.")
            st.stop()

        override_payload = {
            "rent": final_monthly_rent,
            "maint_percent": final_maint_percent,
            "vacancy_rate": user_vacancy_reserve,
            "management_fee": user_management_fee,
            "is_outlier": hitl_is_outlier,
            "override_notes": str(override_notes).strip(),
        }

        if from_kb:
            pid = property_id or get_property_id_by_address(address)
            if not pid:
                st.error("Could not resolve property ID for this address.")
                st.stop()
            result = save_user_property_override(
                user["id"], pid, override_payload
            )
        else:
            property_info["address"] = address
            property_info["from_kb"] = True
            property_info["location_score"] = location_score
            property_info["appreciation_forecast"] = appreciation_forecast
            property_info["property_category"] = branding_label
            property_info.update(override_payload)
            result = save_knowledge_base(property_info, user_id=user["id"])

        if result is None:
            st.error("Save failed. Check your connection and try again.")
            st.stop()

        st.cache_data.clear()
        st.success(
            f"Saved your assumptions for {address}."
            if from_kb
            else f"Saved {address} to the shared catalog with your assumptions."
        )
        st.rerun()
    elif from_kb and not has_assumption_changes:
        st.caption("Adjust a slider above to enable saving your personal assumptions.")
    
   
