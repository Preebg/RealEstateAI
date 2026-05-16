from streamlit.testing.v1 import AppTest

def run_verification():
    print("Starting App...")
    # Initialize the AppTest with the main entry point
    # Increased timeout for initial load
    at = AppTest.from_file("AIUnderwriterv2.py").run(timeout=10)

    print("Authenticating...")
    # Set the password in the first text input and run to trigger authentication
    at.text_input[0].set_value("betaINVESTOR12110").run(timeout=10)
    
    # Attempt to click a submit/login button if one exists to finalize authentication
    login_btns = [btn for btn in at.button if btn.label in ["Submit", "Login", "Enter"]]
    if login_btns:
        login_btns[0].click().run(timeout=10)

    print("Inputting Address...")
    # Set the address in the first text input and run the app state
    at.text_input[0].set_value("123 Main St, Springfield, IL").run(timeout=10)

    print("Waiting for Gemini API...")
    print(f"Buttons found: {len(at.button)}")
    
    # Search for the button by its label
    analyze_btns = [btn for btn in at.button if btn.label == 'Analyze Property']
    
    if analyze_btns:
        # The analysis process involves multiple API calls and search grounding.
        # We increase the timeout significantly (e.g., 120 seconds) to allow the AI to finish.
        analyze_btns[0].click().run(timeout=120)
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
