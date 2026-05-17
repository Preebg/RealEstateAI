#include <cmath>

extern "C" {
    // 10-Year Appreciation
    void calculate_10yr_appreciation(double current_value, double location_score, double* future_value, double* annual_rate, double* total_growth) {
        if (current_value <= 0) {
            *future_value = 0; *annual_rate = 0; *total_growth = 0;
            return;
        }
        double rate = 0.03 + ((location_score - 5.0) * 0.005);
        double f_val = current_value * std::pow((1.0 + rate), 10.0);
        *future_value = f_val;
        *annual_rate = rate * 100.0;
        *total_growth = ((f_val - current_value) / current_value) * 100.0;
    }

    // Mortgage Calculation
    double calculate_mortgage(double price, double down_payment_pct, double interest_rate, int loan_term) {
        double loan_amount = price * (1.0 - (down_payment_pct / 100.0));
        double monthly_ir = (interest_rate / 100.0) / 12.0;
        int total_payments = loan_term * 12;
        if (monthly_ir > 0) {
            return loan_amount * (monthly_ir * std::pow((1.0 + monthly_ir), total_payments)) / (std::pow((1.0 + monthly_ir), total_payments) - 1.0);
        }
        return loan_amount / total_payments;
    }

    // Operating Expenses
    void calculate_operating_expenses(double price, double tax_rate, double monthly_insurance, double monthly_hoa, 
                                     double maint_percent, double monthly_rent, double vacancy_reserve_pct, 
                                     double management_fee_pct, double* total_expenses, double* monthly_taxes, 
                                     double* monthly_maint, double* vacancy_reserve, double* management_fee) {
        double taxes = ((tax_rate / 100.0) * price) / 12.0;
        double maint = (maint_percent / 100.0) * monthly_rent;
        double vac = (vacancy_reserve_pct / 100.0) * monthly_rent;
        double mgmt = (management_fee_pct / 100.0) * monthly_rent;
        
        *monthly_taxes = taxes;
        *monthly_maint = maint;
        *vacancy_reserve = vac;
        *management_fee = mgmt;
        *total_expenses = taxes + monthly_insurance + monthly_hoa + maint + vac + mgmt;
    }

    // Investment Metrics
    void calculate_investment_metrics(double price, double annual_noi, double total_investment, 
                                     double monthly_net_cash_flow, double* cap_rate, double* cash_on_cash) {
        *cap_rate = (price > 0) ? (annual_noi / price) * 100.0 : 0;
        *cash_on_cash = (total_investment > 0) ? (monthly_net_cash_flow * 12.0 / total_investment) * 100.0 : 0;
    }
}
