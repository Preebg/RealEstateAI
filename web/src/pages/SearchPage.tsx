import { useEffect, useMemo, useRef, useState } from 'react'
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
import {
  analyzeInvestment,
  normalizeMonthlyInsurance,
  normalizePercentRate,
  normalizeTaxRatePercent,
  type FinanceMetrics,
} from '../lib/finance'
import {
  fetchPropertyDetail,
  createPropertyShare,
  firstCatalogUuid,
} from '../lib/portfolio'

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

function pdfDownloadFilename(address: string): string {
  const cleaned = address
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '')
    .replace(/\s+/g, ' ')
    .replace(/^[.\s]+|[.\s]+$/g, '')
  const slug = (cleaned || 'property').slice(0, 80)
  return `CapEigen - ${slug}.pdf`
}

function moneyExact(n: number) {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return n < 0 ? `-$${abs}` : `$${abs}`
}

function addressesMatch(a?: unknown, b?: unknown): boolean {
  return String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase()
}

function assumptionsFromProperty(property: Record<string, unknown>): Assumptions {
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
      num(property.vacancy_rate ?? property.ai_vacancy_rate, 5),
    ),
    management_fee_pct: normalizePercentRate(
      num(property.management_fee ?? property.ai_management_fee, 8),
    ),
  }
}

function jsonSafe<T>(value: T): T {
  return JSON.parse(
    JSON.stringify(value, (_key, v) => (typeof v === 'bigint' ? Number(v) : v)),
  ) as T
}

function quantumPayload(value: unknown): Record<string, number> | undefined {
  if (!value || typeof value !== 'object') return undefined
  const q = value as Record<string, unknown>
  const keys = [
    'cashflow_success_pct',
    'appreciation_success_pct',
    'combined_wealth_success_pct',
    'overall_success_pct',
  ] as const
  if (!keys.every((k) => typeof q[k] === 'number')) return undefined
  return q as Record<string, number>
}

function forecastPayload(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object') return undefined
  const f = value as Record<string, unknown>
  if (!Array.isArray(f.value_schedule_p50)) return undefined
  return f
}

function cashFlowRows(assumptions: Assumptions, finance: FinanceMetrics) {
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

export function SearchPage() {
  const [params] = useSearchParams()
  const paramAddress = params.get('address') || ''
  const paramId = params.get('id') || ''
  const [query, setQuery] = useState(paramAddress)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const [shareBusy, setShareBusy] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [assumptionsDirty, setAssumptionsDirty] = useState(false)
  const autoStartedKey = useRef<string | null>(null)

  const jobQuery = useQuery({
    queryKey: ['analysis', jobId],
    enabled: Boolean(jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'done' || s === 'error' ? false : 2000
    },
    queryFn: () => apiFetch<AnalysisJob>(`/api/analysis/${jobId}`),
  })

  const kbQuery = useQuery({
    queryKey: ['kb-property', paramId, paramAddress],
    enabled: Boolean(paramId || paramAddress),
    queryFn: () => fetchPropertyDetail({ id: paramId || null, address: paramAddress || null }),
  })

  const jobProperty = jobQuery.data?.property_data
  const kbProperty = kbQuery.data
  const kbMatch =
    kbProperty &&
    (addressesMatch(kbProperty.address, query) ||
      (Boolean(paramId) && addressesMatch(query, paramAddress)))
      ? kbProperty
      : null
  const property = useMemo(() => {
    const base = jobProperty ?? kbMatch ?? null
    if (!base) return null
    const catalogId = firstCatalogUuid(
      base.id,
      base.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (catalogId && String(base.id || '') !== catalogId) {
      return { ...base, id: catalogId, property_id: catalogId }
    }
    return base
  }, [jobProperty, kbMatch, paramId])

  const finance = useMemo(() => {
    if (!property || !assumptions) return null
    return analyzeInvestment({
      ...assumptions,
      price: num(property.price ?? property.predicted_value),
    })
  }, [property, assumptions])

  useEffect(() => {
    document.title = 'Individual Search · CapEigen'
  }, [])

  useEffect(() => {
    if (paramAddress) setQuery(paramAddress)
  }, [paramAddress])

  useEffect(() => {
    if (!property || assumptions) return
    setAssumptions(assumptionsFromProperty(property))
  }, [property, assumptions])

  useEffect(() => {
    if (!assumptionsDirty || !property || !assumptions || !jobId || !finance) return
    let cancelled = false
    ;(async () => {
      try {
        await apiFetch<FinanceResult>('/api/finance/recalc', {
          method: 'POST',
          body: JSON.stringify({
            ...assumptions,
            price: num(property.price ?? property.predicted_value),
            job_id: jobId,
            location_score: num(property.location_score, 5),
            forecast_rate: num(property.forecast_rate, 0),
          }),
        })
      } catch {
        if (!cancelled) {
          // Client-side breakdown is already on screen.
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [assumptionsDirty, property, assumptions, jobId, finance])

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
    setShareUrl(null)
    setAssumptionsDirty(false)
    const sameListing = addressesMatch(property?.address, target)
    if (!sameListing) setAssumptions(null)
    try {
      const res = await apiFetch<{ job_id: string }>('/api/analysis/start', {
        method: 'POST',
        body: JSON.stringify({ address: target }),
      })
      setJobId(res.job_id)
      setQuery(target)
      setSuggestions([])
    } catch (err) {
      const catalogHit =
        addressesMatch(paramAddress, target) &&
        (kbQuery.isLoading || Boolean(kbQuery.data) || Boolean(paramId))
      if (!catalogHit) {
        setError(err instanceof Error ? err.message : 'Analysis failed')
      }
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const addr = paramAddress.trim()
    if (!addr) return
    const key = `${paramId}|${addr}`
    if (autoStartedKey.current === key) return
    autoStartedKey.current = key
    void startAnalysis(addr)
    // Auto-run once per home-page click-through. startAnalysis is recreated each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramAddress, paramId])

  async function downloadPdf() {
    if (!property || !finance || !assumptions) return
    const rows = cashFlowRows(assumptions, finance)
    const price = num(property.price ?? property.predicted_value)
    setPdfBusy(true)
    setError(null)
    try {
      const blob = await apiFetch<Blob>('/api/pdf', {
        method: 'POST',
        body: JSON.stringify({
          address: String(property.address || query),
          property_info: jsonSafe({
            ...property,
            summary:
              typeof property.summary === 'string' && property.summary
                ? property.summary
                : 'No summary available.',
          }),
          metrics: {
            'Risk-Adjusted Cap Rate': `${finance.cap_rate.toFixed(2)}%`,
            'Cash on Cash Return': `${finance.cash_on_cash.toFixed(2)}%`,
            'Monthly Net Cash Flow': moneyExact(finance.monthly_net_cash_flow),
            'Total Cash Required': moneyExact(finance.total_investment),
          },
          table_data: {
            Description: rows.map(([label]) => label),
            Amount: rows.map(([, amount]) => amount),
          },
          params: {
            'Offer Amount': money(price),
            'Down Payment': `${assumptions.down_payment_pct}%`,
            'Interest Rate': `${assumptions.interest_rate}%`,
            'Loan Term': `${assumptions.loan_term} Years`,
            'Monthly Rent': moneyExact(assumptions.monthly_rent),
          },
          location_score: num(property.location_score, 5),
          quantum_risk: quantumPayload(property.quantum_risk),
          forecast_display: forecastPayload(property._forecast_display_cache),
        }),
      })
      if (!(blob instanceof Blob) || blob.size < 8) {
        throw new Error('PDF download returned an empty file.')
      }
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = pdfDownloadFilename(String(property.address || query))
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF download failed')
    } finally {
      setPdfBusy(false)
    }
  }

  async function createShare() {
    const propertyId = firstCatalogUuid(
      property?.id,
      property?.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (!propertyId) {
      setError('Save the property to your account before creating a share link.')
      return
    }
    setError(null)
    setShareCopied(false)
    setShareBusy(true)
    setShareUrl(null)
    try {
      const res = await createPropertyShare({ propertyId })
      setShareUrl(res.share_url)
      try {
        await navigator.clipboard.writeText(res.share_url)
        setShareCopied(true)
      } catch {
        setShareCopied(false)
      }
    } catch (err) {
      setShareUrl(null)
      setError(err instanceof Error ? err.message : 'Failed to create share link')
    } finally {
      setShareBusy(false)
    }
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
  const fromKb = Boolean(jobQuery.data?.from_kb || (property && !jobProperty && kbMatch))
  const stillComputing =
    jobQuery.data?.status === 'running' && (deferred.length > 0 || !property)

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
                  onChange={(e) => {
                    setAssumptionsDirty(true)
                    setAssumptions({ ...assumptions, [key]: Number(e.target.value) })
                  }}
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
        {kbQuery.isLoading && paramAddress && !property && (
          <p className="text-sm text-muted">Loading property from catalog…</p>
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
                  {fromKb ? 'Loaded from knowledge base' : 'AI research'}
                  {stillComputing ? ' · still computing…' : ''}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={pdfBusy || !finance}
                  onClick={() => void downloadPdf()}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
                >
                  {pdfBusy ? 'Preparing PDF…' : 'Download PDF'}
                </button>
                <button
                  type="button"
                  disabled={shareBusy}
                  onClick={() => void createShare()}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
                >
                  {shareBusy ? 'Creating link…' : 'Share link'}
                </button>
              </div>
            </div>
            {(shareBusy || shareUrl) && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm">
                {shareUrl ? (
                  <>
                    <p className="font-medium text-text">Share link ready</p>
                    <a className="mt-1 block break-all text-primary underline" href={shareUrl}>
                      {shareUrl}
                    </a>
                    {shareCopied && (
                      <p className="mt-1 text-muted">Copied to clipboard</p>
                    )}
                  </>
                ) : (
                  <p className="text-muted">Creating share link…</p>
                )}
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ['Price', money(num(property.price ?? property.predicted_value))],
                ['Monthly rent', money(assumptions?.monthly_rent ?? 0)],
                ['Cash flow / mo', money(finance?.monthly_net_cash_flow ?? 0)],
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
                    : property.quantum_risk_score != null
                      ? `${num(property.quantum_risk_score).toFixed(1)}%`
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

            {finance && assumptions && (
              <div>
                <h3 className="mb-2 font-display text-lg font-semibold">
                  Monthly cash flow breakdown
                </h3>
                <div className="overflow-x-auto rounded-xl border border-border">
                  <table className="min-w-full text-sm">
                    <thead className="bg-surface text-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Description</th>
                        <th className="px-3 py-2 text-right font-medium">Monthly amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cashFlowRows(assumptions, finance).map(([label, amount, emphasis]) => (
                        <tr
                          key={label}
                          className={`border-t border-border ${emphasis ? 'bg-surface/60 font-semibold' : ''}`}
                        >
                          <td className="px-3 py-2">{label}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{amount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

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
