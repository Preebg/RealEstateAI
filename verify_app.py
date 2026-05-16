from streamlit.testing.v1 import AppTest

def run_verification():
    print("Starting App...")
    # Initialize the AppTest with the main entry point
    at = AppTest.from_file("AIUnderwriterv2.py").run()

    print("Inputting Address...")
    # Set the address in the first text input and run the app state
    at.text_input[0].set_value("123 Main St, Springfield, IL").run()

    print("Waiting for Gemini API...")
    print(f"Buttons found: {len(at.button)}")
    
    # Search for the button by its label
    analyze_btns = at.get('button', label='Analyze Property')
    
    if analyze_btns:
        analyze_btns[0].click().run()
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
