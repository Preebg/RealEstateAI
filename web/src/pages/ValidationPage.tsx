import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { apiFetch } from '../lib/api'

type ValidationResult = {
  row_count: number
  report_text: string
  calibration_png_base64?: string | null
  price_mape_pct: number | null
  rent_mape_pct: number | null
}

export function ValidationPage() {
  const [result, setResult] = useState<ValidationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    document.title = 'Model Validation · CapEigen'
  }, [])

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const fileInput = form.elements.namedItem('csv') as HTMLInputElement
    const file = fileInput.files?.[0]
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await apiFetch<ValidationResult>('/api/validation/backtest', {
        method: 'POST',
        body,
      })
      setResult(res)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Validation failed (admin access required)',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Model validation</h1>
        <p className="mt-1 text-muted">
          Upload a comps CSV to compute price/rent MAPE and RMSE (admin only).
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        className="rounded-2xl border border-border bg-white p-5 shadow-sm"
      >
        <input
          name="csv"
          type="file"
          accept=".csv,text/csv"
          required
          className="block w-full text-sm"
        />
        <button
          type="submit"
          disabled={busy}
          className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          {busy ? 'Running…' : 'Run backtest'}
        </button>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </form>

      {result && (
        <section className="space-y-4 rounded-2xl border border-border bg-white p-5 shadow-sm">
          <pre className="whitespace-pre-wrap text-sm">{result.report_text}</pre>
          {result.calibration_png_base64 && (
            <img
              src={`data:image/png;base64,${result.calibration_png_base64}`}
              alt="Calibration plot"
              className="max-w-full rounded-lg border border-border"
            />
          )}
        </section>
      )}
    </div>
  )
}
