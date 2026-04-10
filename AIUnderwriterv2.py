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
    st.header("Property Stats")
    address=st.text_input("Property Address", placeholder="e.g. 123 Maple St")
    down_payment=st.number_input("Expected Down Payment (%)", value=20)
    loan_term=st.number_input("Loan Term (yrs)", value=30)
    interest_rate=st.number_input("Your Mortgage Rate (%)", value=6)

listing_description = st.text_area("Listing Description", placeholder="Paste Description of the property here...")
# 4. Get Property Details From The Address
@st.cache_data
def get_property_details(address, description):
    prompt = f"""
    Act as a landlord trying to provide a fair rent.
    Provide accurate estimated real estate data for {address} and the {description}:
    - Price of the home as listed
    - Year home is built
    - Estimated rent per month (Increase rent by $100-200 if new(0-5 years old)or newly renovated)
    - Annual Property tax rate (as percentage, ex. 1.5)
    - HOA fee monthly for this community
    - Estimated monthly insurance for this area

    Return only a JSON object: {{"price": 0,"year":0,"rent":0,"tax_rate":0, "hoa":0, "insurance":0}}
    """
    try:
        response = client.models.generate_content(model=model_name, contents=prompt)
        data = json.loads(response.text.replace("```json", "").replace("```", ""))
        return [data['price'], data['year'], data['rent'], data['tax_rate'], data['hoa'], data['insurance']]
    except Exception:
        return [100000, 2026, 0.0, 1.2, 0.0, 80.0] 
    
# 5. The Maintenance Function
def get_maintenance_estimate(description, year):
    current_year = datetime.datetime.now().year
    age = current_year - year
    
    # We added the "Conservative Investor" rules here to fix the 1.5% issue
    prompt = f"""
    Act as a Conservative Real Estate Auditor. 
    Analyze this {age}-year-old property.
    Description: {description}

    RULES for Annual Maintenance %:
    - New Construction (<5 years): 1-2%
    - Mid-Age (10-25 years): 2-4%
    - Old/Original (30+ years): 4-8% 
    - If 'Original HVAC', 'Original Windows', 'TLC', or 'AS-IS' is mentioned, ensure the score is at least 8%.
    - If 'new roof' or 'new hvac' or 'updated'is mentioned, reduce the score by 1-2%.

    Return ONLY the final percentage as a number (ex. 5.5).
    """ 
    response = client.models.generate_content(model=model_name, contents=prompt)
    return float(response.text.strip())

# 6. The Analysis Logic
if st.button("Analyze Property"):
    if not listing_description:
        st.error("Please paste a description first!")
    else:
        with st.spinner("AI is calculating costs..."):
            # Skim basic details from the address
            ai_pulled_values = get_property_details(address, listing_description)
            price=ai_pulled_values[0]
            year_built=ai_pulled_values[1]
            monthly_rent=ai_pulled_values[2]
            tax_rate=ai_pulled_values[3]
            monthly_HOA=ai_pulled_values[4]
            monthly_insurance=ai_pulled_values[5]

            ai_suggested_val = get_maintenance_estimate(listing_description, year_built)
            # We put it in the sidebar so you can tweak it while looking at the results
            st.sidebar.markdown("---")
            st.sidebar.write("### 🛠️ Manual Override")
            final_maint_percent = st.sidebar.slider(
                "Adjust Maintenance %", 
                0.0, 10.0, 
                float(ai_suggested_val),
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
            monthly_vacancy_reserve=monthly_rent*0.05
            
            total_monthly_expenses = monthly_mortgage + monthly_taxes + monthly_insurance + monthly_HOA + monthly_maint + monthly_vacancy_reserve
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
                st.write("Monthly Cash Flow")

                table_data={
                    "Description": [
                        "Gross Monthly Rent",
                        "Mortgage Payment (P&I)",
                        "Property Taxes",
                        "Insurance",
                        "HOA Fee",
                        "Maintenance (CapEx)",
                        "Vacancy (5%)",  
                        "Total Expenses"             
                                    
                    ],
                    "Amount": [
                        f"${monthly_rent:,.2f}",
                        f"-${monthly_mortgage:,.2f}",
                        f"-${monthly_taxes:,.2f}",
                        f"-${monthly_insurance:,.2f}",
                        f"-${monthly_HOA:,.2f}",
                        f"-${monthly_maint:,.2f}",
                        f"-${monthly_vacancy_reserve:,.2f}",
                        f"**${total_monthly_expenses:,.2f}**"
                    ]
                }
                df= pd.DataFrame(table_data)
                st.table(df)

                st.info(f"Property Age: {datetime.datetime.now().year - year_built} years.")
                st.info(f"Maintenance is calculated at {final_maint_percent}% of property value annually.")

                st.caption("Disclaimer: This is an AI-powered tool for educational purposes. Always verify financial data with a professional before making investment decisions.")

