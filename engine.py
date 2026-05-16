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
    prompt = f"""Research the property at {address}. Find:
    1. Listing price, year built, HOA fees.
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
    
    Return ONLY a JSON object:
    {{
        "price": number,
        "year": number,
        "rent": number,
        "tax_rate": number,
        "hoa": number,
        "insurance": number,
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

def checker_agent(analysis_json, listing_price, model):
    prompt = f"""Verify this real estate analysis JSON:
    {analysis_json}
    
    Rules:
    1. Ensure all required keys are present.
    2. The 'predicted_value' MUST NOT be equal to the listing price ({listing_price}).
    If it is equal, adjust the predicted_value slightly based on market logic.
    Return the corrected JSON object ONLY."""
    
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text

@st.cache_data(persist="disk", show_spinner=False)
def get_property_details(address):
    kb_data = get_kb_raw_data()
    if address in kb_data:
        data = kb_data[address]
        data["from_kb"] = True 
        return data
    
    previously_analyzed = get_kb_context()
    
    try:
        # Agentic Workflow to lower latency by using specialized models
        # 1. Researcher (Fast search model)
        research_results = researcher_agent(address, primary_search_model_name)
        
        # 2. Analyzer (High-reasoning model)
        analysis_results = analyzer_agent(address, research_results, analysis_model_name)
        
        # 3. Checker (Fast validation model)
        # Extract listing price from analysis for the checker
        try:
            temp_data = json.loads(analysis_results.split("```json")[1].split("```")[0].strip() if "```json" in analysis_results else analysis_results)
            listing_price = temp_data.get("price", 0)
        except:
            listing_price = 0
            
        final_json_text = checker_agent(analysis_results, listing_price, primary_search_model_name)
        
        # Robust JSON extraction
        text = final_json_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        property_data = json.loads(text)
        
        # Source extraction (from the researcher's original response)
        # Note: In a full agentic flow, we'd pass the response object, but for brevity:
        property_data["sources"] = [f"https://www.google.com/search?q={address.replace(' ', '+')}"]
        
        # Map keys and calculate forecast (Keep existing logic)
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
        
    except Exception as e:
        st.error(f"Agentic Analysis Error: {e}")
        return {
            "price": 0, "year": datetime.datetime.now().year, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0,
            "predicted_value": 0, "prediction_reasoning": "Error predicting value.", "location_score": 0,
            "ai_vacancy_rate": 5.0, "ai_management_fee": 10.0, "appreciation_forecast": 0, "forecast_rate": 0, "forecast_growth": 0,
            "sources": []
        }

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
