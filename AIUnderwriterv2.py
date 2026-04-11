from google import genai
import streamlit as st
import datetime 
import pandas as pd 
from engine import get_property_details 
import tldextract
import urllib.parse

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

#def get_pretty_label(url):
    import tldextract
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

address = st.text_input("Address", placeholder="Enter the property address.")

    
# 3. The Analysis Logic
if "property_data" not in st.session_state:
    st.session_state["property_data"] = None

if st.button("Analyze Property"):
    if address:
        st.session_state.property_data = None # Clear previous data while fetching new
        status = st.status("🔍 Searching Zillow and Public Records...")
        result = get_property_details(address)
        status.update(label="✅ Analysis Complete!", state="complete")
        st.session_state.property_data = result
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
    monthly_maint=safe_float(property_info.get("maint_percent"))
    
    sources=property_info.get("sources", [])

    # We put it in the sidebar so you can tweak it while looking at the results
    st.sidebar.markdown("---")
    st.sidebar.write("### 🛠️ Manual Override")
    final_monthly_rent = st.sidebar.slider(
        "Adjust Monthly Rent ($)", 
        800.0, 4000.0, 
        value = float(monthly_rent),
        step=25.0,
        help="The AI suggested the initial value, but you can override it here."
    )
    final_maint_percent = st.sidebar.slider(
        "Adjust Maintenance %", 
        0.0, 15.0, 
        value = float(monthly_maint),
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
    monthly_maint = (final_maint_percent / 100 * final_monthly_rent)
    init_vacancy_reserve=final_monthly_rent*0.05
    
    user_vacancy_reserve = st.sidebar.slider(
    "Adjust Vacancy Reserve %", 
    0.0, 10.0, 
    value = float(init_vacancy_reserve/final_monthly_rent)*100 if final_monthly_rent > 0 else 5.0,
    step=0.1,         
    help="The AI set this at 5% of rent, but you can adjust it based on your market knowledge."
    )
    actual_vacancy_reserve = (user_vacancy_reserve / 100) * final_monthly_rent

    init_management_fee=final_monthly_rent*0.10
    user_management_fee = st.sidebar.slider(
    "Adjust Management Fee %", 
    5.0, 12.0, 
    value = float(init_management_fee/final_monthly_rent)*100 if final_monthly_rent > 0 else 10.0,
    step=0.1,           
    help="The AI set this at 10% of rent, but you can adjust it based on your market knowledge."
    )
    actual_management_fee = (user_management_fee / 100) * final_monthly_rent
    
    init_closing_costs = price * 0.03
    user_closing_costs = st.sidebar.slider(
        "Adjust Closing Costs ($)",
        min_value=0.0,
        max_value=10.0,
        value=3.0,
        step=0.1,
        help = "Standard ckosing costs are around 3-5% of the purchase price."
    )

    user_closing_costs=(price * (user_closing_costs / 100))
    st.sidebar.caption(f"Estimated Closing Costs: ${user_closing_costs:,.2f}")
    operating_expenses = monthly_taxes + monthly_insurance + monthly_HOA + monthly_maint + actual_vacancy_reserve + actual_management_fee
    total_monthly_expenses = monthly_mortgage + operating_expenses
    monthly_net_cash_flow = monthly_rent - total_monthly_expenses

    #Metrics
    annual_noi = (monthly_rent-operating_expenses)*12
    if (price>0):
        cap_rate = (annual_noi / price) * 100
    else: 
        cap_rate=0 

    total_investment = (price * (down_payment / 100)) + user_closing_costs    
    if(total_investment>0):
        cash_on_cash=(monthly_net_cash_flow*12)/(total_investment)*100
    else: 
        cash_on_cash = 0 

    # 4. Display Results
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    # Show the user-adjusted number
    col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
    col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
    col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")
    
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
                "Total Expenses"             
                            
            ],
            "Amount": [
                f"${monthly_rent:,.2f}",
                f"-${monthly_mortgage:,.2f}",
                f"-${monthly_taxes:,.2f}",
                f"-${monthly_insurance:,.2f}",
                f"-${monthly_HOA:,.2f}",
                f"-${monthly_maint:,.2f}",
                f"-${actual_vacancy_reserve:,.2f}",
                f"-${actual_management_fee:,.2f}",
                f"${total_monthly_expenses:,.2f}"
            ]
        }
        df= pd.DataFrame(table_data)
        st.table(df)

        st.info(f"Property Age: {datetime.datetime.now().year - year_built} years.")
        st.info(f"Based on total cash out of pocket: ${total_investment:,.2f})")
        st.caption("Disclaimer: This is an AI-powered tool for educational purposes. Always verify financial data with a professional before making investment decisions.")
        st.sidebar.write(f"💸 Total Cash Required: **${total_investment:,.2f}**")
    
    
    
    #
    #sources = property_info.get("sources", [])
    #with st.popover("View Data Sources 🔗"):
    # Ensure 'sources' is a list of full URLs
       # if not sources:
       #     st.write("No sources found.")
        #else:
        #    for link in set(sources):
                # Create the 'Pretty Name' for the text
         #       pretty_name = get_pretty_label(link)
          #      
          #      # Format: [Text](URL) 
                # This keeps the link functional but the text clean!
          #      st.markdown(f"- [{pretty_name}]({link})")
    ###



