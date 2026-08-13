import { supabase } from './supabase'
import type { PortfolioItem } from './api'

/** Matches knowledge_base.ACTIVE_PROPERTY_ARCHIVE_DAYS */
const ARCHIVE_DAYS = 30
const PAGE_SIZE = 500

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

function rowToItem(row: Record<string, unknown>): PortfolioItem {
  return {
    id: row.id != null ? String(row.id) : undefined,
    address: row.address != null ? String(row.address) : undefined,
    price: asNumber(row.price),
    predicted_value: asNumber(row.predicted_value),
    latitude: asNumber(row.latitude),
    longitude: asNumber(row.longitude),
    sqft: asNumber(row.square_footage),
    location_score: asNumber(row.location_score),
    rent: asNumber(row.rent),
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
