def calculate_10yr_appreciation(current_value, location_score):
    """Calculates projected property value over 10 years based on location score."""
    if current_value <= 0:
        return {"future_value": 0.0, "annual_rate": 0.0, "total_growth": 0.0}
    
    # Base rate 3% + 0.5% for every point above 5
    annual_rate = 0.03 + ((location_score - 5.0) * 0.005)
    future_value = current_value * ((1.0 + annual_rate) ** 10)
    total_growth = ((future_value - current_value) / current_value) * 100.0
    
    return {
        "future_value": future_value,
        "annual_rate": annual_rate * 100.0,
        "total_growth": total_growth
    }

def calculate_mortgage(price, down_payment_pct, interest_rate, loan_term):
    """Calculates monthly mortgage payment (Principal & Interest)."""
    loan_amount = price * (1.0 - (down_payment_pct / 100.0))
    monthly_ir = (interest_rate / 100.0) / 12.0
    total_payments = loan_term * 12
    
    if monthly_ir > 0:
        payment = loan_amount * (monthly_ir * (1.0 + monthly_ir)**total_payments) / ((1.0 + monthly_ir)**total_payments - 1.0)
    else:
        payment = loan_amount / total_payments
        
    return payment

def calculate_operating_expenses(price, tax_rate, monthly_insurance, monthly_hoa, maint_percent, monthly_rent, vacancy_reserve_pct, management_fee_pct):
    """Calculates detailed monthly operating expenses."""
    monthly_taxes = ((tax_rate / 100.0) * price) / 12.0
    monthly_maint = (maint_percent / 100.0) * monthly_rent
    vacancy_reserve = (vacancy_reserve_pct / 100.0) * monthly_rent
    management_fee = (management_fee_pct / 100.0) * monthly_rent
    
    total_expenses = monthly_taxes + monthly_insurance + monthly_hoa + monthly_maint + vacancy_reserve + management_fee
    
    return total_expenses, monthly_taxes, monthly_maint, vacancy_reserve, management_fee

def calculate_investment_metrics(price, annual_noi, total_investment, monthly_net_cash_flow):
    """Calculates Cap Rate and Cash on Cash return."""
    cap_rate = (annual_noi / price) * 100.0 if price > 0 else 0.0
    cash_on_cash = (monthly_net_cash_flow * 12.0 / total_investment) * 100.0 if total_investment > 0 else 0.0
    
    return cap_rate, cash_on_cash
