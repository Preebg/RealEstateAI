# harvester.py
import time
import logging
import json
from google.genai import errors
import engine
from knowledge_base import save_knowledge_base

# --- CONFIGURATION ---
TARGETS_FILE = "targets.txt"
LOG_FILE = "failed_addresses.log"
# Default Investment Parameters (since there is no UI slider in headless mode)
INVESTMENT_PARAMS = {
    "down_payment": 25,
    "interest_rate": 6.0,
    "loan_term": 30,
    "closing_costs_pct": 3.0
}

logging.basicConfig(filename=LOG_FILE, level=logging.ERROR, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def execute_with_backoff(func, *args, **kwargs):
    """Handles 429 Rate Limit errors with exponential backoff."""
    retries = 0
    max_retries = 5
    while retries < max_retries:
        try:
            return func(*args, **kwargs)
        except errors.ClientError as e:
            if e.code == 429:
                wait_time = (2 ** retries)
                print(f"⚠️ Rate limit hit. Backing off for {wait_time}s...")
                time.sleep(wait_time)
                retries += 1
            else:
                raise e
    raise Exception("Max retries exceeded for API rate limits.")

def calculate_headless_cash_flow(data):
    """Replicates the math logic from AIUnderwriterv2.py for headless execution."""
    try:
        price = float(data.get("price", 0))
        rent = float(data.get("rent", 0))
        tax_rate = float(data.get("tax_rate", 0))
        hoa = float(data.get("hoa", 0))
        insurance = float(data.get("insurance", 0))
        maint_pct = float(data.get("maint_percent", 0))
        vac_rate = float(data.get("ai_vacancy_rate", 5.0))
        mgmt_fee_pct = float(data.get("ai_management_fee", 10.0))

        # Mortgage Calculation
        loan_amount = price * (1 - (INVESTMENT_PARAMS["down_payment"] / 100))
        monthly_ir = (INVESTMENT_PARAMS["interest_rate"] / 100) / 12
        total_payments = INVESTMENT_PARAMS["loan_term"] * 12
        
        if monthly_ir > 0:
            monthly_mortgage = loan_amount * (monthly_ir * (1 + monthly_ir)**total_payments) / ((1 + monthly_ir)**total_payments - 1)
        else:
            monthly_mortgage = loan_amount / total_payments

        # Operating Expenses
        monthly_taxes = ((tax_rate / 100) * price) / 12
        monthly_maint = (maint_pct / 100 * rent)
        vacancy_reserve = (vac_rate / 100) * rent
        mgmt_fee = (mgmt_fee_pct / 100) * rent
        
        op_ex = monthly_taxes + hoa + insurance + monthly_maint + vacancy_reserve + mgmt_fee
        cash_flow = rent - (monthly_mortgage + op_ex)
        
        return cash_flow
    except Exception as e:
        print(f"Math Error: {e}")
        return 0.0

def discover_cheap_properties(location, max_price=300000):
    """Uses the researcher agent to find new property addresses under a price cap."""
    print(f"🌐 Searching for properties under ${max_price} in {location}...")
    prompt = f"Find a list of 10-20 residential properties currently for sale in {location} listed for under ${max_price}. Return ONLY a plain list of full addresses, one per line."
    
    # Use the engine's client and primary model
    response = engine.client.models.generate_content(
        model=engine.primary_search_model_name,
        contents=prompt,
        config=engine.types.GenerateContentConfig(
            tools=[engine.types.Tool(google_search=engine.types.GoogleSearch())]
        )
    )
    
    addresses = [line.strip() for line in response.text.split('\n') if line.strip()]
    with open(TARGETS_FILE, "a") as f:
        for addr in addresses:
            f.write(f"{addr}\n")
    print(f"✅ Added {len(addresses)} potential targets to {TARGETS_FILE}")

def main():
    # 1. Discovery Phase (Optional: Change location as needed)
    # discover_cheap_properties("Atlanta, GA") 

    # 2. Load Targets
    try:
        with open(TARGETS_FILE, "r") as f:
            addresses = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"❌ {TARGETS_FILE} not found. Please create it or run discovery.")
        return

    total = len(addresses)
    print(f"🚀 Starting harvest of {total} properties...")

    for idx, address in enumerate(addresses):
        try:
            # Stage 1: Initial Analysis
            initial_data, from_kb = execute_with_backoff(engine.get_initial_analysis, address)
            
            # Stage 2: Final Analysis
            final_data = execute_with_backoff(engine.get_final_analysis, initial_data, address)
            
            # Stage 3: Math & Quantum Probability
            cash_flow = calculate_headless_cash_flow(final_data)
            prob = engine.calculate_quantum_probability(
                cash_flow, 
                final_data.get("forecast_rate", 0), 
                final_data.get("location_score", 0)
            )
            
            # Stage 4: Persistence
            save_knowledge_base(final_data)
            
            # Telemetry
            print(f"[Processing {idx+1}/{total}] {address} - Success: {prob:.2f}% probability")

        except Exception as e:
            print(f"❌ Failed {address}: {str(e)}")
            logging.error(f"Address: {address} | Error: {str(e)}")
            continue

if __name__ == "__main__":
    main()
