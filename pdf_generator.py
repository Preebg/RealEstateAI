from fpdf import FPDF
import datetime

def generate_property_pdf(address, property_info, metrics, table_data, params, location_score):
    pdf = FPDF()
    pdf.add_page()
    
    # Header & Address
    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 10, "Property Analysis Report", ln=True, align='C')
    pdf.set_font("Times", "", 12)
    pdf.cell(0, 10, f"Address: {address}", ln=True, align='C')
    pdf.ln(5)

    #Investment Parameters
    pdf.set_font("Times", "B", 11)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 8, "Investment Parameters", ln=True, fill=True)
    pdf.set_font("Times", "", 10)
    
    # Display params side-by-side or in a list
    param_text = f"Down Payment: {params['Down Payment']}  |  Interest Rate: {params['Interest Rate']}  |  Loan Term: {params['Loan Term']}"
    pdf.cell(0, 8, param_text, ln=True)
    pdf.ln(5)

    # Summary Section
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 10, "Property Summary:", ln=True)
    pdf.set_font("Times", "", 10)
    pdf.multi_cell(0, 5, property_info.get("summary", "No summary available."))
    pdf.ln(5)

    # Detailed Breakdown Table 
    pdf.set_font("Times", "B", 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 10, "Description", border=1, fill=True)
    pdf.cell(45, 10, "Monthly Amount", border=1, ln=True, fill=True)
    
    pdf.set_font("Times", "", 11)

    for i in range(len(table_data["Description"])):
        pdf.cell(95, 10, table_data["Description"][i], border=1)
        pdf.cell(45, 10, table_data["Amount"][i], border=1, ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Proprietary Location Score: {location_score}/10", ln=True)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 5, "This score represents a weighted analysis of local appreciation trends, "
                         "school ratings, and quantum-simulated market volatility.")
    pdf.ln(5)

    # Final Investment Metrics
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 10, "Final Projections:", ln=True)
    pdf.set_font("Times", "", 11)
    for label, value in metrics.items():
        pdf.cell(0, 8, f"{label}: {value}", ln=True)

    return bytes(pdf.output())