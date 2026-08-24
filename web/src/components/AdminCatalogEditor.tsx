import { useEffect, useState, type FormEvent } from 'react'
import { apiFetch } from '../lib/api'
import { num } from '../lib/propertyAnalysis'

type MetricField = {
  key: string
  label: string
  step?: string
}

const NUMBER_FIELDS: MetricField[] = [
  { key: 'price', label: 'Price', step: '0.01' },
  { key: 'rent', label: 'Monthly rent', step: '0.01' },
  { key: 'year_built', label: 'Year built', step: '1' },
  { key: 'square_footage', label: 'Square footage', step: '1' },
  { key: 'tax_rate', label: 'Tax rate %', step: '0.01' },
  { key: 'insurance', label: 'Insurance / mo', step: '0.01' },
  { key: 'hoa', label: 'HOA / mo', step: '0.01' },
  { key: 'original_ai_maint', label: 'Maint %', step: '0.01' },
  { key: 'location_score', label: 'Location score', step: '0.1' },
  { key: 'monthly_net_cash_flow', label: 'Cash flow / mo', step: '0.01' },
  { key: 'forecast_rate', label: 'Forecast rate %', step: '0.01' },
  { key: 'quantum_risk_score', label: 'Quantum alignment %', step: '0.1' },
]

function fieldValue(property: Record<string, unknown>, key: string): string {
  if (key === 'rent') {
    const rent = property.rent ?? property.original_ai_rent
    return rent == null || rent === '' ? '' : String(rent)
  }
  const value = property[key]
  return value == null || value === '' ? '' : String(value)
}

type AdminCatalogEditorProps = {
  property: Record<string, unknown>
  propertyId: string
  onSaved: (next: Record<string, unknown>) => void
  onDeleted: () => void
}

export function AdminCatalogEditor({
  property,
  propertyId,
  onSaved,
  onDeleted,
}: AdminCatalogEditorProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [original, setOriginal] = useState<Record<string, string>>({})
  const [summary, setSummary] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const field of NUMBER_FIELDS) {
      next[field.key] = fieldValue(property, field.key)
    }
    setValues(next)
    setOriginal(next)
    setSummary(typeof property.summary === 'string' ? property.summary : '')
    setError(null)
    setInfo(null)
  }, [property, propertyId])

  async function onSave(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setInfo(null)
    const cashFlowChanged =
      (values.monthly_net_cash_flow ?? '').trim() !== (original.monthly_net_cash_flow ?? '').trim()
    const payload: Record<string, number | string | boolean> = {
      recalculate_cash_flow: !cashFlowChanged,
    }
    for (const field of NUMBER_FIELDS) {
      const raw = values[field.key]?.trim()
      if (!raw) continue
      if (field.key === 'monthly_net_cash_flow' && !cashFlowChanged) continue
      const parsed = num(raw, Number.NaN)
      if (!Number.isFinite(parsed)) {
        setBusy(false)
        setError(`Enter a number for ${field.label}.`)
        return
      }
      payload[field.key] = parsed
    }
    if (summary.trim()) payload.summary = summary.trim()
    try {
      const res = await apiFetch<{ property: Record<string, unknown> }>(
        `/api/admin/properties/${encodeURIComponent(propertyId)}`,
        { method: 'PATCH', body: JSON.stringify(payload) },
      )
      onSaved(res.property || {})
      setInfo('Catalog metrics saved. End users will see the updated values.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save catalog metrics')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete() {
    const address = String(property.address || propertyId)
    if (
      !window.confirm(
        `Remove “${address}” from the harvest Postgres catalog? End users will no longer see it.`,
      )
    ) {
      return
    }
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      await apiFetch(`/api/admin/properties/${encodeURIComponent(propertyId)}`, {
        method: 'DELETE',
      })
      onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove property')
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={(event) => void onSave(event)}
      className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50/70 p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Catalog admin</h2>
          <p className="mt-1 text-sm text-muted">
            Correct harvested metrics in local Postgres so every signed-in user sees accurate
            numbers. Cash flow is recalculated from rent and price unless you change that field.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onDelete()}
          className="rounded-lg border border-red-200 bg-card px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
        >
          Remove from catalog
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {NUMBER_FIELDS.map((field) => (
          <label key={field.key} className="block text-sm">
            <span className="mb-1 block font-medium">{field.label}</span>
            <input
              type="number"
              step={field.step}
              value={values[field.key] ?? ''}
              onChange={(e) => setValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
              className="w-full rounded-lg border border-border bg-card px-3 py-2"
            />
          </label>
        ))}
      </div>
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Summary</span>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          rows={4}
          className="w-full rounded-lg border border-border bg-card px-3 py-2"
        />
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {info && <p className="text-sm text-emerald-700">{info}</p>}
      <button
        type="submit"
        disabled={busy}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
      >
        {busy ? 'Saving…' : 'Save catalog metrics'}
      </button>
    </form>
  )
}
