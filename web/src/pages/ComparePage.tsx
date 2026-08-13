import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../lib/api'
import { fetchPortfolio } from '../lib/portfolio'

type SavedProp = { address?: string; id?: string; property_id?: string }

export function ComparePage() {
  const [selected, setSelected] = useState<string[]>([])
  const [metrics, setMetrics] = useState<Record<string, unknown>[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const saved = useQuery({
    queryKey: ['saved'],
    queryFn: () =>
      apiFetch<{ properties: SavedProp[] }>('/api/properties/saved').catch(() => ({
        properties: [] as SavedProp[],
      })),
  })

  const portfolio = useQuery({
    queryKey: ['portfolio-compare'],
    queryFn: () =>
      fetchPortfolio().then((r) => r.properties.map((p) => ({ address: p.address }))),
  })

  const options = [
    ...(saved.data?.properties || []),
    ...((portfolio.data || []).map((p) => ({ address: p.address })) as SavedProp[]),
  ]
  const addresses = Array.from(
    new Set(options.map((p) => p.address).filter(Boolean) as string[]),
  ).slice(0, 100)

  useEffect(() => {
    document.title = 'Compare · CapEigen'
  }, [])

  function toggle(addr: string) {
    setSelected((prev) => {
      if (prev.includes(addr)) return prev.filter((a) => a !== addr)
      if (prev.length >= 4) return prev
      return [...prev, addr]
    })
  }

  async function runCompare() {
    if (selected.length < 1) return
    setBusy(true)
    setError(null)
    try {
      const res = await apiFetch<{ metrics: Record<string, unknown>[] }>('/api/compare', {
        method: 'POST',
        body: JSON.stringify({ addresses: selected }),
      })
      setMetrics(res.metrics)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Compare failed')
    } finally {
      setBusy(false)
    }
  }

  const keys = [
    ['address', 'Address'],
    ['price', 'List Price'],
    ['monthly_rent', 'Monthly Rent'],
    ['monthly_net_cash_flow', 'Cash Flow'],
    ['cap_rate', 'Cap Rate'],
    ['cash_on_cash', 'Cash on Cash'],
    ['one_year_roi', '1-Year ROI'],
    ['location_score', 'Location Score'],
    ['quantum_overall', 'Quantum'],
    ['strategy', 'Strategy'],
  ] as const

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Compare properties</h1>
        <p className="mt-1 text-muted">Select up to four properties for side-by-side metrics.</p>
      </header>

      <div className="rounded-2xl border border-border bg-white p-4 shadow-sm">
        <div className="mb-3 grid max-h-64 gap-2 overflow-auto sm:grid-cols-2">
          {addresses.map((addr) => (
            <label key={addr} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(addr)}
                onChange={() => toggle(addr)}
              />
              <span className="truncate">{addr}</span>
            </label>
          ))}
          {addresses.length === 0 && (
            <p className="text-sm text-muted">No properties available yet.</p>
          )}
        </div>
        <button
          type="button"
          disabled={busy || selected.length === 0}
          onClick={runCompare}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          {busy ? 'Comparing…' : 'Compare'}
        </button>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      {metrics.length > 0 && (
        <div className="overflow-x-auto rounded-2xl border border-border bg-white shadow-sm">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2">Metric</th>
                {metrics.map((_, i) => (
                  <th key={i} className="px-3 py-2">
                    Prop {i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.map(([key, label]) => (
                <tr key={key} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{label}</td>
                  {metrics.map((m, i) => (
                    <td key={i} className="px-3 py-2">
                      {formatCell(m[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') {
    if (Math.abs(value) >= 100) return Math.round(value).toLocaleString()
    return value.toFixed(2)
  }
  return String(value)
}
