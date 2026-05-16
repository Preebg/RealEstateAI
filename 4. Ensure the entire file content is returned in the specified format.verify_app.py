from streamlit.testing.v1 import AppTest

def run_verification():
    print("Starting App...")
    # Initialize the AppTest with the main entry point
    # Increased timeout for initial load
    at = AppTest.from_file("AIUnderwriterv2.py").run(timeout=10)

    print("Authenticating...")
    # Find password input by label (case-insensitive) or fallback to index 0
    password_input = next((ti for ti in at.text_input if "password" in ti.label.lower()), at.text_input[0])
    password_input.set_value("betaINVESTOR12110").run(timeout=10)
    
    # Attempt to click a submit/login button if one exists to finalize authentication
    login_btns = [btn for btn in at.button if btn.label in ["Submit", "Login", "Enter"]]
    if login_btns:
        login_btns[0].click().run(timeout=10)

    print("Inputting Address...")
    # Find the address input specifically by its label "Address"
    address_input = next((ti for ti in at.text_input if ti.label == "Address"), None)
    if address_input:
        address_input.set_value("123 Main St, Springfield, IL").run(timeout=10)
    else:
        print("❌ Error: Address input field not found.")
        exit(1)

    print("Waiting for Gemini API...")
    print(f"Buttons found: {len(at.button)}")
    
    # Search for the button by its label
    analyze_btns = [btn for btn in at.button if btn.label == 'Analyze Property']
    
    if analyze_btns:
        # The analysis process involves multiple API calls and search grounding.
        # We increase the timeout significantly (e.g., 300 seconds) to allow the AI to finish.
        analyze_btns[0].click().run(timeout=300)
    else:
        print("❌ Error: 'Analyze Property' button not found.")
        exit(1)

    print("Checking Results...")
    # Verify that the results are rendered in the UI. 
    # We check for the existence of the 'Monthly Take-Home' metric.
    try:
        # The metric is located in tab1, but AppTest can access it via the global list
        found_metric = any("Monthly Take-Home" in m.label for m in at.metric)
        
        if found_metric:
            print("✅ Verification Successful: Results appeared in the UI.")
        else:
            print("❌ Verification Failed: 'Monthly Take-Home' metric not found.")
            exit(1)
            
    except Exception as e:
        print(f"❌ Verification Failed with error: {e}")
        exit(1)

if __name__ == "__main__":
    run_verification()
