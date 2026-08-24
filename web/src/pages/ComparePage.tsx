import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import type { PortfolioItem } from '../lib/api'
import { fetchPortfolio, fetchPropertyDetail, propertySearchPath } from '../lib/portfolio'
import {
  comparisonRowFromPortfolioItem,
  comparisonRowFromProperty,
  type ComparisonRow,
} from '../lib/propertyAnalysis'
import { trackPreviewEvent } from '../lib/previewActivity'

const MAX_SELECTED = 4

const METRIC_ROWS: Array<{
  key: keyof ComparisonRow
  label: string
  kind: 'currency' | 'percent' | 'score' | 'text'
  higherIsBetter: boolean | null
}> = [
  { key: 'address', label: 'Address', kind: 'text', higherIsBetter: null },
  { key: 'price', label: 'List Price', kind: 'currency', higherIsBetter: false },
  { key: 'monthly_rent', label: 'Monthly Rent', kind: 'currency', higherIsBetter: true },
  { key: 'monthly_net_cash_flow', label: 'Cash Flow', kind: 'currency', higherIsBetter: true },
  { key: 'cap_rate', label: 'Cap Rate', kind: 'percent', higherIsBetter: true },
  { key: 'cash_on_cash', label: 'Cash on Cash', kind: 'percent', higherIsBetter: true },
  { key: 'one_year_roi', label: '1-Year ROI', kind: 'percent', higherIsBetter: true },
  { key: 'location_score', label: 'Location Score', kind: 'score', higherIsBetter: true },
  { key: 'quantum_overall', label: 'Quantum', kind: 'percent', higherIsBetter: true },
  { key: 'strategy', label: 'Strategy', kind: 'text', higherIsBetter: null },
]

function propertyKey(item: { id?: string; address?: string }): string {
  return (item.id || item.address || '').trim()
}

function money(n: number): string {
  const rounded = Math.round(n)
  if (rounded < 0) return `-$${Math.abs(rounded).toLocaleString()}`
  return `$${rounded.toLocaleString()}`
}

function formatMetric(value: unknown, kind: 'currency' | 'percent' | 'score' | 'text'): string {
  if (value == null || value === '') return '—'
  if (kind === 'text') return String(value)
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return String(value)
  if (kind === 'currency') return money(n)
  if (kind === 'percent') return `${n.toFixed(2)}%`
  return `${n.toFixed(1)}/10`
}

function bestIndexes(values: Array<number | null>, higherIsBetter: boolean): Set<number> {
  const nums = values
    .map((v, i) => (v != null && Number.isFinite(v) ? { i, v } : null))
    .filter((row): row is { i: number; v: number } => row != null)
  if (nums.length < 2) return new Set()
  const target = higherIsBetter
    ? Math.max(...nums.map((row) => row.v))
    : Math.min(...nums.map((row) => row.v))
  return new Set(nums.filter((row) => row.v === target).map((row) => row.i))
}

export function ComparePage() {
  const [query, setQuery] = useState('')
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [metrics, setMetrics] = useState<ComparisonRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const portfolio = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
  })

  const properties = portfolio.data?.properties ?? []
  const byKey = useMemo(() => {
    const map = new Map<string, PortfolioItem>()
    for (const item of properties) {
      const key = propertyKey(item)
      if (key) map.set(key, item)
    }
    return map
  }, [properties])

  const selectedItems = selectedKeys
    .map((key) => byKey.get(key))
    .filter((item): item is PortfolioItem => Boolean(item))

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const rows = needle
      ? properties.filter((p) => {
          const hay = [p.address, p.market_city, p.state_code, p.strategy]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
          return hay.includes(needle)
        })
      : properties
    return rows.slice(0, 80)
  }, [properties, query])

  useEffect(() => {
    document.title = 'Compare · CapEigen'
  }, [])

  function toggle(item: PortfolioItem) {
    const key = propertyKey(item)
    if (!key) return
    setSelectedKeys((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key)
      if (prev.length >= MAX_SELECTED) return prev
      return [...prev, key]
    })
  }

  async function runCompare() {
    if (selectedItems.length < 2) {
      setError('Select at least two properties to compare.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const rows = await Promise.all(
        selectedItems.map(async (item) => {
          try {
            const detail = await fetchPropertyDetail({
              id: item.id || null,
              address: item.address || null,
            })
            if (detail) return comparisonRowFromProperty(detail)
          } catch {
            // Fall back to catalog list metrics if the detail fetch fails.
          }
          return comparisonRowFromPortfolioItem(item)
        }),
      )
      setMetrics(rows)
      trackPreviewEvent('compare', {
        path: '/compare',
        label: selectedItems.map((p) => p.address).join(', '),
        payload: { addresses: selectedItems.map((p) => p.address) },
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Compare failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Compare properties</h1>
        <p className="mt-1 text-muted">
          Search the catalog and pick up to four listings for side-by-side underwriting.
        </p>
      </header>

      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search address, city, or state"
          className="mb-3 w-full rounded-lg border border-border px-3 py-2 text-sm outline-none focus:border-primary"
        />

        {selectedItems.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {selectedItems.map((item) => {
              const key = propertyKey(item)
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggle(item)}
                  className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                >
                  {item.address} ×
                </button>
              )
            })}
          </div>
        )}

        {portfolio.isLoading && <p className="text-sm text-muted">Loading catalog…</p>}
        {portfolio.error && (
          <p className="text-sm text-red-600">{(portfolio.error as Error).message}</p>
        )}

        <div className="mb-3 grid max-h-72 gap-1 overflow-auto sm:grid-cols-2">
          {filtered.map((item) => {
            const key = propertyKey(item)
            const checked = selectedKeys.includes(key)
            const disabled = !checked && selectedKeys.length >= MAX_SELECTED
            return (
              <label
                key={key}
                className={clsx(
                  'flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface',
                  disabled && 'opacity-50',
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(item)}
                />
                <span className="min-w-0">
                  <span className="block truncate">{item.address}</span>
                  <span className="block text-xs text-muted">
                    {[item.market_city, item.state_code].filter(Boolean).join(', ') || '—'}
                    {item.price != null ? ` · ${money(item.price)}` : ''}
                  </span>
                </span>
              </label>
            )
          })}
          {!portfolio.isLoading && filtered.length === 0 && (
            <p className="text-sm text-muted">
              {properties.length === 0
                ? 'No properties in the catalog yet.'
                : 'No properties match that search.'}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy || selectedItems.length < 2}
            onClick={() => void runCompare()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {busy ? 'Comparing…' : 'Compare'}
          </button>
          <p className="text-xs text-muted">
            {selectedItems.length} of {MAX_SELECTED} selected
          </p>
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      {metrics.length > 0 && (
        <div className="overflow-x-auto rounded-2xl border border-border bg-card shadow-sm">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2">Metric</th>
                {metrics.map((row) => (
                  <th key={row.property_id || row.address} className="max-w-[14rem] px-3 py-2">
                    <Link
                      className="text-primary hover:underline"
                      to={propertySearchPath({
                        address: row.address,
                        id: row.property_id,
                      })}
                    >
                      {row.address}
                    </Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRIC_ROWS.filter((row) => row.key !== 'address').map((def) => {
                const values = metrics.map((m) => {
                  const raw = m[def.key]
                  return typeof raw === 'number' ? raw : null
                })
                const winners =
                  def.higherIsBetter == null
                    ? new Set<number>()
                    : bestIndexes(values, def.higherIsBetter)
                return (
                  <tr key={def.key} className="border-t border-border">
                    <td className="px-3 py-2 font-medium">{def.label}</td>
                    {metrics.map((m, i) => (
                      <td
                        key={`${def.key}-${m.property_id || m.address}`}
                        className={clsx(
                          'px-3 py-2',
                          winners.has(i) && 'font-semibold text-primary',
                        )}
                      >
                        {formatMetric(m[def.key], def.kind)}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
