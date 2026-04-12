# knowledge_base.py
import json
import os

KB_FILE = "property_kb.json"
#Saves every input into a local JSON file as a simple knowledge base for future reference and AI learning. Each property is stored under its address as the key, with all the details in a nested dictionary.
def save_knowledge_base(property_data):
    """Saves the property dictionary to a permanent JSON file."""
    kb = {}
    if os.path.exists(KB_FILE):
        try: 
            with open(KB_FILE, "r") as f:
                kb = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            kb = {}
    if not os .path.exists(KB_FILE):
        return "No previous examples found. Use your best judgement for this first one!"
    # Use address as the unique ID for the house
    address = property_data.get("address", "Unknown Address")
    kb[address] = property_data

    with open(KB_FILE, "w") as f:
        json.dump(kb, f, indent=4)

def get_kb_context():
    """Pulls the last 3 saved properties to teach the AI your style."""
    if not os.path.exists(KB_FILE):
        return ""
    try:
        with open(KB_FILE, "r") as f:
            kb = json.load(f)
        
        if not kb:
            return ""

        # Format the last 3 examples for the AI prompt
        examples = list(kb.values())[-3:]
        context = "\n--- PREVIOUS ANALYSIS EXAMPLES ---\n"
        for ex in examples:
            context += f"Address: {ex.get('address')}\nRent: {ex.get('rent')}\nMaint: {ex.get('maint_percent')}%\n"
        return context
    except:
        return ""
    
def get_kb_raw_data():
    if not os.path.exists(KB_FILE):
        return {}
    with open(KB_FILE, "r") as f:
        return json.load(f)