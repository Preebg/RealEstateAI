# knowledge_base.py
import json
from streamlit_gsheets import GSheetsConnection
import streamlit as st
import pandas as pd


#Saves every input into a local JSON file as a simple knowledge base for future reference and AI learning. Each property is stored under its address as the key, with all the details in a nested dictionary.
def get_kb_raw_data():
    """Fetches all property data from the private Google Sheet."""
    try:
        conn = st.connection("gsheets", type="streamlit_gsheets.gsheets_connection.GSheetsConnection")
        df = conn.read(ttl=0)
        # Convert 'sources' column back from string to list if it exists
        if not df.empty and "sources" in df.columns:
            df['sources'] = df['sources'].apply(lambda x: json.loads(x) if isinstance(x, str) and x.startswith('[') else x)
        return df.set_index("address").to_dict('index')
    except Exception as e:
        st.error(f"Error loading database: {e}")
        return {}

def save_knowledge_base(property_data):
    """Appends new property data to the private Google Sheet."""
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # Read existing data
    try:
        df = conn.read()
    except:
        df = pd.DataFrame()

    # Convert sources list to string for spreadsheet storage
    if "sources" in property_data and isinstance(property_data["sources"], list):
        property_data["sources"] = json.dumps(property_data["sources"])

    # Add the new property
    new_row = pd.DataFrame([property_data])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    
    # Save back to cloud
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
            context += f"Address: {addr}\nRent: {data.get('rent')}\nMaint: {data.get('maint_percent')}%\n"
        return context
    except:
        return ""