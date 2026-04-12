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
primary_search_model_name="gemini-2.5-flash"
secondary_search_model_name="gemini-2.5-flash-lite"
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
    CRITICAL DATA POINTS NEEDED:
    1. The exact 'Annual Property Tax' amount (look for public records or tax history).
    2. The 'Rent Zestimate' or actual 'Rental Listing' prices for similar homes in this specific neighborhood.
        - Attempt to find rent estimates from 'Rentometer.com', 'Rentcast.io', 'Apartments.com', or similar rental sites. If multiple are found provide the average.
    3. The current listing price and year built.
    4. Details on HOA.
    5. Insurance: Look for any mentions of insurance costs in the monthly expenses a website might list
        - If none are found, use local averages based on zip code and label it 'Regional Estimate'.
    
    IMPORTANT: Do NOT provide the 'Estimated Monthly Mortgage' or 'Estimated Monthly Payment'. 
    I need the raw building and market data, not a loan calculation.
    Also, provide a 3-4 sentence summary of the property's condition and any key features or issues mentioned in the listing such as 'new roof', 'original hvac', 'updated kitchen', 'TLC needed', 'AS-IS' etc.
    """

    search_response = run_search_with_failover(search_prompt)
    if not search_response:
        st.error("Both primary and secondary search models failed. Please try again later.")
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0
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

    history_context = get_kb_context()

    #Use analysis model to extract structured data and insights from the raw search context.
    analysis_prompt=f"""
    DATA:{raw_context}
    History:{history_context}

    Task:
    Analyze the NEW Property data. Use the Previous Analysis examples (if any) to provide a better estimate for this new property. Extract the following details in a structured JSON format: 
    1. Extract: Price, Year Built, Estimated Rent, Tax Rate(calculate as: [Annual Tax / Price] * 100), HOA, Insurance.
        - If the DATA provides a 'Regional Estimate' for insurance, label it as such in the summary.
        - If the DATA says $0 or is less than $60 or is missing insurance, use $80-$100 and label it as 'Assumed Minimum' in the summary. If data provides insurance above $600, it is likely a annual tax amount, so divide by 12.
    2. Calculate Maintenance %:
        - New (<5 yrs): 1-2%
        - Mid (10-25 yrs): 2-4%
        - Old (30+ yrs): 4-6%
        - If 'Original HVAC/Windows/TLC/AS-IS': 6-10%
        - If 'New roof/hvac': reduce by 1-2%

    IMPORTANT: For all numeric fields (price, rent, taxes, hoa, insurance, maint_percent), return ONLY the number. 
    Do not include currency symbols, commas, or descriptive text like 'estimated'.
    Return only a JSON object with these keys: "price", "year", "rent", "tax_rate", "hoa", "insurance", "summary", "maint_percent"
    """
    
    try:
        # Only returns JSON object
        response = client.models.generate_content(
            model=analysis_model_name, 
            contents=analysis_prompt, 
            config={
                "response_mime_type": "application/json",
                "thinking_config": {"include_thoughts": False} 
            }
        )
        property_data = json.loads(response.text.strip())
        property_data["sources"] = sources  # Add sources to the property data dictionary
        return property_data
        
    except Exception as e:
        st.error(f"AI Fetch Error: {e}")
        # Fallback values so the rest of the app doesn't crash
        return {
            "price": 0, "year": 2026, "rent": 0, "tax_rate": 1.5, 
            "hoa": 0, "insurance": 100, "summary": "Error fetching data.", "maint_percent": 3.0
        }