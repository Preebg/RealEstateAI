# knowledge_base.py
import json
from streamlit_gsheets import GSheetsConnection
import streamlit as st
import pandas as pd


#Saves every input into a local JSON file as a simple knowledge base for future reference and AI learning. Each property is stored under its address as the key, with all the details in a nested dictionary.
def get_kb_raw_data():
    try:
        conn = st.connection("gsheets", type="streamlit_gsheets.gsheets_connection.GSheetsConnection")
        # 1. ttl=0 forces it to ignore the cache and get LIVE data
        df = conn.read(ttl=0) 
        
        if df.empty:
            return {}

        # 2. If you saved the same address twice, this keeps only the NEWEST one
        df = df.drop_duplicates(subset=['address'], keep='last')

        # 3. Clean up the 'rent' column to ensure it's a clean number
        if 'rent' in df.columns:
            df['rent'] = pd.to_numeric(df['rent'], errors='coerce').fillna(0)
            
        return df.set_index("address").to_dict('index')
    except Exception as e:
        # 4. Change st.error to print so it doesn't clutter your UI if it's just a warning
        print(f"DB Sync Note: {e}") 
        return {}

def save_knowledge_base(property_data):
    conn = st.connection("gsheets", type="streamlit_gsheets.gsheets_connection.GSheetsConnection")
    
    try:
        df = conn.read(ttl=0)
    except:
        df = pd.DataFrame()

    # 1. REMOVE any existing entry for this address before adding the new one
    if not df.empty and "address" in df.columns:
        df = df[df["address"] != property_data["address"]]

    # 2. Prepare the data & Add Timestamp
    property_data["timestamp"] = pd.Timestamp.now().isoformat()
    property_data = property_data.copy()
    if "sources" in property_data and isinstance(property_data["sources"], list):
        property_data["sources"] = json.dumps(property_data["sources"])

    # 3. Add the new (overridden) entry
    new_row = pd.DataFrame([property_data])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    
    # 4. Save back to the cloud
    conn.update(data=updated_df)

def get_kb_context():
    """Pulls recent examples to help the AI learn style."""
    try:
        df = get_kb_raw_data()
        if not df: return ""
        
        # Get last 3 addresses
        examples = list(df.items())[-3:]
        context = "\n--- PREVIOUS ANALYSIS EXAMPLES ---\n"
        for addr, data in examples:
            context += f"Address: {addr}\nRent: {data.get('rent')}\nMaint: {data.get('maint_percent')}%\nValue: {data.get('predicted_value')}\n"
        return context
    except:
        return ""
