import { useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../lib/api'

type ArchivedProperty = {
  id?: string
  address?: string | null
  market_city?: string | null
  state_code?: string | null
  zip_code?: string | null
  price?: number | null
  predicted_value?: number | null
  rent?: number | null
  original_ai_rent?: number | null
  monthly_net_cash_flow?: number | null
  location_score?: number | null
  quantum_risk_score?: number | null
  square_footage?: number | null
  year_built?: number | null
  tax_rate?: number | null
  hoa?: number | null
  insurance?: number | null
  maint_percent?: number | null
  original_ai_maint?: number | null
  appreciation_forecast?: number | null
  forecast_rate?: number | null
  forecast_growth?: number | null
  ai_vacancy_rate?: number | null
  ai_management_fee?: number | null
  property_label?: string | null
  property_category?: string | null
  property_condition?: string | null
  strategy_tag?: string | null
  listing_status?: string | null
  days_on_market?: number | null
  latitude?: number | null
  longitude?: number | null
  from_kb?: boolean | null
  timestamp?: string | null
  archived_at?: string | null
}

type ArchivedListResponse = {
  properties: ArchivedProperty[]
  total: number
  limit: number
  offset: number
  q?: string | null
}

type PortfolioResponse = {
  properties?: ArchivedProperty[]
}

const PAGE_SIZE = 50
const EXPORT_PAGE_SIZE = 200

const CSV_COLUMNS = [
  'dataset_source',
  'id',
  'address',
  'zip_code',
  'state_code',
  'market_city',
  'price',
  'predicted_value',
  'year_built',
  'square_footage',
  'rent',
  'original_ai_rent',
  'tax_rate',
  'hoa',
  'insurance',
  'maint_percent',
  'original_ai_maint',
  'location_score',
  'quantum_risk_score',
  'appreciation_forecast',
  'forecast_rate',
  'forecast_growth',
  'ai_vacancy_rate',
  'ai_management_fee',
  'monthly_net_cash_flow',
  'property_label',
  'property_category',
  'property_condition',
  'strategy_tag',
  'listing_status',
  'days_on_market',
  'latitude',
  'longitude',
  'from_kb',
  'timestamp',
  'archived_at',
] as const

function formatWhen(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString()
}

function formatMoney(value?: number | null) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(Number(value))
}

function formatNumber(value?: number | null, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
  })
}

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

function cellValue(row: Record<string, unknown>, key: string): string {
  const value = row[key]
  if (value == null) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  const lines = [
    CSV_COLUMNS.join(','),
    ...rows.map((row) =>
      CSV_COLUMNS.map((col) => csvEscape(cellValue(row, col))).join(','),
    ),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const PAGE_FETCH_TIMEOUT_MS = 45_000

async function apiFetchPage<T>(path: string): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), PAGE_FETCH_TIMEOUT_MS)
  try {
    return await apiFetch<T>(path, { signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(
        `Archive page timed out after ${PAGE_FETCH_TIMEOUT_MS / 1000}s. Confirm the harvest API is awake, then retry.`,
      )
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

async function fetchAllArchived(
  query: string,
  onProgress: (loaded: number, total: number) => void,
): Promise<Record<string, unknown>[]> {
  const out: Record<string, unknown>[] = []
  let offset = 0
  let total = Number.POSITIVE_INFINITY

  while (offset < total) {
    const params = new URLSearchParams({
      limit: String(EXPORT_PAGE_SIZE),
      offset: String(offset),
    })
    if (query.trim()) params.set('q', query.trim())
    const res = await apiFetchPage<ArchivedListResponse>(
      `/api/admin/archived-properties?${params.toString()}`,
    )
    const batch = res.properties || []
    total = typeof res.total === 'number' ? res.total : offset + batch.length
    for (const item of batch) {
      out.push({ ...item, dataset_source: 'archived' })
    }
    offset += EXPORT_PAGE_SIZE
    onProgress(Math.min(out.length, total), total)
    if (batch.length === 0) break
    // Guard against a gateway that ignores offset and repeats page 1.
    if (batch.length < EXPORT_PAGE_SIZE) break
    if (out.length >= total) break
  }
  return out
}

async function fetchActiveCatalog(
  onProgress: (message: string) => void,
): Promise<Record<string, unknown>[]> {
  onProgress('Loading live catalog…')
  const res = await apiFetchPage<PortfolioResponse>('/api/portfolio')
  return (res.properties || []).map((item) => ({
    ...item,
    dataset_source: 'active',
    archived_at: null,
  }))
}

export function ArchivedPropertiesPage() {
  const [rows, setRows] = useState<ArchivedProperty[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [query, setQuery] = useState('')
  const [draftQuery, setDraftQuery] = useState('')
  const [includeActive, setIncludeActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [exportProgress, setExportProgress] = useState<string | null>(null)

  async function load(nextPage = page, nextQuery = query) {
    setBusy(true)
    setError(null)
    const offset = nextPage * PAGE_SIZE
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    })
    if (nextQuery.trim()) params.set('q', nextQuery.trim())
    try {
      const res = await apiFetch<ArchivedListResponse>(
        `/api/admin/archived-properties?${params.toString()}`,
      )
      setRows(res.properties || [])
      setTotal(res.total || 0)
      setPage(nextPage)
      setQuery(nextQuery)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not load archived properties'
      const looksMissing =
        /not found/i.test(message) ||
        message.trim() === '404' ||
        /failed to fetch/i.test(message)
      setError(
        looksMissing
          ? `${message}. The archived-properties API may not be running on the harvest machine yet — rebuild/restart the API container (docker compose up --build -d api). Your data is still in Postgres; this is a routing/deploy issue, not a wipe.`
          : message,
      )
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    document.title = 'Archived properties · CapEigen'
    void load(0, '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pageCount = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total],
  )
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1
  const rangeEnd = Math.min(total, (page + 1) * PAGE_SIZE)

  async function downloadDataset() {
    setExporting(true)
    setError(null)
    setExportProgress('Starting export…')
    try {
      const archived = await fetchAllArchived(query, (loaded, expected) => {
        setExportProgress(`Fetched ${loaded.toLocaleString()} / ${expected.toLocaleString()} archived rows…`)
      })
      let combined = archived
      if (includeActive) {
        const active = await fetchActiveCatalog(setExportProgress)
        combined = [...archived, ...active]
        setExportProgress(
          `Building CSV (${combined.length.toLocaleString()} rows: ${archived.length} archived + ${active.length} active)…`,
        )
      } else {
        setExportProgress(`Building CSV (${combined.length.toLocaleString()} rows)…`)
      }
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      downloadCsv(
        `capeigen-dataset-${includeActive ? 'full' : 'archived'}-${stamp}.csv`,
        combined,
      )
      setExportProgress(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not download dataset')
      setExportProgress(null)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold">Archived properties</h1>
          <p className="mt-1 max-w-2xl text-muted">
            Harvested listings older than 30 days move here. Download builds the CSV in your
            browser from small paged API reads (usually ~1–3 MB total).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm">
            <input
              type="checkbox"
              checked={includeActive}
              onChange={(e) => setIncludeActive(e.target.checked)}
            />
            Include live catalog
          </label>
          <button
            type="button"
            onClick={() => void downloadDataset()}
            disabled={exporting || busy}
            className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {exporting ? 'Downloading…' : 'Download dataset CSV'}
          </button>
        </div>
      </header>
      {exportProgress && <p className="text-sm text-muted">{exportProgress}</p>}

      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void load(0, draftQuery)
        }}
      >
        <input
          value={draftQuery}
          onChange={(e) => setDraftQuery(e.target.value)}
          placeholder="Search address, city, ZIP, or state"
          className="min-w-[16rem] flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface"
        >
          Search
        </button>
        <button
          type="button"
          onClick={() => {
            setDraftQuery('')
            void load(0, '')
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={() => void load(page, query)}
          className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface"
        >
          Refresh
        </button>
      </form>

      {error && <p className="text-red-600">{error}</p>}
      {busy && <p className="text-muted">Loading archive…</p>}

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
        <p>
          {total === 0
            ? 'No archived properties yet.'
            : `Showing ${rangeStart}–${rangeEnd} of ${total.toLocaleString()}`}
          {query.trim() ? ` · filter “${query.trim()}”` : ''}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || page <= 0}
            onClick={() => void load(page - 1, query)}
            className="rounded-lg border border-border px-3 py-1.5 hover:bg-surface disabled:opacity-50"
          >
            Previous
          </button>
          <span className="self-center">
            Page {Math.min(page + 1, pageCount)} / {pageCount}
          </span>
          <button
            type="button"
            disabled={busy || page + 1 >= pageCount}
            onClick={() => void load(page + 1, query)}
            className="rounded-lg border border-border px-3 py-1.5 hover:bg-surface disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-surface text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Address</th>
              <th className="px-3 py-2 font-medium">Market</th>
              <th className="px-3 py-2 font-medium">Price</th>
              <th className="px-3 py-2 font-medium">AI value</th>
              <th className="px-3 py-2 font-medium">Rent</th>
              <th className="px-3 py-2 font-medium">Cash flow</th>
              <th className="px-3 py-2 font-medium">Score</th>
              <th className="px-3 py-2 font-medium">Label</th>
              <th className="px-3 py-2 font-medium">Archived</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id || row.address || String(row.archived_at)} className="border-t border-border">
                <td className="max-w-[18rem] px-3 py-2 font-medium">
                  <div className="truncate" title={row.address || undefined}>
                    {row.address || '—'}
                  </div>
                  <div className="text-xs text-muted">
                    {[row.square_footage ? `${formatNumber(row.square_footage)} sqft` : null, row.year_built]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </div>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted">
                  {[row.market_city, row.state_code, row.zip_code].filter(Boolean).join(', ') || '—'}
                </td>
                <td className="whitespace-nowrap px-3 py-2">{formatMoney(row.price)}</td>
                <td className="whitespace-nowrap px-3 py-2">{formatMoney(row.predicted_value)}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  {formatMoney(row.rent ?? row.original_ai_rent)}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  {formatMoney(row.monthly_net_cash_flow)}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  {formatNumber(row.location_score, 1)}
                  {row.quantum_risk_score != null ? (
                    <span className="text-muted">
                      {' '}
                      / {formatNumber(row.quantum_risk_score, 2)}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2">
                  {row.strategy_tag || row.property_label || row.property_category || '—'}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted">
                  {formatWhen(row.archived_at)}
                </td>
              </tr>
            ))}
            {!busy && rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-muted">
                  No archived rows match this filter. After harvest ages listings past 30 days,
                  they appear here for review and export.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
