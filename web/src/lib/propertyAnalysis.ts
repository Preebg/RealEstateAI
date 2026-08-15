import {
  analyzeInvestment,
  calculateOneYearRoi,
  normalizeMonthlyInsurance,
  normalizePercentRate,
  normalizeTaxRatePercent,
  type FinanceMetrics,
} from './finance'
import type { PortfolioItem } from './api'
import { buildPropertyPdfBlob, pdfDownloadFilename } from './propertyPdf'

export type Assumptions = {
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

export const ASSUMPTION_SLIDERS = [
  ['monthly_rent', 'Monthly rent', 0, 20000, 50],
  ['down_payment_pct', 'Down payment %', 0, 100, 1],
  ['interest_rate', 'Interest rate %', 0, 20, 0.1],
  ['loan_term', 'Loan term (yrs)', 5, 40, 1],
  ['closing_costs_pct', 'Closing costs %', 0, 10, 0.1],
  ['tax_rate', 'Tax rate %', 0, 5, 0.05],
  ['monthly_insurance', 'Insurance / mo', 0, 2000, 10],
  ['monthly_hoa', 'HOA / mo', 0, 2000, 10],
  ['maint_percent', 'Maint %', 0, 10, 0.1],
  ['vacancy_reserve_pct', 'Vacancy %', 0, 30, 0.5],
  ['management_fee_pct', 'Mgmt fee %', 0, 20, 0.5],
] as const

export function num(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function money(n: number): string {
  return `$${Math.round(n).toLocaleString()}`
}

export function moneyExact(n: number): string {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return n < 0 ? `-$${abs}` : `$${abs}`
}

export function parseYearBuilt(raw: Record<string, unknown>): number | undefined {
  for (const key of ['year_built', 'year'] as const) {
    const n = Number(raw[key])
    if (Number.isFinite(n) && n >= 1800) return Math.round(n)
  }
  return undefined
}

export function formatYearBuilt(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 1800) return '—'
  return String(Math.round(n))
}

export function hydrateProperty(raw: Record<string, unknown>): Record<string, unknown> {
  const rent = num(raw.rent ?? raw.estimated_rent ?? raw.original_ai_rent, 0)
  const score = num(raw.quantum_risk_score)
  const quantum =
    raw.quantum_risk && typeof raw.quantum_risk === 'object'
      ? raw.quantum_risk
      : score > 0
        ? {
            overall_success_pct: score,
            cashflow_success_pct: score,
            appreciation_success_pct: score,
            combined_wealth_success_pct: score,
          }
        : raw.quantum_risk

  return {
    ...raw,
    from_kb: raw.from_kb ?? true,
    property_id: raw.property_id ?? raw.id,
    rent: rent > 0 ? rent : raw.rent,
    sqft: raw.square_footage ?? raw.sqft,
    year_built: parseYearBuilt(raw),
    strategy:
      raw.strategy || raw.strategy_tag || raw.property_label || raw.property_category,
    quantum_risk: quantum,
  }
}

export function assumptionsFromProperty(property: Record<string, unknown>): Assumptions {
  return {
    down_payment_pct: 25,
    interest_rate: 6,
    loan_term: 30,
    closing_costs_pct: 3,
    tax_rate: normalizeTaxRatePercent(num(property.tax_rate, 1.2)),
    monthly_insurance: normalizeMonthlyInsurance(num(property.insurance, 150)),
    monthly_hoa: num(property.hoa, 0),
    maint_percent: num(property.maint_percent ?? property.original_ai_maint, 1),
    monthly_rent: num(
      property.rent ?? property.estimated_rent ?? property.original_ai_rent,
      0,
    ),
    vacancy_reserve_pct: normalizePercentRate(
      num(
        property.user_vacancy_rate ?? property.vacancy_rate ?? property.ai_vacancy_rate,
        5,
      ),
    ),
    management_fee_pct: normalizePercentRate(
      num(
        property.user_management_fee ??
          property.management_fee ??
          property.ai_management_fee,
        8,
      ),
    ),
  }
}

export function financeFromProperty(
  property: Record<string, unknown>,
  assumptions: Assumptions,
): FinanceMetrics {
  return analyzeInvestment({
    ...assumptions,
    price: num(property.price ?? property.predicted_value),
  })
}

export function quantumPayload(value: unknown): Record<string, number> | undefined {
  if (!value || typeof value !== 'object') return undefined
  const q = value as Record<string, unknown>
  const keys = [
    'cashflow_success_pct',
    'appreciation_success_pct',
    'combined_wealth_success_pct',
    'overall_success_pct',
  ] as const
  const out: Record<string, number> = {}
  for (const k of keys) {
    const n = Number(q[k])
    if (!Number.isFinite(n)) return undefined
    out[k] = n
  }
  return out
}

export function cashFlowRows(assumptions: Assumptions, finance: FinanceMetrics) {
  return [
    ['Gross monthly rent', moneyExact(assumptions.monthly_rent), false],
    ['Mortgage payment (P&I)', moneyExact(-finance.monthly_mortgage), false],
    ['Property taxes', moneyExact(-finance.monthly_taxes), false],
    ['Insurance', moneyExact(-finance.monthly_insurance), false],
    ['HOA fee', moneyExact(-finance.monthly_hoa), false],
    ['Maintenance (CapEx)', moneyExact(-finance.calculated_monthly_maint), false],
    ['Vacancy reserve', moneyExact(-finance.actual_vacancy_reserve), false],
    ['Management fee', moneyExact(-finance.actual_management_fee), false],
    ['Total costs', moneyExact(-finance.total_monthly_expenses), true],
    ['Cash flow monthly', moneyExact(finance.monthly_net_cash_flow), true],
  ] as const
}

export function forecastYearlyValues(property: Record<string, unknown>): number[] {
  const cache = property._forecast_display_cache as
    | { yearly_values?: unknown[]; value_schedule_p50?: unknown[] }
    | undefined
  const fromCache = cache?.yearly_values || cache?.value_schedule_p50
  if (Array.isArray(fromCache) && fromCache.length > 1) {
    return fromCache.map((v) => Number(v)).filter((v) => Number.isFinite(v))
  }

  const price = num(property.price ?? property.predicted_value)
  const hasRate = property.forecast_rate != null || property.forecast_growth != null
  if (price <= 0 || !hasRate) return []
  const rate = num(property.forecast_rate ?? property.forecast_growth)
  return Array.from({ length: 11 }, (_, i) => price * (1 + rate / 100) ** i)
}

export type ComparisonRow = {
  address: string
  property_id: string
  price: number | null
  monthly_rent: number | null
  monthly_net_cash_flow: number | null
  cap_rate: number | null
  cash_on_cash: number | null
  one_year_roi: number | null
  location_score: number | null
  quantum_overall: number | null
  strategy: string
}

function finiteOrNull(value: number): number | null {
  return Number.isFinite(value) ? value : null
}

export function comparisonRowFromProperty(property: Record<string, unknown>): ComparisonRow {
  const hydrated = hydrateProperty(property)
  const assumptions = assumptionsFromProperty(hydrated)
  const finance = financeFromProperty(hydrated, assumptions)
  const price = num(hydrated.price ?? hydrated.predicted_value)
  const forecastRate = num(hydrated.forecast_rate)
  const roi = calculateOneYearRoi({
    currentPrice: price,
    forecastRatePct: forecastRate,
    monthlyNetCashFlow: finance.monthly_net_cash_flow,
    downPaymentPct: assumptions.down_payment_pct,
  })
  const quantum = quantumPayload(hydrated.quantum_risk)
  let quantumOverall: number | null = quantum?.overall_success_pct ?? null
  if (quantumOverall == null && hydrated.quantum_risk_score != null) {
    quantumOverall = finiteOrNull(num(hydrated.quantum_risk_score))
  }
  const strategy =
    hydrated.strategy != null && String(hydrated.strategy).trim()
      ? String(hydrated.strategy)
      : '—'
  return {
    address: String(hydrated.address || 'Unknown'),
    property_id: String(hydrated.property_id || hydrated.id || ''),
    price: price > 0 ? price : null,
    monthly_rent: assumptions.monthly_rent > 0 ? assumptions.monthly_rent : null,
    monthly_net_cash_flow: finiteOrNull(finance.monthly_net_cash_flow),
    cap_rate: finiteOrNull(finance.cap_rate),
    cash_on_cash: finiteOrNull(finance.cash_on_cash),
    one_year_roi: finiteOrNull(roi),
    location_score:
      hydrated.location_score != null ? finiteOrNull(num(hydrated.location_score)) : null,
    quantum_overall: quantumOverall,
    strategy,
  }
}

export function comparisonRowFromPortfolioItem(item: PortfolioItem): ComparisonRow {
  return {
    address: item.address || 'Unknown',
    property_id: item.id || '',
    price: item.price ?? item.predicted_value ?? null,
    monthly_rent: item.rent ?? null,
    monthly_net_cash_flow: item.monthly_cash_flow ?? null,
    cap_rate: null,
    cash_on_cash: null,
    one_year_roi: item.one_year_roi ?? null,
    location_score: item.location_score ?? null,
    quantum_overall: item.quantum_success ?? null,
    strategy: item.strategy || '—',
  }
}

export function downloadPropertyPdf(opts: {
  property: Record<string, unknown>
  assumptions: Assumptions
  finance: FinanceMetrics
  address: string
}): void {
  const { property, assumptions, finance, address } = opts
  const rows = cashFlowRows(assumptions, finance)
  const price = num(property.price ?? property.predicted_value)
  const blob = buildPropertyPdfBlob({
    address,
    summary: typeof property.summary === 'string' ? property.summary : undefined,
    locationScore: num(property.location_score, 5),
    strategy: property.strategy != null ? String(property.strategy) : undefined,
    yearBuilt: parseYearBuilt(property),
    price,
    assumptions,
    finance,
    breakdown: rows.map(([label, amount, emphasize], i) => ({
      label,
      amount,
      emphasize,
      value:
        [
          assumptions.monthly_rent,
          -finance.monthly_mortgage,
          -finance.monthly_taxes,
          -finance.monthly_insurance,
          -finance.monthly_hoa,
          -finance.calculated_monthly_maint,
          -finance.actual_vacancy_reserve,
          -finance.actual_management_fee,
          -finance.total_monthly_expenses,
          finance.monthly_net_cash_flow,
        ][i] ?? 0,
    })),
    quantum: quantumPayload(property.quantum_risk),
    forecastValues: forecastYearlyValues(property),
  })
  if (!(blob instanceof Blob) || blob.size < 8) {
    throw new Error('PDF download returned an empty file.')
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = pdfDownloadFilename(address)
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
