# knowledge_base.py
import streamlit as st
from supabase import create_client, Client
import pandas as pd
import json

# Initialize Supabase
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_API_KEY"]
supabase: Client = create_client(url, key)

def get_kb_raw_data():
    """Fetches all properties from Supabase and returns a dictionary."""
    try:
        # We query the 'properties' table you just created
        response = supabase.table("properties").select("*").execute()
        data = response.data
        
        if not data:
            return {}
            
        # Your engine expects a dictionary keyed by address
        return {item['address']: item for item in data}
    except Exception as e:
        print(f"Supabase Fetch Error: {e}")
        return {}

def save_knowledge_base(property_data):
    """Saves or Updates a property in Supabase."""
    try:
        # Create a copy to avoid mutating the original dict
        payload = property_data.copy()
        
        # 1. Clean up data types (Supabase/Postgres is stricter than GSheets)
        # Convert lists to JSON strings if they aren't already
        if "sources" in payload and isinstance(payload["sources"], list):
            # No need to json.dumps, the supabase-py lib handles lists for JSONB columns!
            pass 
            
        # 2. Match your SQL column names exactly
        # If your dictionary has extra keys from the LLM, we filter for only what's in SQL
        allowed_columns = [
            "address", "price", "year_built", "rent", "tax_rate", 
            "hoa", "insurance", "summary", "maint_percent", 
            "predicted_value", "prediction_reasoning", "location_score", 
            "property_label", "quantum_risk_score", "sources"
        ]
        
        filtered_payload = {k: v for k, v in payload.items() if k in allowed_columns}

        # 3. The 'Upsert' (Update or Insert)
        # This tells Supabase: "If this address exists, update it. If not, make a new row."
        supabase.table("properties").upsert(filtered_payload, on_conflict="address").execute()
        
        st.success(f"Successfully synced {payload['address']} to Supabase.")
    except Exception as e:
        st.error(f"Failed to save to Supabase: {e}")

def get_kb_context():
    """Pulls recent examples for the LLM."""
    try:
        response = supabase.table("properties").select("address, rent, predicted_value").limit(3).execute()
        if not response.data: return ""
        
        context = "\n--- RECENT ANALYSES ---\n"
        for item in response.data:
            context += f"Address: {item['address']} | Predicted: {item['predicted_value']}\n"
        return context
    except:
        return ""
