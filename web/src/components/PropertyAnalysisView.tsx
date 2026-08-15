import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { FinanceMetrics } from '../lib/finance'
import {
  ASSUMPTION_SLIDERS,
  assumptionsFromProperty,
  cashFlowRows,
  downloadPropertyPdf,
  financeFromProperty,
  forecastYearlyValues,
  formatYearBuilt,
  hydrateProperty,
  money,
  num,
  type Assumptions,
} from '../lib/propertyAnalysis'
import { trackPreviewEvent, trackPreviewEventDebounced } from '../lib/previewActivity'

type PropertyAnalysisViewProps = {
  property: Record<string, unknown> | null
  variant: 'account' | 'guest'
  addressLabel?: string
  sourceLabel?: string
  stillComputing?: boolean
  header?: ReactNode
  emptyHint?: string
  shareBusy?: boolean
  shareUrl?: string | null
  shareCopied?: boolean
  onShare?: () => void
  onBookmark?: () => void
  onAssumptionsChange?: (assumptions: Assumptions, finance: FinanceMetrics) => void
}

export function PropertyAnalysisView({
  property: rawProperty,
  variant,
  addressLabel,
  sourceLabel,
  stillComputing,
  header,
  emptyHint,
  shareBusy,
  shareUrl,
  shareCopied,
  onShare,
  onBookmark,
  onAssumptionsChange,
}: PropertyAnalysisViewProps) {
  const property = useMemo(
    () => (rawProperty ? hydrateProperty(rawProperty) : null),
    [rawProperty],
  )
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const propertyKey = `${String(property?.id || '')}|${String(property?.address || '')}`
  const lastKey = useRef<string>('')

  useEffect(() => {
    if (!property) {
      setAssumptions(null)
      lastKey.current = ''
      return
    }
    if (lastKey.current === propertyKey) return
    lastKey.current = propertyKey
    setAssumptions(assumptionsFromProperty(property))
  }, [property, propertyKey])

  const finance = useMemo(() => {
    if (!property || !assumptions) return null
    return financeFromProperty(property, assumptions)
  }, [property, assumptions])

  const forecastChart = useMemo(() => {
    if (!property) return []
    return forecastYearlyValues(property).map((v, i) => ({ year: `Y${i}`, value: v }))
  }, [property])

  async function handlePdf() {
    if (!property || !finance || !assumptions) return
    setPdfBusy(true)
    setError(null)
    try {
      downloadPropertyPdf({
        property,
        assumptions,
        finance,
        address: String(property.address || addressLabel || 'property'),
      })
      trackPreviewEvent('pdf', {
        path: window.location.pathname,
        label: String(property.address || addressLabel || 'property'),
        payload: { address: property.address },
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF download failed')
    } finally {
      setPdfBusy(false)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="space-y-4 rounded-2xl border border-border bg-white/90 p-4 shadow-sm">
        <h2 className="font-display text-lg font-semibold">Assumptions</h2>
        {assumptions ? (
          <div className="space-y-3 text-sm">
            {ASSUMPTION_SLIDERS.map(([key, label, min, max, step]) => (
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
                    const next = { ...assumptions, [key]: Number(e.target.value) }
                    setAssumptions(next)
                    if (property && onAssumptionsChange) {
                      onAssumptionsChange(next, financeFromProperty(property, next))
                    }
                    trackPreviewEventDebounced(
                      `assumptions:${String(property?.address || addressLabel || '')}`,
                      'assumption_change',
                      {
                        path: window.location.pathname,
                        label: String(property?.address || addressLabel || ''),
                        payload: { address: property?.address, [key]: Number(e.target.value) },
                      },
                    )
                  }}
                  className="mt-1 w-full accent-primary"
                />
              </label>
            ))}
            {variant === 'account' && onBookmark && (
              <button
                type="button"
                onClick={onBookmark}
                className="w-full rounded-lg border border-border py-2 hover:bg-surface"
              >
                Save to my account
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted">
            {emptyHint || 'Run an analysis to edit assumptions.'}
          </p>
        )}
      </aside>

      <div className="space-y-6">
        {header}

        {error && <p className="text-sm text-red-600">{error}</p>}

        {property && (
          <section className="space-y-4 rounded-2xl border border-border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  {String(property.address || addressLabel || 'Property')}
                </h2>
                {sourceLabel && (
                  <p className="text-sm text-muted">
                    {sourceLabel}
                    {stillComputing ? ' · still computing…' : ''}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={pdfBusy || !finance}
                  onClick={() => void handlePdf()}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
                >
                  {pdfBusy ? 'Preparing PDF…' : 'Download PDF'}
                </button>
                {variant === 'account' && onShare && (
                  <button
                    type="button"
                    disabled={shareBusy}
                    onClick={() => void onShare()}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-60"
                  >
                    {shareBusy ? 'Creating link…' : 'Share link'}
                  </button>
                )}
              </div>
            </div>
            {variant === 'account' && (shareBusy || shareUrl) && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm">
                {shareUrl ? (
                  <>
                    <p className="font-medium text-text">Share link ready</p>
                    <a className="mt-1 block break-all text-primary underline" href={shareUrl}>
                      {shareUrl}
                    </a>
                    {shareCopied && <p className="mt-1 text-muted">Copied to clipboard</p>}
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
                ['Location score', `${num(property.location_score, 5).toFixed(1)}/10`],
                ['Year built', formatYearBuilt(property.year_built)],
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
