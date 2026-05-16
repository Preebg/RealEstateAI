from google import genai
import streamlit as st
import datetime 
import pandas as pd 
from engine import get_initial_analysis, get_final_analysis, calculate_10yr_appreciation
import urllib.parse
from authenticate import check_password
from knowledge_base import save_knowledge_base 
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt
from pdf_generator import generate_property_pdf
from streamlit_searchbox import st_searchbox 
from engine import search_addresses as search_function
import tldextract

if not check_password():
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
st.set_page_config(page_title="AI Property Scout", page_icon="🏠")
st.title("🏠 AI Property Analyzer")
st.write("Enter details below to get an AI-calculated Risk-Adjusted ROI.")

# 2. Sidebar for Inputs (Instead of hardcoded variables)
with st.sidebar:
    st.header("Investment Parameters")
    down_payment=st.number_input("Expected Down Payment (%)", value=25)
    loan_term=st.number_input("Loan Term (yrs)", value=30)
    interest_rate=st.number_input("Your Mortgage Rate (%)", value=6.000)

address = st_searchbox("Property Address", search=search_function, key="prop_search_v3", placeholder="123 Main St, New York, NY")
# address = st.text_input("Address", placeholder="Enter the property address.")

    
# 3. The Analysis Logic
if "property_data" not in st.session_state:
    st.session_state["property_data"] = None

if st.button("Analyze Property"):
    if address:
        st.session_state.property_data = None

        # Stage 1: Fast Analysis
        with st.status("🔍 Researching property and estimating value...") as status:
            initial_data, from_kb = get_initial_analysis(address)

            # Immediate Display of Summary and Forecast
            st.markdown("### 📝 AI Property Summary")
            st.write(initial_data.get("summary", "No summary available."))

            loc_score = safe_float(initial_data.get("location_score"))
            pred_val = safe_float(initial_data.get("predicted_value"))
            forecast = calculate_10yr_appreciation(pred_val, loc_score)

            st.subheader("📈 10-Year Appreciation Forecast")
            st.write(f"**Estimated Value in 2034:** ${forecast['future_value']:,.2f}")
            st.write(f"**Projected Annual Growth:** {forecast['annual_rate']:.2f}%")

            # Stage 2: Detailed Analysis
            status.update(label="✅ Verifying data and calculating ROI...", state="running")
            final_result = get_final_analysis(initial_data, address)
            st.session_state.property_data = final_result
            status.update(label="✅ Analysis Complete!", state="complete")

        st.rerun()
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
    
    maint_min, maint_max = 0.0, 15.0
    clamped_maint = max(maint_min, min(maint_max, float(ai_maint_percent)))
    final_maint_percent = st.sidebar.slider(
        "Adjust Maintenance %", 
        maint_min, maint_max, 
        value = clamped_maint,
        step=0.1,
        help="The AI suggested the initial value, but you can override it here."
    )
        
    # 5. The Math (Using the SLIDER value, not the raw AI value)
    #Mortgage Payment
    loan_amount=price*(1-(down_payment/100))
    monthly_ir = (interest_rate / 100) / 12
    total_payments = loan_term * 12
    if monthly_ir > 0:
        monthly_mortgage = loan_amount * (monthly_ir * (1 + monthly_ir)**total_payments) / ((1 + monthly_ir)**total_payments - 1)
    else:
        monthly_mortgage = loan_amount / total_payments

    #Expense calculations
    monthly_taxes=((tax_rate/100)*price)/12
    calculated_monthly_maint = (final_maint_percent / 100 * final_monthly_rent)
    init_vacancy_reserve=final_monthly_rent*0.05
    
    vac_min, vac_max = 0.0, 10.0
    clamped_vac = max(vac_min, min(vac_max, ai_vacancy_rate))
    user_vacancy_reserve = st.sidebar.slider(
    "Adjust Vacancy Reserve %", 
    vac_min, vac_max, 
    value = clamped_vac,
    step=0.1,         
    help="The AI set this at 5% of rent, but you can adjust it based on your market knowledge."
    )
    actual_vacancy_reserve = (user_vacancy_reserve / 100) * final_monthly_rent

    init_management_fee=final_monthly_rent*0.10
    mgmt_min, mgmt_max = 5.0, 12.0
    clamped_mgmt = max(mgmt_min, min(mgmt_max, ai_mgmt_fee))
    user_management_fee = st.sidebar.slider(
    "Adjust Management Fee %", 
    mgmt_min, mgmt_max, 
    value = clamped_mgmt,
    step=0.1,           
    help="The AI set this at 10% of rent, but you can adjust it based on your market knowledge."
    )
    actual_management_fee = (user_management_fee / 100) * final_monthly_rent
    
    init_closing_costs_pct = 3.0
    closing_min, closing_max = 0.0, 10.0
    clamped_closing = max(closing_min, min(closing_max, init_closing_costs_pct))
    user_closing_costs_pct = st.sidebar.slider(
        "Adjust Closing Costs (%)",
        closing_min, closing_max,
        value=clamped_closing,
        step=0.1,
        help = "Standard closing costs are around 3-5% of the purchase price."
    )

    user_closing_costs_total=(price * (user_closing_costs_pct / 100))
    st.sidebar.caption(f"Estimated Closing Costs: ${user_closing_costs_total:,.2f}")
    operating_expenses = monthly_taxes + monthly_insurance + monthly_HOA + calculated_monthly_maint + actual_vacancy_reserve + actual_management_fee
    total_monthly_expenses = monthly_mortgage + operating_expenses
    monthly_net_cash_flow = final_monthly_rent - total_monthly_expenses

    #Metrics
    annual_noi = (final_monthly_rent-operating_expenses)*12
    if (price>0):
        cap_rate = (annual_noi / price) * 100
    else: 
        cap_rate=0 

    total_investment = (price * (down_payment / 100)) + user_closing_costs_total    
    if(total_investment>0):
        cash_on_cash=(monthly_net_cash_flow*12)/(total_investment)*100
    else: 
        cash_on_cash = 0 

    if cash_on_cash > 10 and location_score <= 7:
        branding_label = "Cash-flower"
    elif location_score > 7 and cash_on_cash <= 10:
        branding_label = "Appreciation Machine"
    else:
        branding_label = "Balanced"

    # 4. Display Results
    st.divider()
    tab1 = st.tabs(["📊 Overview"])[0]

    with tab1:
        col1, col2, col3 = st.columns(3)
        col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
        col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
        col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")
        
        st.subheader(f"🏷️ Property Label: {branding_label}")
        st.subheader("🎯 AI Valuation")
        st.info(f"**Predicted Market Value:** ${predicted_value:,.2f}\n\n**Reasoning:** {prediction_reasoning}")
        
        with st.expander("📈 10-Year Appreciation Forecast"):
            st.write(f"**Estimated Value in 2036:** ${appreciation_forecast:,.2f}")
            st.write(f"**Projected Annual Growth:** {forecast_rate:.2f}%")
            st.info(f"**Logic:** The forecast uses a compound growth formula. The rate is dynamically adjusted based on the Location Score ({location_score}/10).")
            st.markdown("**Methodology:** This app utilizes a Compound Growth Model to project future value based on historical neighborhood trends and location-weighted growth rates.")

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
        pdf_bytes = generate_property_pdf(address, property_info, pdf_metrics, table_data, investment_params)

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
            save_knowledge_base(property_info)
            st.cache_data.clear()  # Clear cache to ensure fresh data is pulled next time
            
            # Use success message and rerun to hide this section immediately
            st.success(f"Saved {address} to the knowledge base!")
            st.rerun()
    else:
        st.divider()
        st.success("Verified Property: This data is being pulled from your Knowledge Base.")
