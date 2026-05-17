# knowledge_base.py
import streamlit as st
from supabase import create_client, Client
import pandas as pd
import json

def get_client():
    """Returns a Supabase client, ensuring it is properly defined."""
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

def get_kb_raw_data():
    """Fetches all properties from Supabase."""
    try:
        supabase = get_client() # This defines 'supabase' inside the method scope
        response = supabase.table("properties").select("*").execute()
        data = response.data
        
        if not data:
            return {}
            
        return {item['address']: item for item in data}
    except Exception as e:
        print(f"Supabase Fetch Error: {e}")
        return {}

def save_knowledge_base(property_data):
    """Saves or Updates a property in Supabase."""
    try:
        supabase = get_client() # This defines 'supabase' inside the method scope
        payload = property_data.copy()
        
        # Ensure numbers are cleaned for PostgreSQL NUMERIC types
        for key in ["price", "rent", "tax_rate", "location_score", "predicted_value"]:
            if key in payload:
                # Use your existing safe_float logic or clean here
                val = str(payload[key]).replace('$', '').replace(',', '').strip()
                try:
                    payload[key] = float(val)
                except:
                    payload[key] = 0.0

        allowed_columns = [
            "address", "price", "year_built", "rent", "tax_rate", 
            "hoa", "insurance", "summary", "maint_percent", 
            "predicted_value", "prediction_reasoning", "location_score", 
            "property_label", "quantum_risk_score", "sources"
        ]
        
        filtered_payload = {k: v for k, v in payload.items() if k in allowed_columns}

        # The 'Upsert'
        response = supabase.table("properties").upsert(filtered_payload, on_conflict="address").execute()
        
        print(f"DEBUG: Success! Row added: {response.data}")
        return response
    except Exception as e:
        print(f"Full Error Detail: {e}")
        st.error(f"Failed to save to Supabase: {e}")

def get_kb_context():
    """Pulls recent examples for the LLM."""
    try:
        supabase = get_client()
        response = supabase.table("properties").select("address, rent, predicted_value").limit(3).execute()
        if not response.data: return ""
        
        context = "\n--- RECENT ANALYSES ---\n"
        for item in response.data:
            context += f"Address: {item['address']} | Predicted: {item['predicted_value']}\n"
        return context
    except:
        return ""
