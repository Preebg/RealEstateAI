from typing import TypedDict


class AppreciationForecast(TypedDict):
    future_value: float
    annual_rate: float
    total_growth: float


class OperatingExpenseBreakdown(TypedDict):
    total: float
    monthly_taxes: float
    monthly_maintenance: float
    vacancy_reserve: float
    management_fee: float


class InvestmentAnalysis(TypedDict):
    monthly_mortgage: float
    closing_costs_total: float
    operating_expenses: OperatingExpenseBreakdown
    total_monthly_expenses: float
    monthly_net_cash_flow: float
    annual_noi: float
    total_investment: float
    cap_rate: float
    cash_on_cash: float


def calculate_10yr_appreciation(
    current_value: float, location_score: float
) -> AppreciationForecast:
    """Calculates projected property value over 10 years based on location score."""
    if current_value <= 0:
        return {"future_value": 0.0, "annual_rate": 0.0, "total_growth": 0.0}

    annual_rate = 0.03 + ((location_score - 5.0) * 0.005)
    future_value = current_value * ((1.0 + annual_rate) ** 10)
    total_growth = ((future_value - current_value) / current_value) * 100.0

    return {
        "future_value": future_value,
        "annual_rate": annual_rate * 100.0,
        "total_growth": total_growth,
    }


def calculate_mortgage(
    price: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term: int,
) -> float:
    """Calculates monthly mortgage payment (Principal & Interest)."""
    loan_amount = price * (1.0 - (down_payment_pct / 100.0))
    monthly_ir = (interest_rate / 100.0) / 12.0
    total_payments = loan_term * 12

    if monthly_ir > 0:
        payment = loan_amount * (monthly_ir * (1.0 + monthly_ir) ** total_payments) / (
            (1.0 + monthly_ir) ** total_payments - 1.0
        )
    else:
        payment = loan_amount / total_payments

    return payment


def calculate_operating_expenses(
    price: float,
    tax_rate: float,
    monthly_insurance: float,
    monthly_hoa: float,
    maint_percent: float,
    monthly_rent: float,
    vacancy_reserve_pct: float,
    management_fee_pct: float,
) -> OperatingExpenseBreakdown:
    """Calculates detailed monthly operating expenses."""
    monthly_taxes = ((tax_rate / 100.0) * price) / 12.0
    monthly_maint = (maint_percent / 100.0) * monthly_rent
    vacancy_reserve = (vacancy_reserve_pct / 100.0) * monthly_rent
    management_fee = (management_fee_pct / 100.0) * monthly_rent

    total_expenses = (
        monthly_taxes
        + monthly_insurance
        + monthly_hoa
        + monthly_maint
        + vacancy_reserve
        + management_fee
    )

    return {
        "total": total_expenses,
        "monthly_taxes": monthly_taxes,
        "monthly_maintenance": monthly_maint,
        "vacancy_reserve": vacancy_reserve,
        "management_fee": management_fee,
    }


def calculate_closing_costs(price: float, closing_costs_pct: float) -> float:
    """Calculates total closing costs from purchase price and percentage."""
    return price * (closing_costs_pct / 100.0)


def calculate_total_investment(
    price: float, down_payment_pct: float, closing_costs_total: float
) -> float:
    """Calculates total cash required (down payment plus closing costs)."""
    return (price * (down_payment_pct / 100.0)) + closing_costs_total


def calculate_annual_noi(monthly_rent: float, operating_expenses: float) -> float:
    """Calculates annual net operating income (rent minus operating expenses)."""
    return (monthly_rent - operating_expenses) * 12.0


def calculate_monthly_net_cash_flow(
    monthly_rent: float, monthly_mortgage: float, operating_expenses: float
) -> tuple[float, float]:
    """Returns (total monthly expenses, net monthly cash flow)."""
    total_monthly_expenses = monthly_mortgage + operating_expenses
    monthly_net_cash_flow = monthly_rent - total_monthly_expenses
    return total_monthly_expenses, monthly_net_cash_flow


def calculate_investment_metrics(
    price: float,
    annual_noi: float,
    total_investment: float,
    monthly_net_cash_flow: float,
) -> tuple[float, float]:
    """Calculates Cap Rate and Cash on Cash return."""
    cap_rate = (annual_noi / price) * 100.0 if price > 0 else 0.0
    cash_on_cash = (
        (monthly_net_cash_flow * 12.0 / total_investment) * 100.0
        if total_investment > 0
        else 0.0
    )
    return cap_rate, cash_on_cash


def project_value_schedule(
    base_value: float, annual_rate_pct: float, num_years: int = 11
) -> list[float]:
    """Projects property value for each year using compound growth."""
    rate = annual_rate_pct / 100.0
    return [base_value * ((1.0 + rate) ** year) for year in range(num_years)]


def analyze_investment(
    price: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term: int,
    closing_costs_pct: float,
    tax_rate: float,
    monthly_insurance: float,
    monthly_hoa: float,
    maint_percent: float,
    monthly_rent: float,
    vacancy_reserve_pct: float,
    management_fee_pct: float,
) -> InvestmentAnalysis:
    """Runs full investment math: mortgage, expenses, cash flow, and return metrics."""
    monthly_mortgage = calculate_mortgage(
        price, down_payment_pct, interest_rate, loan_term
    )
    closing_costs_total = calculate_closing_costs(price, closing_costs_pct)
    op_ex = calculate_operating_expenses(
        price,
        tax_rate,
        monthly_insurance,
        monthly_hoa,
        maint_percent,
        monthly_rent,
        vacancy_reserve_pct,
        management_fee_pct,
    )
    total_monthly_expenses, monthly_net_cash_flow = calculate_monthly_net_cash_flow(
        monthly_rent, monthly_mortgage, op_ex["total"]
    )
    annual_noi = calculate_annual_noi(monthly_rent, op_ex["total"])
    total_investment = calculate_total_investment(
        price, down_payment_pct, closing_costs_total
    )
    cap_rate, cash_on_cash = calculate_investment_metrics(
        price, annual_noi, total_investment, monthly_net_cash_flow
    )

    return {
        "monthly_mortgage": monthly_mortgage,
        "closing_costs_total": closing_costs_total,
        "operating_expenses": op_ex,
        "total_monthly_expenses": total_monthly_expenses,
        "monthly_net_cash_flow": monthly_net_cash_flow,
        "annual_noi": annual_noi,
        "total_investment": total_investment,
        "cap_rate": cap_rate,
        "cash_on_cash": cash_on_cash,
    }
