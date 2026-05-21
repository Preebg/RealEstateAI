from google import genai
import streamlit as st
import datetime 
import pandas as pd 
from engine import calculate_quantum_probability, get_initial_analysis, get_final_analysis
from finance import (
    analyze_investment,
    calculate_10yr_appreciation,
    project_value_schedule,
)
import urllib.parse
from authenticate import get_logged_in_user, render_auth_sidebar
from knowledge_base import lookup_property, render_auth_page, save_knowledge_base
from market_pulse import render_market_pulse
import matplotlib.pyplot as plt
from pdf_generator import generate_property_pdf
import tldextract

st.set_page_config(page_title="AI Property Scout", page_icon="🏠", layout="wide")

if not render_auth_page():
    st.stop()
def safe_float(value):
    """Converts a value to float, handling strings, None, or empty values."""
    if value is None:
        return 0.0
    try:
        # Remove commas and dollar signs just in case the AI added them
        if isinstance(value, str):
            value = value.replace('$', '').replace(',', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return 0.0
    
#Helper function to clean source names for display

def get_pretty_label(url):
    try:
        # Peel back the brand name (Zillow, Redfin, etc.)
        ext = tldextract.extract(url)
        brand = ext.domain.capitalize()
        if brand and brand != "Google":
            return f"{brand}.{ext.suffix}"
        return "View Source"
    except:
        return "View Source"

# 1. Setup the Web Interface
st.title("🏠 AI Property Analyzer")
st.write("Enter details below to get an AI-calculated Risk-Adjusted ROI.")

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
    year_built=safe_float(property_info.get("year"))
    monthly_rent=safe_float(property_info.get("rent"))
    tax_rate=safe_float(property_info.get("tax_rate"))
    monthly_HOA=safe_float(property_info.get("hoa"))
    monthly_insurance=safe_float(property_info.get("insurance")) 
    ai_maint_percent=safe_float(property_info.get("maint_percent"))
    
    # New Predicted Value Fields
    predicted_value = safe_float(property_info.get("predicted_value"))
    prediction_reasoning = property_info.get("prediction_reasoning", "No reasoning provided.")
    location_score = safe_float(property_info.get("location_score"))
    
    ai_vacancy_rate = safe_float(property_info.get("ai_vacancy_rate"))
    ai_mgmt_fee = safe_float(property_info.get("ai_management_fee"))
    appreciation_forecast = safe_float(property_info.get("appreciation_forecast"))
    forecast_rate = safe_float(property_info.get("forecast_rate"))
    
    sources=property_info.get("sources", [])

    # We put it in the sidebar so you can tweak it while looking at the results
    st.sidebar.markdown("---")
    st.sidebar.write("### 🛠️ Manual Override")
    
    # Clamp values to ensure they are within slider ranges to prevent Streamlit crashes
    rent_min, rent_max = 800.0, 4000.0
    clamped_rent = max(rent_min, min(rent_max, float(monthly_rent)))
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
    clamped_vac = max(vac_min, min(vac_max, ai_vacancy_rate))
    user_vacancy_reserve = st.sidebar.slider(
        "Adjust Vacancy Reserve %", 
        vac_min, vac_max, 
        value = clamped_vac,
        step=0.1,         
        help="The AI set this at 5% of rent, but you can adjust it based on your market knowledge."
    )

    mgmt_min, mgmt_max = 8.0, 12.0
    clamped_mgmt = max(mgmt_min, min(mgmt_max, float(ai_mgmt_fee)))
    user_management_fee = st.sidebar.slider(
        "Adjust Management Fee %", 
        mgmt_min, mgmt_max, 
        value = clamped_mgmt,
        step=0.1,           
        help="The AI set this at 10% of rent, but you can adjust it based on your market knowledge."
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
        quantum_score = calculate_quantum_probability(
            monthly_net_cash_flow, 
            forecast_rate, 
            location_score
        )
        # Save to the main dictionary for Supabase later
        property_info["quantum_risk_score"] = quantum_score

    # 4. Display Results
    st.divider()
    header_col1, header_col2 = st.columns([2, 1])
    with header_col1:
        st.subheader("📊 Analysis Overview")

    with header_col2:
        st.metric(
            label="⚛️ Quantum Success Prob.", 
            value=f"{quantum_score:.1f}%",
            help="Calculated via Qiskit Ry-Gate rotations modeling non-linear market volatility."
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

        st.info(f"Property Age: {datetime.datetime.now().year - year_built} years.")
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
        pdf_bytes = generate_property_pdf(address, property_info, pdf_metrics, table_data, investment_params, location_score)

        st.download_button(
            label="📩 Download Full PDF Report",
            data=pdf_bytes,
            file_name=f"Analysis_{address.replace(' ', '_')}.pdf",
            mime="application/pdf"
        )

    is_already_saved = property_info.get("from_kb", False)
    if not is_already_saved:
        sources = property_info.get("sources", [])
        with st.popover("View Data Sources 🔗"):
            if not sources:
                st.write("No sources found.")
            else:
                for link in set(sources):
                    pretty_name = get_pretty_label(link)
                    st.markdown(f"- [{pretty_name}]({link})")
        st.divider()
        st.subheader("Improve the Algorithm")
        st.info("This property is new to the database. Save your adjustments to help the AI learn.")
        
        if st.button("✅ Confirm & Save to Knowledge Base"):
            # Update the dictionary with your manual slider overrides
            property_info["rent"] = final_monthly_rent
            property_info["maint_percent"] = final_maint_percent
            property_info["address"] = address  
            property_info["from_kb"] = True     # Mark it as saved
            
            property_info["location_score"] = location_score
            property_info["appreciation_forecast"] = appreciation_forecast
            property_info["property_category"] = branding_label
            
            # Save to JSON
            print(f"DEBUG: Saving address: {address}")
            user = get_logged_in_user()
            if user:
                save_knowledge_base(property_info, user_id=user["id"])
            else:
                st.error("You must be signed in to save to the knowledge base.")
                st.stop()
            st.cache_data.clear()  # Clear cache to ensure fresh data is pulled next time
            
            # Use success message and rerun to hide this section immediately
            st.success(f"Saved {address} to the knowledge base!")
            st.rerun()
    else:
        st.divider()
        st.success("Verified Property: This data is being pulled from your Knowledge Base.")
    
   
