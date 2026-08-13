import { supabase } from './supabase'
import type { PortfolioItem } from './api'

/** Matches knowledge_base.ACTIVE_PROPERTY_ARCHIVE_DAYS */
const ARCHIVE_DAYS = 30
const PAGE_SIZE = 500
const DEFAULT_DOWN_PAYMENT_PCT = 25

const LIST_SELECT = [
  'id',
  'address',
  'price',
  'predicted_value',
  'latitude',
  'longitude',
  'square_footage',
  'location_score',
  'rent',
  'original_ai_rent',
  'year_built',
  'monthly_net_cash_flow',
  'market_city',
  'state_code',
  'forecast_rate',
  'quantum_risk_score',
  'strategy_tag',
  'property_label',
  'property_category',
].join(',')

function activeCutoffIso(): string {
  const cutoff = new Date()
  cutoff.setUTCDate(cutoff.getUTCDate() - ARCHIVE_DAYS)
  return cutoff.toISOString()
}

function asNumber(value: unknown): number | undefined {
  if (value == null || value === '') return undefined
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : undefined
}

/** Prefer saved rent; fall back to AI baseline (most KB rows only have original_ai_rent). */
function resolveRent(row: Record<string, unknown>): number | undefined {
  const rent = asNumber(row.rent)
  if (rent != null && rent > 0) return rent
  const aiRent = asNumber(row.original_ai_rent)
  if (aiRent != null && aiRent > 0) return aiRent
  return undefined
}

function resolvePrice(row: Record<string, unknown>): number | undefined {
  const price = asNumber(row.price)
  if (price != null && price > 0) return price
  return asNumber(row.predicted_value)
}

function computeHomeAge(yearBuilt: number | undefined): number | undefined {
  if (yearBuilt == null || yearBuilt < 1800) return undefined
  return Math.max(new Date().getFullYear() - yearBuilt, 0)
}

/** Gross rental yield: annual rent / price. */
function computeRentalYield(rent: number | undefined, price: number | undefined): number | undefined {
  if (rent == null || rent <= 0 || price == null || price <= 0) return undefined
  return (rent * 12 * 100) / price
}

/**
 * One-year ROI aligned with finance.calculate_one_year_roi defaults
 * (25% down, stored cash flow + forecast appreciation).
 */
function computeOneYearRoi(
  price: number | undefined,
  monthlyCashFlow: number | undefined,
  forecastRate: number | undefined,
): number | undefined {
  if (price == null || price <= 0) return undefined
  const downPayment = price * (DEFAULT_DOWN_PAYMENT_PCT / 100)
  if (downPayment <= 0) return undefined
  const rate = forecastRate != null && forecastRate > 0 ? forecastRate : 0
  const appreciationGain = price * (rate / 100)
  const annualCashFlow = (monthlyCashFlow ?? 0) * 12
  return ((appreciationGain + annualCashFlow) / downPayment) * 100
}

function rowToItem(row: Record<string, unknown>): PortfolioItem {
  const price = resolvePrice(row)
  const rent = resolveRent(row)
  const yearBuilt = asNumber(row.year_built)
  const monthlyCashFlow = asNumber(row.monthly_net_cash_flow)
  const forecastRate = asNumber(row.forecast_rate)

  return {
    id: row.id != null ? String(row.id) : undefined,
    address: row.address != null ? String(row.address) : undefined,
    price,
    predicted_value: asNumber(row.predicted_value),
    latitude: asNumber(row.latitude),
    longitude: asNumber(row.longitude),
    sqft: asNumber(row.square_footage),
    location_score: asNumber(row.location_score),
    rent,
    year_built: yearBuilt,
    home_age: computeHomeAge(yearBuilt),
    monthly_cash_flow: monthlyCashFlow,
    rental_yield: computeRentalYield(rent, price),
    one_year_roi: computeOneYearRoi(price, monthlyCashFlow, forecastRate),
    market_city: row.market_city != null ? String(row.market_city) : undefined,
    state_code: row.state_code != null ? String(row.state_code) : undefined,
    quantum_success: asNumber(row.quantum_risk_score),
    strategy:
      (row.strategy_tag as string | undefined) ||
      (row.property_label as string | undefined) ||
      (row.property_category as string | undefined),
  }
}

/**
 * Load the portfolio map from Supabase (no FastAPI required).
 * Works on Netlify when only the SPA + Supabase are configured.
 */
export async function fetchPortfolio(): Promise<{
  properties: PortfolioItem[]
  count: number
}> {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session) {
    throw new Error('Sign in to load the portfolio.')
  }

  const cutoff = activeCutoffIso()
  const properties: PortfolioItem[] = []
  let offset = 0

  for (;;) {
    const { data, error } = await supabase
      .from('properties')
      .select(LIST_SELECT)
      .gte('timestamp', cutoff)
      .order('timestamp', { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1)

    if (error) {
      throw new Error(error.message || 'Failed to load portfolio from Supabase')
    }

    const batch = (data as unknown as Array<Record<string, unknown>> | null) ?? []
    for (const row of batch) {
      properties.push(rowToItem(row))
    }
    if (batch.length < PAGE_SIZE) break
    offset += PAGE_SIZE
  }

  return { properties, count: properties.length }
}

export type RangeBounds = { min: number; max: number }

export function numericBounds(
  values: Array<number | undefined>,
  fallback: RangeBounds,
): RangeBounds {
  const nums = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (nums.length === 0) return fallback
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  if (max <= min) return { min, max: min + 1 }
  return { min, max }
}

export function rangeActive(
  selected: RangeBounds,
  bounds: RangeBounds,
  epsilon = 1e-9,
): boolean {
  return selected.min > bounds.min + epsilon || selected.max < bounds.max - epsilon
}
