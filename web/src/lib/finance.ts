/** Client-side underwriting math aligned with finance.py. */

export type FinanceAssumptions = {
  price: number
  down_payment_pct: number
  interest_rate: number
  loan_term: number
  closing_costs_pct: number
  tax_rate: number
  monthly_insurance: number
  monthly_hoa: number
  maint_percent: number
  monthly_rent: number
  vacancy_reserve_pct: number
  management_fee_pct: number
}

export type FinanceMetrics = {
  monthly_mortgage: number
  user_closing_costs_total: number
  monthly_taxes: number
  monthly_insurance: number
  monthly_hoa: number
  calculated_monthly_maint: number
  actual_vacancy_reserve: number
  actual_management_fee: number
  total_monthly_expenses: number
  monthly_net_cash_flow: number
  total_investment: number
  cap_rate: number
  cash_on_cash: number
}

const MONTHLY_INSURANCE_ANNUAL_THRESHOLD = 400
const PERCENT_FEE_MIN = 1
const PERCENT_FEE_MAX = 20

export function roundMoney(n: number): number {
  return Math.round(n * 100) / 100
}

export function normalizeMonthlyInsurance(value: number): number {
  if (value > MONTHLY_INSURANCE_ANNUAL_THRESHOLD) {
    return roundMoney(value / 12)
  }
  return value
}

export function normalizePercentRate(
  value: number,
  minPct = PERCENT_FEE_MIN,
  maxPct = PERCENT_FEE_MAX,
): number {
  if (value <= 0) return value
  if (value >= 1) return Number(value.toFixed(4))
  const scaled = value * 100
  if (scaled >= minPct && scaled <= maxPct) return Number(scaled.toFixed(4))
  return Number(value.toFixed(4))
}

export function normalizeTaxRatePercent(value: number): number {
  return normalizePercentRate(value, 0.3, 12)
}

function calculateMortgage(
  price: number,
  downPaymentPct: number,
  interestRate: number,
  loanTerm: number,
): number {
  const loanAmount = price * (1 - downPaymentPct / 100)
  const monthlyIr = interestRate / 100 / 12
  const totalPayments = loanTerm * 12
  if (monthlyIr > 0) {
    const factor = (1 + monthlyIr) ** totalPayments
    return (loanAmount * (monthlyIr * factor)) / (factor - 1)
  }
  return totalPayments > 0 ? loanAmount / totalPayments : 0
}

export function analyzeInvestment(input: FinanceAssumptions): FinanceMetrics {
  const monthlyMortgage = calculateMortgage(
    input.price,
    input.down_payment_pct,
    input.interest_rate,
    input.loan_term,
  )
  const closingCosts = input.price * (input.closing_costs_pct / 100)
  const monthlyTaxes = ((input.tax_rate / 100) * input.price) / 12
  const monthlyMaint = (input.maint_percent / 100) * input.monthly_rent
  const vacancyReserve = (input.vacancy_reserve_pct / 100) * input.monthly_rent
  const managementFee = (input.management_fee_pct / 100) * input.monthly_rent
  const operatingTotal =
    monthlyTaxes +
    input.monthly_insurance +
    input.monthly_hoa +
    monthlyMaint +
    vacancyReserve +
    managementFee
  const totalMonthlyExpenses = monthlyMortgage + operatingTotal
  const monthlyNetCashFlow = input.monthly_rent - totalMonthlyExpenses
  const annualNoi = (input.monthly_rent - operatingTotal) * 12
  const totalInvestment = input.price * (input.down_payment_pct / 100) + closingCosts
  const capRate = input.price > 0 ? (annualNoi / input.price) * 100 : 0
  const cashOnCash =
    totalInvestment > 0 ? ((monthlyNetCashFlow * 12) / totalInvestment) * 100 : 0

  return {
    monthly_mortgage: roundMoney(monthlyMortgage),
    user_closing_costs_total: roundMoney(closingCosts),
    monthly_taxes: roundMoney(monthlyTaxes),
    monthly_insurance: roundMoney(input.monthly_insurance),
    monthly_hoa: roundMoney(input.monthly_hoa),
    calculated_monthly_maint: roundMoney(monthlyMaint),
    actual_vacancy_reserve: roundMoney(vacancyReserve),
    actual_management_fee: roundMoney(managementFee),
    total_monthly_expenses: roundMoney(totalMonthlyExpenses),
    monthly_net_cash_flow: roundMoney(monthlyNetCashFlow),
    total_investment: roundMoney(totalInvestment),
    cap_rate: capRate,
    cash_on_cash: cashOnCash,
  }
}

export function flattenFinanceNumbers(
  source: Record<string, unknown>,
): Record<string, number> {
  const flat: Record<string, number> = {}
  const walk = (obj: Record<string, unknown>) => {
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        flat[key] = value
      } else if (value && typeof value === 'object' && !Array.isArray(value)) {
        walk(value as Record<string, unknown>)
      }
    }
  }
  walk(source)
  return flat
}
