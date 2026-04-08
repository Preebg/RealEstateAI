from google import genai
import streamlit as st

# 1. Setup the Web Interface
st.set_page_config(page_title="AI Property Scout", page_icon="🏠")
st.title("🏠 AI Property Analyzer")
st.write("Enter details below to get an AI-calculated Risk-Adjusted Cap Rate.")

# 2. API Setup
API_KEY = st.secrets["GEMINI_API_KEY"] 
client = genai.Client(api_key=API_KEY)

# 3. Sidebar for Inputs (Instead of hardcoded variables)
with st.sidebar:
    st.header("Property Stats")
    price = st.number_input("Purchase Price ($)", value=400000)
    monthly_rent = st.number_input("Monthly Rent ($)", value=2500)
    year_built = st.number_input("Year Built", value=1975)

listing_description = st.text_area("Listing Description", placeholder="Paste Description of the property here...")

# 3. The "Expert" AI Function
def get_maintenance_estimate(description, year):
    current_year = 2026
    age = current_year - year
    
    # We added the "Conservative Investor" rules here to fix the 1.5% issue
    prompt = f"""
    Act as a Conservative Real Estate Auditor. 
    Analyze this {age}-year-old property.
    Description: {description}

    RULES for Annual Maintenance %:
    - New Construction (<5 years): 1-2%
    - Mid-Age (10-25 years): 2-4%
    - Old/Original (30+ years): 5-8% 
    - If 'Original HVAC', 'Original Windows', or 'TLC' is mentioned, ensure the score is at least 6%.
    - If 'new roof' or 'new hvac' or 'updated'is mentioned, reduce the score by 1-2%.

    Return ONLY the final percentage as a number (e.g. 5.5).
    """ 
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return float(response.text.strip())

# 4. The Analysis Logic
if st.button("Analyze Property"):
    if not listing_description:
        st.error("Please paste a description first!")
    else:
        with st.spinner("AI is calculating costs..."):
            # Get the AI's starting point
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
            annual_maint_cost = (final_maint_percent / 100) * price
            annual_income = monthly_rent * 12
            noi = annual_income - annual_maint_cost
            cap_rate = (noi / price) * 100

            # 6. Display Results
            st.divider()
            col1, col2 = st.columns(2)
            
            # Show the user-adjusted number
            col1.metric("CapEx", f"{final_maint_percent}%", f"${annual_maint_cost:,.0f}/yr")
            col2.metric("Risk-Adjusted Cap Rate", f"{cap_rate:.2f}%")
            
            st.warning(f"Note: Using a {final_maint_percent}% maintenance rate for a house built in {year_built}.")

