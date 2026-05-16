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

@st.cache_data(persist="disk", show_spinner=False)
def get_property_details(address):
    kb_data = get_kb_raw_data()
    if address in kb_data:
        data = kb_data[address]
        data["from_kb"] = True 
        return data
    
    raw_context = "" # No longer needed as a separate step
    previously_analyzed = get_kb_context()

    # Master Research & Analysis Prompt
    master_prompt = f"""
    You are an expert real estate analyst. Your goal is to provide a comprehensive underwrite for the property at {address}.
    
    CONTEXT FROM DATABASE:
    {previously_analyzed}
    (Only use properties analyzed within the past 6 months for comparison).

    RESEARCH TASK:
    Use your search tools to find and synthesize the following:
    1. PROPERTY BASICS: Current listing price, year built, and HOA fees.
    2. TAXES: Find the total Annual Property Tax (including school and local taxes). If not found, estimate based on the zip code average.
    3. RENT: Find the Rent Zestimate or actual rental listings for similar homes in this specific neighborhood (use Rentometer, Rentcast, etc.). For multifamily, calculate total building rent.
    4. INSURANCE: Find monthly insurance costs or use local zip code averages.
    5. VALUATION: Research recent comparable sales (comps) in the immediate area to determine a fair market 'predicted_value'.
    6. MARKET METRICS: Research the current average vacancy rate and standard property management fees for this specific neighborhood/city.

    OUTPUT FORMAT:
    Return ONLY a JSON object with these keys:
    {{
        "price": number,
        "year": number,
        "rent": number,
        "tax_rate": number, (Annual Tax / Price * 100)
        "hoa": number,
        "insurance": number,
        "summary": "3-4 sentence summary of condition, features, and any 'TLC' or 'Updated' notes",
        "maint_percent": number, (New <5yr: 1-2%, Mid 10-25yr: 2-4%, Old 30+yr: 4-6%. Adjust for condition),
        "predicted_value": number,
        "prediction_reasoning": "1-2 sentence explanation based on the comps found",
        "location_score": number, (0-10 based on transit/schools),
        "vacancy_rate": number,
        "management_fee": number
    }}
    IMPORTANT: No currency symbols, no commas, no markdown prose outside the JSON.
    """
    
    try:
        # Single consolidated call with Tools
        response = client.models.generate_content(
            model=analysis_model_name, 
            contents=master_prompt, 
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch()), types.Tool(google_maps=types.GoogleMaps())]
            )
        )
        
        if not response.text:
            raise ValueError("AI returned an empty response")

        # 1. Extract Sources from the response metadata
        sources_set = set()
        try:
            candidate = response.candidates[0]
            metadata = getattr(candidate, 'grounding_metadata', None)
            if metadata:
                chunks = getattr(metadata, 'grounding_chunks', [])
                for chunk in chunks:
                    web_source = getattr(chunk, 'web', None)
                    if web_source and hasattr(web_source, 'uri'):
                        uri = web_source.uri
                        if uri and "google.com/search" not in uri.lower():
                            sources_set.add(uri)
            if not sources_set:
                sources_set.add(f"https://www.google.com/search?q={address.replace(' ', '+')}")
        except:
            sources_set.add(f"https://www.google.com/search?q={address.replace(' ', '+')}")

        # 2. Robust JSON extraction
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        property_data = json.loads(text)
        property_data["sources"] = list(sources_set)
        
        # Map keys to app format
        property_data["ai_vacancy_rate"] = property_data.get("vacancy_rate", 5.0)
        property_data["ai_management_fee"] = property_data.get("management_fee", 10.0)
        
        # Calculate 10-Year Forecast
        forecast = calculate_10yr_appreciation(
            property_data.get("predicted_value", 0), 
            property_data.get("location_score", 0)
        )
        property_data["appreciation_forecast"] = forecast["future_value"]
        property_data["forecast_rate"] = forecast["annual_rate"]
        property_data["forecast_growth"] = forecast["total_growth"]
        
        return property_data
        
    except Exception as e:
        st.error(f"AI Analysis Error: {e}")
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0,
            "predicted_value": 0, "prediction_reasoning": "Error predicting value.", "location_score": 0,
            "ai_vacancy_rate": 5.0, "ai_management_fee": 10.0, "appreciation_forecast": 0, "forecast_rate": 0, "forecast_growth": 0,
            "sources": []
        }
