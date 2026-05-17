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
primary_search_model_name="gemini-2.5-flash-lite"
secondary_search_model_name="gemini-2.5-flash"
analysis_model_name="gemini-3.1-flash-lite-preview"

KB_FILE = "property_kb.json"

def _extract_json(text):
    """Helper to extract JSON from LLM responses."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)

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
    CRITICAL: Find the current, active listing price. Cross-reference multiple sources (e.g., Zillow, Redfin, Realtor.com) to ensure the price is accurate and up-to-date.
    
    Find:
    1. Exact current listing price, year built, HOA fees.
    2. Annual Property Tax.
    3. Rent Zestimate/comparable rentals.
    4. Monthly insurance costs.
    5. Recent comparable sales (comps) in the immediate area.
    6. Average vacancy rate and management fees for the neighborhood.
    Return the raw findings clearly."""
    
    response = client.models.generate_content(
        model=model, 
        contents=prompt, 
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch()), types.Tool(google_maps=types.GoogleMaps())]
        )
    )
    return response.text

def analyzer_agent(address, research_data, model):
    prompt = f"""You are an expert real estate analyst. Based on this research:
    {research_data}
    
    Provide a comprehensive underwrite for {address}.
    IMPORTANT: The 'predicted_value' must be an independent estimate based on the comps found. 
    It must NEVER be identical to the listing price.
    
    Return ONLY a JSON object. 
    CRITICAL: The 'price' field must be the exact current listing price found in the research. Do not average or estimate this value.
    Ensure 'rent', 'hoa', and 'insurance' are provided as MONTHLY values:
    {{
        "price": number,
        "year": number,
        "rent": number,
        "tax_rate": number,
        "hoa": number,
        "insurance": number, // Monthly insurance cost
        "summary": "3-4 sentence summary",
        "maint_percent": number,
        "predicted_value": number,
        "prediction_reasoning": "1-2 sentence explanation",
        "location_score": number,
        "vacancy_rate": number,
        "management_fee": number
    }}"""
    
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text

def checker_agent(analysis_json, listing_price, research_data, model):
    prompt = f"""You are a verification agent. Compare the following Analysis JSON against the Raw Research Data.
    
    Analysis JSON:
    {analysis_json}
    
    Raw Research Data:
    {research_data}
    
    Rules:
    1. The 'price' in the JSON must exactly match the active listing price found in the research data.
    2. The 'predicted_value' MUST NOT be equal to the listing price ({listing_price}). It must be a reasoned estimate based on the comps found in the research.
    3. Ensure all required keys are present.
    
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
    analysis_results = analyzer_agent(address, research_results, analysis_model_name)
    return _extract_json(analysis_results), False, research_results

def get_final_analysis(initial_data, address, research_results=None):
    """Stage 2: Verification, detailed mapping, and forecasting."""
    # Checker - Only run if we have research data (not from KB)
    if research_results:
        listing_price = initial_data.get("price", 0)
        final_json_text = checker_agent(json.dumps(initial_data), listing_price, research_results, primary_search_model_name)
        property_data = _extract_json(final_json_text)
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
