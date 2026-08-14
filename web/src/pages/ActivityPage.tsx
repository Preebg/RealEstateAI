import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'

type PreviewEvent = {
  id?: string
  username?: string
  event_type?: string
  path?: string | null
  label?: string | null
  payload?: Record<string, unknown>
  created_at?: string
}

const LABELS: Record<string, string> = {
  login: 'Signed in',
  page_view: 'Opened page',
  analyze: 'Analyzed property',
  compare: 'Ran compare',
  pdf: 'Downloaded PDF',
  share: 'Created share link',
  bookmark: 'Saved property',
  assumption_change: 'Moved assumption sliders',
  sign_out: 'Signed out',
}

function formatWhen(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function extra(event: PreviewEvent): string {
  const payload = event.payload || {}
  const address = payload.address || payload.addresses
  if (Array.isArray(address)) return address.filter(Boolean).join(', ')
  if (typeof address === 'string') return address
  if (event.path) return event.path
  return ''
}

export function ActivityPage() {
  const [events, setEvents] = useState<PreviewEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const res = await apiFetch<{ events: PreviewEvent[]; count: number }>(
        '/api/preview/activity?username=salifT&limit=200',
      )
      setEvents(res.events || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load activity')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    document.title = 'Preview activity · CapEigen'
    void load()
  }, [])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold">salifT activity</h1>
          <p className="mt-1 text-muted">
            Pages, searches, compares, PDFs, and slider changes from the preview login.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
        >
          Refresh
        </button>
      </header>

      {busy && <p className="text-muted">Loading activity…</p>}
      {error && <p className="text-red-600">{error}</p>}

      {!busy && !error && (
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id || `${event.created_at}-${event.event_type}`} className="border-t border-border">
                  <td className="whitespace-nowrap px-3 py-2 text-muted">
                    {formatWhen(event.created_at)}
                  </td>
                  <td className="px-3 py-2 font-medium">
                    {LABELS[event.event_type || ''] || event.event_type}
                  </td>
                  <td className="px-3 py-2">{event.label || extra(event) || '—'}</td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-6 text-center text-muted">
                    No activity yet. After salifT logs in, actions appear here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
