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

def run_search_with_failover(prompt):
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    
    # We will try 3 times before giving up
    for attempt in range(3):
        try:
            return client.models.generate_content(
                model=primary_search_model_name,
                contents=prompt,
                config=config
            )
        except errors.ClientError as e:
            # If 503 (Overloaded) or 429 (Rate Limit)
            if e.code in [503, 429]:
                # If it's the last attempt, try the secondary model as a hail mary
                if attempt == 2:
                    return client.models.generate_content(
                        model=secondary_search_model_name,
                        contents=prompt,
                        config=config
                    )
                
                # Otherwise, wait and try again (1s, 2s)
                time.sleep(attempt + 1) 
                continue
            else:
                # If it's a different error, show a clean message
                st.error("The search service is briefly busy. Please refresh in a moment.")
                return None
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

@st.cache_data(persist="disk", show_spinner=False)
def get_property_details(address):
    kb_data = get_kb_raw_data()
    if address in kb_data:
        data = kb_data[address]
        data["from_kb"] = True 
        return data
    
    #Search for property details using Google search tool in Gemini. 
    search_prompt = f"""
    Search for the current property listing of {address}.
    You are an expert real estate analyst with access to the web and public records. Extract the following details about the property in a structured JSON format:
    CRITICAL DATA POINTS NEEDED:
    1. The exact 'Annual Property Tax' amount (look for public records or tax history).
        - The property tax must include the school tax and any other local taxes, not just the county tax. If not found, use the average property tax rate for the zip code and calculate an estimated tax based on the price. Note in the summary if this is an estimate based on zip code average.
    2. The 'Rent Zestimate' or actual 'Rental Listing' prices for similar homes in this specific neighborhood.
        - Attempt to find rent estimates from 'Rentometer.com', 'Rentcast.io', 'Apartments.com', or similar rental sites. If multiple are found provide the average.
        - If it is a multifamily property, look for the total rent for the entire building, not per unit. If only per unit rents are found, multiply by the number of units to get a total rent estimate.
    3. The current listing price and year built.
    4. Details on HOA.
    5. Insurance: Look for any mentions of insurance costs in the monthly expenses a website might list
        - Provide insurance costs as a monthly amount. If only annual insurance is found, divide by 12 and note in the summary that it was annual data converted to monthly.
        - If none are found, use local averages based on zip code.
    
    IMPORTANT: Do NOT provide the 'Estimated Monthly Mortgage' or 'Estimated Monthly Payment'. 
    I need the raw building and market data, not a loan calculation.
    Also, provide a 3-4 sentence summary of the property's condition and any key features or issues mentioned in the listing such as 'new roof', 'original hvac', 'updated kitchen', 'TLC needed', 'AS-IS' etc.
    """

    search_response = run_search_with_failover(search_prompt)
    if not search_response:
        st.error("Both primary and secondary search models failed. Please try again later.")
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0,
            "ai_vacancy_rate": 5.0, "ai_management_fee": 10.0, "appreciation_forecast": 0, "forecast_rate": 0, "forecast_growth": 0
        }

    sources_set = set()
    try:
        # 1. Access the first candidate and grounding_metadata
        candidate = search_response.candidates[0]
        metadata = getattr(candidate, 'grounding_metadata', None)
        
        if metadata:
            # 2. Extract Chunks (The modern SDK path)
            chunks = getattr(metadata, 'grounding_chunks', [])
            for chunk in chunks:
                # Use a more direct check for the 'web' attribute
                web_source = getattr(chunk, 'web', None)
                if web_source and hasattr(web_source, 'uri'):
                    uri = web_source.uri
                    # Exclude the generic search page but keep the actual listings
                    if uri and "google.com/search" not in uri.lower():
                        sources_set.add(uri)
            
            # 3. Fallback to Search Entry Point if no specific links found
            if not sources_set:
                sep = getattr(metadata, 'search_entry_point', None)
                if sep and hasattr(sep, 'rendered_content'):
                    sources_set.add(f"https://www.google.com/search?q={address.replace(' ', '+')}")

        # 4. Final safety check: Always give the user a button to click
        if not sources_set:
            # Force a Zillow link as a last resort
            zillow_slug = address.replace(' ', '-')
            sources_set.add(f"https://www.zillow.com/homes/{zillow_slug}_rb/")

        sources = list(sources_set)
        
    except Exception as e:
        # If metadata is missing entirely, at least provide a search link
        sources = [f"https://www.google.com/search?q={address.replace(' ', '+')}"]


    raw_context = search_response.text.strip()
    if not raw_context:
        raw_context = "Search returned no text."

    previously_analyzed = get_kb_context()

    # Consolidated Master Prompt
    analysis_prompt = f"""
    DATA: {raw_context}
    Other Properties With Accurate Analysis: {previously_analyzed}
    Only use properties that have been analyzed within the past 6 months for this analysis. 

    Task:
    Analyze the property at {address}. Use the provided DATA and your search tools to extract and predict the following in a single structured JSON object:

    1. PROPERTY DETAILS:
       - price: Current listing price (number only).
       - year: Year built (number only).
       - rent: Estimated monthly rent (number only).
       - tax_rate: Annual Property Tax / Price * 100 (number only).
       - hoa: Monthly HOA fee (number only).
       - insurance: Monthly insurance cost (number only). If annual, divide by 12.
       - summary: 3-4 sentence summary of condition and key features.
       - maint_percent: Maintenance % based on age (New <5yr: 1-2%, Mid 10-25yr: 2-4%, Old 30+yr: 4-6%). Adjust for 'TLC/AS-IS' (up to 10%) or 'New Roof/HVAC' (reduce 1-2%).

    2. VALUATION & LOCATION:
       - predicted_value: Fair market value based on recent comps (number only).
       - prediction_reasoning: 1-2 sentence explanation of the valuation.
       - location_score: Neighborhood score from 0-10 based on transit and schools.

    3. OPERATING METRICS:
       - vacancy_rate: Realistic annual vacancy % for this neighborhood.
       - management_fee: Standard local property management fee %.

    IMPORTANT: Return ONLY a JSON object. Do not include currency symbols, commas, or markdown prose outside the JSON.
    """
    
    try:
        # Consolidated call with Tools enabled (No mime_type allowed with tools)
        response = client.models.generate_content(
            model=analysis_model_name, 
            contents=analysis_prompt, 
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch()), types.Tool(google_maps=types.GoogleMaps())]
            )
        )
        
        if not response.text:
            raise ValueError("AI returned an empty response")

        # Robust JSON extraction to prevent "Expecting value" error
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        property_data = json.loads(text)
        property_data["sources"] = sources 
        
        # Map consolidated keys to the expected app format
        property_data["ai_vacancy_rate"] = property_data.get("vacancy_rate", 5.0)
        property_data["ai_management_fee"] = property_data.get("management_fee", 10.0)
        
        # Calculate 10-Year Forecast (Local math, no API call)
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
        # Fallback values so the rest of the app doesn't crash
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0,
            "predicted_value": 0, "prediction_reasoning": "Error predicting value.", "location_score": 0,
            "ai_vacancy_rate": 5.0, "ai_management_fee": 10.0, "appreciation_forecast": 0, "forecast_rate": 0, "forecast_growth": 0
        }
