import google.genai as genai


client = genai.Client(api_key=API_KEY)

price = 400000
monthly_rent=2500
year_built= 1970
listing_description = "Charming mid-century home. original windows and HVAC. Roof was repalced 15 years ago. Needs soem TLC in the kitchen."

def get_maintenance_estimate(description, age):
    prompt= f"""Analyze this house built in {age}.
    Description: {description}
    Give me a suggested annual maintenance budget as a percentage of the price. Standard is 1%, but if it's old/original suggest higher.
    Return ONLY the number (e.g. 1.5).
    """ 
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return float(response.text.strip())

maint_percent= get_maintenance_estimate(listing_description, year_built)
annual_maint_cost = (maint_percent/100)*price

annual_income=monthly_rent*12
noi=annual_income - annual_maint_cost
cap_rate = (noi/price)*100

print(f"AI Suggested Maint: {maint_percent}% (${annual_maint_cost}/year)") 
print(f"Risk-Adjusted Cap Rate: {cap_rate:.2f}%") 




