from google import genai
import streamlit as st
import json 
import pandas as pd  
from google.genai import errors, types
import os 
from knowledge_base import get_kb_context, get_kb_raw_data
import datetime
from streamlit_gsheets import GSheetsConnection
import time 
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

# 2. API Setup
API_KEY = st.secrets["GEMINI_API_KEY"] 
client = genai.Client(api_key=API_KEY)
primary_search_model_name="gemini-2.5-flash"
secondary_search_model_name="gemini-2.5-flash-lite"
analysis_model_name="gemini-3.1-flash-lite-preview"

KB_FILE = "property_kb.json"

def _extract_json(text):
    """Helper to extract JSON from LLM responses."""
    try:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None

def calculate_10yr_appreciation(current_value, location_score):
    if current_value <= 0:
        return {"future_value": 0, "annual_rate": 0, "total_growth": 0}
        
    # Dynamic rate: Base 3% + (location_score - 5) * 0.5%
    # Result: Score 10 = 5.5%, Score 5 = 3%, Score 0 = 0.5%
    annual_rate = 0.03 + ((location_score - 5) * 0.005)
    future_value = current_value * ((1 + annual_rate) ** 10)
    return {
        "future_value": future_value,
        "annual_rate": annual_rate * 100,
        "total_growth": ((future_value - current_value) / current_value) * 100
    }

def researcher_agent(address, model):
    prompt = f"""Research the property at {address}. 
    CRITICAL: You must cross-reference at least 3 different real estate sources (e.g., Zillow, Redfin, Realtor.com, local MLS) to find the currrent listed price of the home. If the property is not currently listed, insert 9999999 as the price of the home.
    
    Find the following details:
    1. PROPERTY BASICS: Current listing price (or estimated market value), year built, and HOA fees.
    2. TAXES: Total Annual Property Tax (including school and local taxes).
    3. RENT: Rent Zestimate or actual rental listings for similar homes in this specific neighborhood.
    4. INSURANCE: Monthly insurance costs or local zip code averages.
    5. VALUATION: Recent comparable sales (comps) in the immediate area. Provide the names of the properties you used to determine the comps, their sale prices, and how they compare to the target property.
    6. MARKET METRICS: Average vacancy rate and standard property management fees for this neighborhood.
    
    Return the raw findings and explicitly list every URL you visited for verification."""
    
    response = client.models.generate_content(
        model=model, 
        contents=prompt, 
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch()), types.Tool(google_maps=types.GoogleMaps())]
        )
    )
    return response.text

def analyzer_agent(address, research_data, model, kb_context):
    prompt = f"""You are an expert real estate analyst. Your goal is to provide a comprehensive underwrite for the property at {address}.
    
    CONTEXT FROM DATABASE:
    {kb_context}
    (Only use properties analyzed within the past 6 months for comparison).

    RESEARCH DATA:
    {research_data}
    If the price given is 9999999, it means the property is not currently listed and you must use the comps and market data to estimate a realistic listing price. Do not leave the price as 9999999 in your final JSON output.
    OUTPUT FORMAT:
    Return ONLY a JSON object with these keys:
    {{
        "price": number,
        "year": number,
        "rent": number,
        "tax_rate": number, (Annual Tax / Price * 100)
        "hoa": number,
        "insurance": number, (Monthly cost - if research provides annual, divide by 12 (it's likely annual amount if the value is above $400))),
        "summary": "3-4 sentence summary of condition, features, and any 'TLC' or 'Updated' notes",
        "maint_percent": number, (New <5yr: 1-2%, Mid 10-25yr: 2-4%, Old 30+yr: 4-6%. Adjust for condition),
        "predicted_value": number,
        "prediction_reasoning": "1-2 sentence explanation based on the comps found and list the name of the properties you used as comps",
        "location_score": number, (0-10 based on transit/schools),
        "vacancy_rate": number,
        "management_fee": number,
        "property_label": "A dynamic label (e.g., 'Cash-flower', 'Appreciation Machine', 'Value-Add Play', 'High-Risk Speculation') based on the financial metrics"
    }}
    IMPORTANT: No currency symbols, no commas, no markdown prose outside the JSON. The 'price' should be the active listing price; if unavailable, use the most recent sale price or a reliable market estimate found in the research."""
    
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text

def checker_agent(analysis_json, listing_price, research_data, model):
    prompt = f"""You are a verification agent. Compare the following Analysis JSON against the Raw Research Data.
    
    Analysis JSON:
    {analysis_json}
    
    Raw Research Data:
    {research_data}
    
    Rules:
    1. The 'price' in the JSON must match the listing price or the best available market estimate found in the research data. If the AI previously guessed, correct it to the actual listing price.
    2. The 'predicted_value' MUST NOT be equal to the listing price ({listing_price}). It must be a reasoned estimate based on the comps found in the research.
    3. The 'insurance' value MUST be a monthly amount. If the research data shows an annual figure (e.g., $1,200/yr), you must divide it by 12 (e.g., $100/mo).
    4. Sanity Check: Ensure all numbers are reasonable. (e.g., Insurance should not be $1,000+/mo for a standard home; tax_rate should be a percentage, not a total dollar amount).
    5. Ensure all required keys are present.
    
    If the JSON is incorrect, fix it based on the research data. Return the corrected JSON object ONLY."""
    
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text

def get_initial_analysis(address):
    """Stage 1: Fast research and basic analysis for immediate display."""
    kb_data = get_kb_raw_data()
    if address in kb_data:
        return kb_data[address], True, None
    
    # Researcher -> Analyzer
    research_results = researcher_agent(address, primary_search_model_name)
    kb_context = get_kb_context()
    analysis_results = analyzer_agent(address, research_results, analysis_model_name, kb_context)
    
    extracted = _extract_json(analysis_results)
    if extracted is None:
        # Fallback if the analyzer fails to return JSON
        return {"price": 0, "summary": "AI failed to generate a valid analysis. Please try again.", "location_score": 0, "predicted_value": 0}, False, research_results
        
    return extracted, False, research_results

def get_final_analysis(initial_data, address, research_results=None):
    """Stage 2: Verification, detailed mapping, and forecasting."""
    # Checker - Only run if we have research data (not from KB)
    if research_results:
        listing_price = initial_data.get("price", 0)
        final_json_text = checker_agent(json.dumps(initial_data), listing_price, research_results, analysis_model_name)
        property_data = _extract_json(final_json_text)
        
        # Fallback: If the checker agent fails to return valid JSON, use the initial analysis
        if property_data is None:
            property_data = initial_data
    else:
        property_data = initial_data
    
    # Mapping and Forecast
    property_data["sources"] = [f"https://www.google.com/search?q={address.replace(' ', '+')}"]
    property_data["ai_vacancy_rate"] = property_data.get("vacancy_rate", 5.0)
    property_data["ai_management_fee"] = property_data.get("management_fee", 10.0)
    
    forecast = calculate_10yr_appreciation(
        property_data.get("predicted_value", 0), 
        property_data.get("location_score", 0)
    )
    property_data["appreciation_forecast"] = forecast["future_value"]
    property_data["forecast_rate"] = forecast["annual_rate"]
    property_data["forecast_growth"] = forecast["total_growth"]
    
    return property_data

def calculate_quantum_probability(cash_flow, forecast_rate, location_score):
    """
    Simulates the probability of investment success using a quantum circuit.
    Maps financial metrics to qubit rotations.
    """
    # Normalize inputs to 0-1 range for rotation (pi/2)
    cf_norm = min(max(cash_flow / 1000, 0), 1) 
    rate_norm = min(max(forecast_rate / 10, 0), 1)
    loc_norm = location_score / 10

    qc = QuantumCircuit(1)
    # Apply rotations based on the three variables to shift state toward |1>
    qc.ry(cf_norm * 3.14159, 0)
    qc.ry(rate_norm * 3.14159, 0)
    qc.ry(loc_norm * 3.14159, 0)
    qc.measure_all()

    simulator = AerSimulator()
    compiled_circuit = transpile(qc, simulator)
    job = simulator.run(compiled_circuit, shots=1024)
    result = job.result().get_counts()
    
    success_count = result.get('1', 0)
    return (success_count / 1024) * 100
