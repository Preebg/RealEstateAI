import { apiFetch, type PortfolioItem } from './api'
import { supabase } from './supabase'

const DEFAULT_DOWN_PAYMENT_PCT = 25

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
  const monthlyCashFlow =
    asNumber(row.monthly_cash_flow) ?? asNumber(row.monthly_net_cash_flow)
  const forecastRate = asNumber(row.forecast_rate)
  const added = row.added_at ?? row.timestamp

  return {
    id: row.id != null ? String(row.id) : undefined,
    address: row.address != null ? String(row.address) : undefined,
    price,
    predicted_value: asNumber(row.predicted_value),
    latitude: asNumber(row.latitude),
    longitude: asNumber(row.longitude),
    sqft: asNumber(row.sqft) ?? asNumber(row.square_footage),
    location_score: asNumber(row.location_score),
    rent,
    year_built: yearBuilt,
    home_age: computeHomeAge(yearBuilt),
    monthly_cash_flow: monthlyCashFlow,
    rental_yield: computeRentalYield(rent, price),
    one_year_roi: computeOneYearRoi(price, monthlyCashFlow, forecastRate),
    market_city: row.market_city != null ? String(row.market_city) : undefined,
    state_code: row.state_code != null ? String(row.state_code) : undefined,
    quantum_success:
      asNumber(row.quantum_success) ?? asNumber(row.quantum_risk_score),
    strategy:
      (row.strategy as string | undefined) ||
      (row.strategy_tag as string | undefined) ||
      (row.property_label as string | undefined) ||
      (row.property_category as string | undefined),
    added_at: added != null ? String(added) : undefined,
  }
}

function sameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

/** Format a catalog timestamp in the viewer's local timezone (matches viewer_timezone.format_added_at). */
export function formatAddedAt(iso?: string, now = new Date()): string {
  if (!iso) return '—'
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return '—'

  const hour24 = dt.getHours()
  const hour = hour24 % 12 || 12
  const minute = String(dt.getMinutes()).padStart(2, '0')
  const timeStr = `${hour}:${minute} ${hour24 < 12 ? 'AM' : 'PM'}`
  if (sameLocalDay(dt, now)) return timeStr

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameLocalDay(dt, yesterday)) return `Yesterday, ${timeStr}`

  const month = dt.toLocaleString('en-US', { month: 'short' })
  if (dt.getFullYear() === now.getFullYear()) {
    return `${month} ${dt.getDate()}, ${timeStr}`
  }
  return `${month} ${dt.getDate()}, ${dt.getFullYear()}, ${timeStr}`
}

export function propertySearchPath(item: { address?: string; id?: string }): string {
  const params = new URLSearchParams()
  if (item.address) params.set('address', item.address)
  if (item.id) params.set('id', item.id)
  const qs = params.toString()
  return qs ? `/search?${qs}` : '/search'
}

const CATALOG_UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function isCatalogUuid(value: unknown): value is string {
  return typeof value === 'string' && CATALOG_UUID_RE.test(value.trim())
}

export function firstCatalogUuid(...values: unknown[]): string {
  for (const value of values) {
    if (isCatalogUuid(value)) return value.trim()
    if (value != null && typeof value !== 'string' && isCatalogUuid(String(value))) {
      return String(value).trim()
    }
  }
  return ''
}

/** Create a guest share row via FastAPI (local Postgres or hosted). */
export async function createPropertyShare(opts: {
  propertyId: string
  expiresDays?: number
}): Promise<{ share_token: string; share_url: string }> {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session?.user?.id) {
    throw new Error('Sign in to create a share link.')
  }

  const propertyId = firstCatalogUuid(opts.propertyId)
  if (!propertyId) {
    throw new Error('This property needs a catalog id before it can be shared.')
  }

  try {
    return await apiFetch<{ share_token: string; share_url: string }>('/api/shares', {
      method: 'POST',
      body: JSON.stringify({
        property_id: propertyId,
        include_assumptions: true,
        expires_days: opts.expiresDays ?? 30,
        base_url: window.location.origin,
      }),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to create share link'
    if (/foreign key|property_id/i.test(msg)) {
      throw new Error(
        'This listing is not in the catalog yet. Save it to your account, then try sharing again.',
      )
    }
    throw err instanceof Error ? err : new Error(msg)
  }
}

type GuestSharePayload = {
  valid?: boolean
  property?: Record<string, unknown> | null
  address?: string
  property_id?: string
  include_assumptions?: boolean
}

/** Load a guest share via FastAPI (harvest-machine Postgres). */
export async function fetchGuestShare(token: string): Promise<{
  valid: boolean
  address?: string
  property: Record<string, unknown> | null
  include_assumptions: boolean
}> {
  const trimmed = token.trim()
  if (!trimmed) return { valid: false, property: null, include_assumptions: false }

  try {
    const data = await apiFetch<GuestSharePayload>(
      `/api/guest/property?token=${encodeURIComponent(trimmed)}`,
    )
    const parsed = parseGuestSharePayload(data || {})
    if (parsed.valid) return parsed
  } catch {
    // Fall back to hosted Supabase RPCs for older share links.
  }

  const { data, error } = await supabase.rpc('get_guest_property', {
    p_share_token: trimmed,
  })
  if (error) {
    throw new Error(error.message || 'Failed to load shared property')
  }
  if (typeof data === 'string') {
    try {
      return parseGuestSharePayload(JSON.parse(data) as GuestSharePayload)
    } catch {
      return { valid: false, property: null, include_assumptions: false }
    }
  }
  return parseGuestSharePayload((data || {}) as GuestSharePayload)
}

function parseGuestSharePayload(payload: GuestSharePayload): {
  valid: boolean
  address?: string
  property: Record<string, unknown> | null
  include_assumptions: boolean
} {
  if (payload.valid !== true) {
    return { valid: false, property: null, include_assumptions: false }
  }

  const prop =
    payload.property && typeof payload.property === 'object' && !Array.isArray(payload.property)
      ? payload.property
      : null
  return {
    valid: true,
    address:
      prop?.address != null
        ? String(prop.address)
        : payload.address != null
          ? String(payload.address)
          : undefined,
    property: prop,
    include_assumptions: payload.include_assumptions !== false,
  }
}

/**
 * Load one catalog property for Individual Search from the harvest API.
 */
export async function fetchPropertyDetail(opts: {
  id?: string | null
  address?: string | null
}): Promise<Record<string, unknown> | null> {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session) {
    throw new Error('Sign in to load the property.')
  }

  const id = opts.id?.trim()
  const address = opts.address?.trim()
  if (!id && !address) return null

  const params = new URLSearchParams()
  if (id) params.set('id', id)
  if (address) params.set('address', address)

  try {
    const row = await apiFetch<Record<string, unknown>>(
      `/api/properties/detail?${params.toString()}`,
    )
    if (!row) return null
    const rent = resolveRent(row)
    return {
      ...row,
      from_kb: true,
      property_id: row.id,
      rent: rent ?? row.rent,
      sqft: row.square_footage ?? row.sqft,
      strategy:
        row.strategy_tag || row.property_label || row.property_category || row.strategy,
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : ''
    if (/not found/i.test(msg)) return null
    throw err
  }
}

/**
 * Load the portfolio map from FastAPI (harvest-machine Postgres).
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

  const data = await apiFetch<{
    properties?: Array<Record<string, unknown>>
    count?: number
  }>('/api/portfolio')
  const properties = (data.properties ?? []).map(rowToItem)
  return { properties, count: data.count ?? properties.length }
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
