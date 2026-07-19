import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiFetch, type AnalysisJob, type FinanceResult } from '../lib/api'

type Assumptions = {
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

function num(v: unknown, fallback = 0) {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function money(n: number) {
  return `$${Math.round(n).toLocaleString()}`
}

export function SearchPage() {
  const [params] = useSearchParams()
  const [query, setQuery] = useState(params.get('address') || '')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null)
  const [finance, setFinance] = useState<Record<string, number> | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  const jobQuery = useQuery({
    queryKey: ['analysis', jobId],
    enabled: Boolean(jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'done' || s === 'error' ? false : 2000
    },
    queryFn: () => apiFetch<AnalysisJob>(`/api/analysis/${jobId}`),
  })

  const property = jobQuery.data?.property_data

  useEffect(() => {
    document.title = 'Individual Search · CapEigen'
  }, [])

  useEffect(() => {
    const addr = params.get('address')
    if (addr) setQuery(addr)
  }, [params])

  useEffect(() => {
    if (!property || assumptions) return
    setAssumptions({
      down_payment_pct: 25,
      interest_rate: 6,
      loan_term: 30,
      closing_costs_pct: 3,
      tax_rate: num(property.tax_rate, 1.2),
      monthly_insurance: num(property.insurance, 150),
      monthly_hoa: num(property.hoa, 0),
      maint_percent: num(property.maint_percent ?? property.original_ai_maint, 1),
      monthly_rent: num(
        property.rent ?? property.estimated_rent ?? property.original_ai_rent,
        0,
      ),
      vacancy_reserve_pct: num(property.vacancy_rate, 5),
      management_fee_pct: num(property.management_fee, 8),
    })
  }, [property, assumptions])

  useEffect(() => {
    if (!property || !assumptions) return
    const price = num(property.price ?? property.predicted_value)
    let cancelled = false
    ;(async () => {
      try {
        const res = await apiFetch<FinanceResult>('/api/finance/recalc', {
          method: 'POST',
          body: JSON.stringify({
            ...assumptions,
            price,
            job_id: jobId,
            location_score: num(property.location_score, 5),
            forecast_rate: num(property.forecast_rate, 0),
          }),
        })
        if (!cancelled) {
          const flat: Record<string, number> = {}
          Object.entries(res.finance).forEach(([k, v]) => {
            if (typeof v === 'number') flat[k] = v
          })
          setFinance(flat)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Finance failed')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [property, assumptions, jobId])

  async function searchAddresses(q: string) {
    setQuery(q)
    if (q.trim().length < 2) {
      setSuggestions([])
      return
    }
    try {
      const res = await apiFetch<{ addresses: string[] }>(
        `/api/properties/search?q=${encodeURIComponent(q)}&limit=8`,
      )
      setSuggestions(res.addresses)
    } catch {
      setSuggestions([])
    }
  }

  async function startAnalysis(address?: string) {
    const target = (address || query).trim()
    if (!target) return
    setBusy(true)
    setError(null)
    setAssumptions(null)
    setFinance(null)
    setShareUrl(null)
    try {
      const res = await apiFetch<{ job_id: string }>('/api/analysis/start', {
        method: 'POST',
        body: JSON.stringify({ address: target }),
      })
      setJobId(res.job_id)
      setQuery(target)
      setSuggestions([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setBusy(false)
    }
  }

  async function downloadPdf() {
    if (!property || !finance) return
    const blob = await apiFetch<Blob>('/api/pdf', {
      method: 'POST',
      body: JSON.stringify({
        address: property.address || query,
        property_info: property,
        metrics: finance,
        table_data: [],
        params: assumptions || {},
        location_score: num(property.location_score, 5),
        quantum_risk: property.quantum_risk,
        forecast_display: property._forecast_display_cache,
      }),
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'capeigen-analysis.pdf'
    a.click()
    URL.revokeObjectURL(url)
  }

  async function createShare() {
    const propertyId = String(property?.id || property?.property_id || '')
    if (!propertyId) {
      setError('Save the property before creating a share link.')
      return
    }
    const res = await apiFetch<{ share_url: string }>('/api/shares', {
      method: 'POST',
      body: JSON.stringify({
        property_id: propertyId,
        base_url: window.location.origin,
      }),
    })
    setShareUrl(res.share_url)
  }

  async function bookmark() {
    await apiFetch('/api/properties/bookmark', {
      method: 'POST',
      body: JSON.stringify({
        property_id: property?.id || property?.property_id,
        property_data: property,
      }),
    })
  }

  const forecastChart = useMemo(() => {
    const cache = property?._forecast_display_cache as
      | { yearly_values?: number[] }
      | undefined
    const values = cache?.yearly_values
    if (!Array.isArray(values)) return []
    return values.map((v, i) => ({ year: `Y${i}`, value: Number(v) }))
  }, [property])

  const deferred = jobQuery.data?.deferred_tasks ?? []
  const total = jobQuery.data?.deferred_tasks_total || 0
  const done = Math.max(total - deferred.length, 0)

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="space-y-4 rounded-2xl border border-border bg-white/90 p-4 shadow-sm">
        <h2 className="font-display text-lg font-semibold">Assumptions</h2>
        {assumptions ? (
          <div className="space-y-3 text-sm">
            {(
              [
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
            ).map(([key, label, min, max, step]) => (
              <label key={key} className="block">
                <span className="text-muted">
                  {label}: {assumptions[key]}
                </span>
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={step}
                  value={assumptions[key]}
                  onChange={(e) =>
                    setAssumptions({ ...assumptions, [key]: Number(e.target.value) })
                  }
                  className="mt-1 w-full accent-primary"
                />
              </label>
            ))}
            <button
              type="button"
              onClick={bookmark}
              className="w-full rounded-lg border border-border py-2 hover:bg-surface"
            >
              Save to my account
            </button>
          </div>
        ) : (
          <p className="text-sm text-muted">Run an analysis to edit assumptions.</p>
        )}
      </aside>

      <div className="space-y-6">
        <header>
          <h1 className="font-display text-3xl font-semibold">Individual Search</h1>
          <p className="mt-1 text-muted">
            Enter an address to estimate rent, cash flow, and long-term returns.
          </p>
        </header>

        <div className="relative rounded-2xl border border-border bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              value={query}
              onChange={(e) => searchAddresses(e.target.value)}
              placeholder="123 Main St, Austin, TX"
              className="flex-1 rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => startAnalysis()}
              className="rounded-lg bg-primary px-5 py-2 font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
            >
              {busy ? 'Starting…' : 'Analyze Property'}
            </button>
          </div>
          {suggestions.length > 0 && (
            <ul className="absolute left-4 right-4 top-full z-10 mt-1 max-h-48 overflow-auto rounded-lg border border-border bg-white shadow-lg">
              {suggestions.map((addr) => (
                <li key={addr}>
                  <button
                    type="button"
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-surface"
                    onClick={() => startAnalysis(addr)}
                  >
                    {addr}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {jobQuery.data?.error && (
          <p className="text-sm text-amber-700">{jobQuery.data.error}</p>
        )}

        {jobId && deferred.length > 0 && (
          <div className="rounded-xl border border-border bg-white p-3 text-sm">
            <p className="mb-2 text-muted">
              Background: {deferred[0]} ({done}/{total})
            </p>
            <div className="h-2 overflow-hidden rounded-full bg-surface">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${total ? (done / total) * 100 : 0}%` }}
              />
            </div>
          </div>
        )}

        {property && (
          <section className="space-y-4 rounded-2xl border border-border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  {String(property.address || query)}
                </h2>
                <p className="text-sm text-muted">
                  {jobQuery.data?.from_kb ? 'Loaded from knowledge base' : 'AI research'}
                  {jobQuery.data?.status === 'running' ? ' · still computing…' : ''}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={downloadPdf}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
                >
                  Download PDF
                </button>
                <button
                  type="button"
                  onClick={createShare}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
                >
                  Share link
                </button>
              </div>
            </div>
            {shareUrl && (
              <p className="break-all text-sm text-primary">
                Share: <a href={shareUrl}>{shareUrl}</a>
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ['Price', money(num(property.price ?? property.predicted_value))],
                ['Monthly rent', money(assumptions?.monthly_rent ?? 0)],
                [
                  'Cash flow / mo',
                  money(finance?.monthly_net_cash_flow ?? 0),
                ],
                ['Cap rate', `${num(finance?.cap_rate).toFixed(2)}%`],
                ['Cash on cash', `${num(finance?.cash_on_cash).toFixed(2)}%`],
                [
                  'Location score',
                  `${num(property.location_score, 5).toFixed(1)}/10`,
                ],
                [
                  'Quantum alignment',
                  property.quantum_risk
                    ? `${num((property.quantum_risk as { overall_success_pct?: number }).overall_success_pct).toFixed(1)}%`
                    : 'Pending…',
                ],
                ['Strategy', String(property.strategy || '—')],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl bg-surface/80 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
                  <p className="mt-1 font-display text-lg font-semibold">{value}</p>
                </div>
              ))}
            </div>

            {forecastChart.length > 0 && (
              <div className="h-64">
                <h3 className="mb-2 font-display text-lg font-semibold">10-year forecast</h3>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={forecastChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ef" />
                    <XAxis dataKey="year" />
                    <YAxis tickFormatter={(v) => `$${Math.round(v / 1000)}k`} />
                    <Tooltip formatter={(v) => money(Number(v))} />
                    <Bar dataKey="value" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {typeof property.summary === 'string' && property.summary && (
              <div>
                <h3 className="mb-2 font-display text-lg font-semibold">Summary</h3>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-text/90">
                  {property.summary}
                </p>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
