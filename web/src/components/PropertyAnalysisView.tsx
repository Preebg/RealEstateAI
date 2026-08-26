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
  CRITICAL_ASSUMPTION_SLIDERS,
  FINANCING_ASSUMPTION_SLIDERS,
  assumptionMetaFromProperty,
  assumptionsFromProperty,
  cashFlowRows,
  downloadPropertyPdf,
  financeFromProperty,
  forecastYearlyValues,
  formatAssumptionDelta,
  formatYearBuilt,
  hasCriticalAssumptionChanges,
  hydrateProperty,
  money,
  num,
  type AssumptionMeta,
  type Assumptions,
  type CriticalAssumptionKey,
} from '../lib/propertyAnalysis'
import { trackPreviewEvent, trackPreviewEventDebounced } from '../lib/previewActivity'

type AssumptionPersistState = 'idle' | 'unsaved' | 'saving' | 'saved'

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
  onAssumptionsChange?: (
    assumptions: Assumptions,
    finance: FinanceMetrics,
    overrideNotes: string,
  ) => void
  assumptionPersistState?: AssumptionPersistState
}

const CRITICAL_LABELS: Record<CriticalAssumptionKey, string> = {
  monthly_rent: 'Monthly rent',
  vacancy_reserve_pct: 'Vacancy %',
  maint_percent: 'Maint %',
  management_fee_pct: 'Mgmt fee %',
}

function formatAiBaseline(key: CriticalAssumptionKey, value: number): string {
  if (key === 'monthly_rent') return money(value)
  return `${value.toFixed(1)}%`
}

function formatSourceLabel(source?: string): string {
  if (!source) return ''
  return source.replace(/_/g, ' ')
}

type AssumptionRowProps = {
  fieldKey: CriticalAssumptionKey
  label: string
  min: number
  max: number
  step: number
  value: number
  meta: AssumptionMeta
  onChange: (value: number) => void
  readOnly?: boolean
}

function AssumptionRow({
  fieldKey,
  label,
  min,
  max,
  step,
  value,
  meta,
  onChange,
  readOnly = false,
}: AssumptionRowProps) {
  const delta = formatAssumptionDelta(fieldKey, meta)
  return (
    <div className="rounded-xl border border-border bg-surface/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-text">
            {label}:{' '}
            <span className="tabular-nums">
              {fieldKey === 'monthly_rent' ? money(value) : `${value}%`}
            </span>
          </p>
          <p className="mt-0.5 text-xs text-muted">
            AI baseline: {formatAiBaseline(fieldKey, meta.aiValue)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {delta && (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-200">
              {delta}
            </span>
          )}
          {meta.confidenceLabel && (
            <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">
              {meta.confidenceLabel} confidence
            </span>
          )}
        </div>
      </div>
      {(meta.source || meta.rationale) && (
        <p className="mt-1.5 text-xs text-muted">
          {meta.source && (
            <span className="capitalize">{formatSourceLabel(meta.source)}</span>
          )}
          {meta.source && meta.rationale ? ' · ' : ''}
          {meta.rationale}
        </p>
      )}
      {!readOnly && (
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="mt-2 w-full accent-primary"
          aria-label={label}
        />
      )}
    </div>
  )
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
  assumptionPersistState = 'idle',
}: PropertyAnalysisViewProps) {
  const property = useMemo(
    () => (rawProperty ? hydrateProperty(rawProperty) : null),
    [rawProperty],
  )
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null)
  const [overrideNotes, setOverrideNotes] = useState('')
  const [financingOpen, setFinancingOpen] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const propertyKey = `${String(property?.id || '')}|${String(property?.address || '')}`
  const lastKey = useRef<string>('')

  useEffect(() => {
    if (!property) {
      setAssumptions(null)
      setOverrideNotes('')
      lastKey.current = ''
      return
    }
    if (lastKey.current === propertyKey) return
    lastKey.current = propertyKey
    setAssumptions(assumptionsFromProperty(property))
    setOverrideNotes(
      typeof property.override_notes === 'string' ? property.override_notes : '',
    )
  }, [property, propertyKey])

  const assumptionMeta = useMemo(() => {
    if (!property || !assumptions) return null
    return assumptionMetaFromProperty(property, assumptions)
  }, [property, assumptions])

  const finance = useMemo(() => {
    if (!property || !assumptions) return null
    return financeFromProperty(property, assumptions)
  }, [property, assumptions])

  const forecastChart = useMemo(() => {
    if (!property) return []
    return forecastYearlyValues(property).map((v, i) => ({ year: `Y${i}`, value: v }))
  }, [property])

  const showUnsaved =
    assumptionMeta &&
    hasCriticalAssumptionChanges(assumptionMeta) &&
    (assumptionPersistState === 'unsaved' || assumptionPersistState === 'saving')

  function applyAssumptionChange(key: keyof Assumptions, value: number) {
    if (!assumptions || !property) return
    const next = { ...assumptions, [key]: value }
    setAssumptions(next)
    const nextFinance = financeFromProperty(property, next)
    onAssumptionsChange?.(next, nextFinance, overrideNotes)
    trackPreviewEventDebounced(
      `assumptions:${String(property.address || addressLabel || '')}`,
      'assumption_change',
      {
        path: window.location.pathname,
        label: String(property.address || addressLabel || ''),
        payload: { address: property.address, [key]: value },
      },
    )
  }

  function handleOverrideNotesChange(notes: string) {
    setOverrideNotes(notes)
    if (assumptions && property && onAssumptionsChange) {
      onAssumptionsChange(assumptions, financeFromProperty(property, assumptions), notes)
    }
  }

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

  const isGuest = variant === 'guest'

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="space-y-4 rounded-2xl border border-border bg-card/90 p-4 shadow-sm">
        <div>
          <h2 className="font-display text-lg font-semibold">Assumptions</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {isGuest
              ? 'AI-proposed assumptions vs values used in this share (read-only).'
              : 'AI proposes assumptions — adjust before you trust cash flow.'}
          </p>
        </div>
        {assumptions && assumptionMeta ? (
          <div className="space-y-3 text-sm">
            {(showUnsaved || assumptionPersistState === 'saving') && !isGuest && (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-900 dark:text-amber-100">
                {assumptionPersistState === 'saving'
                  ? 'Saving assumption changes…'
                  : 'Unsaved assumption changes'}
              </p>
            )}
            {assumptionPersistState === 'saved' &&
              !isGuest &&
              hasCriticalAssumptionChanges(assumptionMeta) && (
              <p className="text-xs text-emerald-700 dark:text-emerald-300">Assumptions saved</p>
            )}
            <div className="space-y-2">
              {CRITICAL_ASSUMPTION_SLIDERS.map(([key, label, min, max, step]) => (
                <AssumptionRow
                  key={key}
                  fieldKey={key as CriticalAssumptionKey}
                  label={CRITICAL_LABELS[key as CriticalAssumptionKey] || label}
                  min={min}
                  max={max}
                  step={step}
                  value={assumptions[key as keyof Assumptions]}
                  meta={assumptionMeta[key as CriticalAssumptionKey]}
                  onChange={(value) => applyAssumptionChange(key as keyof Assumptions, value)}
                  readOnly={isGuest}
                />
              ))}
            </div>

            {variant === 'account' && (
              <label className="block">
                <span className="text-xs font-medium text-muted">Why I changed this</span>
                <textarea
                  value={overrideNotes}
                  onChange={(e) => handleOverrideNotesChange(e.target.value)}
                  rows={2}
                  placeholder="Optional — helps refine future AI estimates"
                  className="mt-1 w-full resize-y rounded-lg border border-border bg-card px-2.5 py-2 text-sm outline-none focus:border-primary"
                />
              </label>
            )}

            {!isGuest && (
              <div>
                <button
                  type="button"
                  onClick={() => setFinancingOpen((open) => !open)}
                  className="flex w-full items-center justify-between rounded-lg border border-border px-2.5 py-2 text-left text-xs font-medium text-muted hover:bg-surface"
                  aria-expanded={financingOpen}
                >
                  Financing &amp; carrying costs
                  <span aria-hidden>{financingOpen ? '−' : '+'}</span>
                </button>
                {financingOpen && (
                  <div className="mt-2 space-y-3 border-l-2 border-border pl-2">
                    {FINANCING_ASSUMPTION_SLIDERS.map(([key, label, min, max, step]) => (
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
                            applyAssumptionChange(key as keyof Assumptions, Number(e.target.value))
                          }
                          className="mt-1 w-full accent-primary"
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}

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
          <section className="space-y-4 rounded-2xl border border-border bg-card p-5 shadow-sm">
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
                  'In-app views',
                  Number(property.app_view_count || 0).toLocaleString(),
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
