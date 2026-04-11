from google import genai
import streamlit as st
import datetime 
import json 
import pandas as pd 
# 1. Setup the Web Interface
st.set_page_config(page_title="AI Property Scout", page_icon="🏠")
st.title("🏠 AI Property Analyzer")
st.write("Enter details below to get an AI-calculated Risk-Adjusted Cap Rate.")

# 2. API Setup
API_KEY = st.secrets["GEMINI_API_KEY"] 
client = genai.Client(api_key=API_KEY)
model_name="gemini-3.1-flash-lite-preview"

# 3. Sidebar for Inputs (Instead of hardcoded variables)
with st.sidebar:
    st.header("Investment Parameters")
    down_payment=st.number_input("Expected Down Payment (%)", value=25)
    loan_term=st.number_input("Loan Term (yrs)", value=30)
    interest_rate=st.number_input("Your Mortgage Rate (%)", value=6)

address = st.text_input("Address", placeholder="Enter the property address.")

# 4. Get Property Details From The Address
@st.cache_data
def get_property_details(address):
    prompt = f"""
    Act as a Real Estate Investment Analyst. Provide data for {address}.
    Task: 
    1. Find core stats: Price, Year Built, Estimated Rent(monthly), Tax Rate(annually as a percentage), HOA(monthly), Insurance(monthly).
    2. Analyze condition: If you can't find a description of the listing, estimate condition based on age looking for key renovations or original property with no changes if it's old. 
    3. Calculate Maintenance %: Use 1-2% for new(<5 yrs), 2-4% for mid-age(10-25 yrs), 5% for old(30+ yrs)/distressed.
        - If 'Original HVAC', 'Original Windows', 'TLC', or 'AS-IS' is mentioned, ensure the score is at least 8%.
        - If 'new roof' or 'new hvac' or 'updated'is mentioned, reduce the score by 1-2%.
        - Return ONLY the final percentage as a number (ex. 5.5).

    Return only a JSON object with these keys: "price", "year", "rent", "tax_rate", "hoa", "insurance", "summary", "maint_percent"
    """
    
    try:
        # Only returns JSON object
        response = client.models.generate_content(
            model=model_name, 
            contents=prompt, 
            config={
                "response_mime_type": "application/json", 
                #"tools":[{ "google_search": {} }]
            }
        )
        return json.loads(response.text.strip())
        
    except Exception as e:
        st.error(f"AI Fetch Error: {e}")
        # Fallback values so the rest of the app doesn't crash
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0
        }
    
# 5. The Analysis Logic
if "property_data" not in st.session_state:
    st.session_state["property_data"] = None

if st.button("Analyze Property"):
    if address:
        st.session_state.property_data = None # Clear previous data while fetching new
        with st.spinner("AI is calculating costs..."):
            st.session_state.property_data=get_property_details(address)
    else:
        st.warning("Please enter a property address.")
if st.session_state.property_data:
    property_info=st.session_state.property_data
    # Skim basic details from the address
    price=property_info["price"]
    year_built=property_info["year"]
    monthly_rent=property_info["rent"]
    tax_rate=property_info["tax_rate"]
    monthly_HOA=property_info["hoa"]
    monthly_insurance=property_info["insurance"]
    monthly_maint=property_info["maint_percent"]

    # We put it in the sidebar so you can tweak it while looking at the results
    st.sidebar.markdown("---")
    st.sidebar.write("### 🛠️ Manual Override")
    final_maint_percent = st.sidebar.slider(
        "Adjust Maintenance %", 
        0.0, 10.0, 
        value = float(monthly_maint),
        step=0.1,
        help="The AI suggested the initial value, but you can override it here."
    )
        
    # 5. The Math (Using the SLIDER value, not the raw AI value)
    #Mortage Payment
    loan_amount=price*(1-(down_payment/100))
    monthly_ir = (interest_rate / 100) / 12
    total_payments = loan_term * 12
    if monthly_ir > 0:
        monthly_mortgage = loan_amount * (monthly_ir * (1 + monthly_ir)**total_payments) / ((1 + monthly_ir)**total_payments - 1)
    else:
        monthly_mortgage = loan_amount / total_payments

    #Expense calculations
    monthly_taxes=((tax_rate/100)*price)/12
    monthly_maint = (final_maint_percent / 100 * monthly_rent)
    init_vacancy_reserve=monthly_rent*0.05
    
    user_vacancy_reserve = st.sidebar.slider(
    "Adjust Vacancy Reserve %", 
    0.0, 10.0, 
    value = float(init_vacancy_reserve/monthly_rent)*100 if monthly_rent > 0 else 5.0,
    step=0.1,         
    help="The AI set this at 5% of rent, but you can adjust it based on your market knowledge."
    )
    actual_vacancy_reserve = (user_vacancy_reserve / 100) * monthly_rent

    init_management_fee=monthly_rent*0.10
    user_management_fee = st.sidebar.slider(
    "Adjust Management Fee %", 
    0.0, 10.0, 
    value = float(init_management_fee/monthly_rent)*100 if monthly_rent > 0 else 10.0,
    step=0.1,           
    help="The AI set this at 10% of rent, but you can adjust it based on your market knowledge."
    )
    actual_management_fee = (user_management_fee / 100) * monthly_rent
    
    total_monthly_expenses = monthly_mortgage + monthly_taxes + monthly_insurance + monthly_HOA + monthly_maint + actual_vacancy_reserve + actual_management_fee
    monthly_net_cash_flow = monthly_rent - total_monthly_expenses

    #Metrics
    annual_noi = (monthly_rent*12)-(monthly_maint*12)
    if (price>0):
        cap_rate = (annual_noi / price) * 100
    else: 
        cap_rate=0 
    initial_investment = price *(down_payment/100)
    if(initial_investment>0):
        cash_on_cash=(monthly_net_cash_flow*12)/(initial_investment)*100
    else: 
        cash_on_cash = 0 

    # 6. Display Results
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    # Show the user-adjusted number
    col1.metric("Monthly Take-Home", f"${monthly_net_cash_flow:,.2f}")
    col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
    col3.metric("Cash On Cash", f"{cash_on_cash:.2f}%")
    
    # 7. The Cash Flow Table (Hidden by Default)
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
                f"${monthly_mortgage:,.2f}",
                f"${monthly_taxes:,.2f}",
                f"${monthly_insurance:,.2f}",
                f"${monthly_HOA:,.2f}",
                f"${monthly_maint:,.2f}",
                f"${actual_vacancy_reserve:,.2f}",
                f"${actual_management_fee:,.2f}",
                f"${total_monthly_expenses:,.2f}"
            ]
        }
        df= pd.DataFrame(table_data)
        st.table(df)

        st.info(f"Property Age: {datetime.datetime.now().year - year_built} years.")
        st.info(f"Maintenance is calculated at {final_maint_percent}% of rent monthly.")

        st.caption("Disclaimer: This is an AI-powered tool for educational purposes. Always verify financial data with a professional before making investment decisions.")

