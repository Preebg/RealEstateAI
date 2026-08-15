import { useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../lib/api'

type Audience = 'all' | 'registered' | 'demo'

type UsageTotals = {
  events: number
  unique_users: number
  logins: number
  page_views: number
  analyzes: number
  compares: number
  pdfs: number
  shares: number
  bookmarks: number
}

type UsageAction = {
  event_type: string
  label: string
  events: number
  unique_users: number
}

type UsagePage = {
  path: string
  label: string
  events: number
  unique_users: number
}

type UsageUser = {
  username: string
  is_preview?: boolean
  event_count: number
  login_count: number
  page_view_count: number
  analyze_count: number
  compare_count: number
  pdf_count: number
  share_count?: number
  bookmark_count?: number
  last_seen?: string | null
}

type UsageEvent = {
  id?: string
  username?: string
  event_type?: string
  path?: string | null
  label?: string | null
  payload?: Record<string, unknown>
  created_at?: string
  is_preview?: boolean
}

type UsageSummary = {
  days: number
  audience: Audience
  totals: UsageTotals
  actions: UsageAction[]
  pages: UsagePage[]
  users: UsageUser[]
}

const ACTION_LABELS: Record<string, string> = {
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

function formatWhen(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function extra(event: UsageEvent): string {
  const payload = event.payload || {}
  const address = payload.address || payload.addresses
  if (Array.isArray(address)) return address.filter(Boolean).join(', ')
  if (typeof address === 'string') return address
  if (event.path) return event.path
  return ''
}

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

function downloadCsv(filename: string, rows: string[][]) {
  const text = rows.map((row) => row.map((cell) => csvEscape(cell)).join(',')).join('\n')
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function Bar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0
  return (
    <div className="h-2 w-full rounded-full bg-surface">
      <div className="h-2 rounded-full bg-primary" style={{ width: `${width}%` }} />
    </div>
  )
}

export function UsagePage() {
  const [days, setDays] = useState(90)
  const [audience, setAudience] = useState<Audience>('all')
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [events, setEvents] = useState<UsageEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)

  async function load(nextDays = days, nextAudience = audience) {
    setBusy(true)
    setError(null)
    try {
      const [summaryRes, eventRes] = await Promise.all([
        apiFetch<UsageSummary>(
          `/api/usage/summary?days=${nextDays}&audience=${encodeURIComponent(nextAudience)}`,
        ),
        apiFetch<{ events: UsageEvent[] }>(
          `/api/usage/activity?limit=200&audience=${encodeURIComponent(nextAudience)}`,
        ),
      ])
      setSummary(summaryRes)
      setEvents(eventRes.events || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load usage data')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    document.title = 'Site usage · CapEigen'
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const maxAction = useMemo(
    () => Math.max(0, ...(summary?.actions.map((item) => item.events) || [0])),
    [summary],
  )
  const maxPage = useMemo(
    () => Math.max(0, ...(summary?.pages.map((item) => item.events) || [0])),
    [summary],
  )

  function exportData() {
    if (!summary) return
    const rows: string[][] = [
      ['section', 'name', 'events', 'unique_users'],
      ...summary.actions.map((item) => [
        'action',
        item.label,
        String(item.events),
        String(item.unique_users),
      ]),
      ...summary.pages.map((item) => [
        'page',
        `${item.label} (${item.path})`,
        String(item.events),
        String(item.unique_users),
      ]),
      ...summary.users.map((item) => [
        'user',
        item.username,
        String(item.event_count),
        item.is_preview ? 'demo' : 'registered',
      ]),
    ]
    downloadCsv(`capeigen-usage-${audience}-${days}d.csv`, rows)
  }

  const totals = summary?.totals

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold">Site usage</h1>
          <p className="mt-1 text-muted">
            What signed-in people actually use — pages, analyses, compares, PDFs, and more.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={audience}
            onChange={(e) => {
              const next = e.target.value as Audience
              setAudience(next)
              void load(days, next)
            }}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-sm"
          >
            <option value="all">All accounts</option>
            <option value="registered">Registered only</option>
            <option value="demo">Demo only</option>
          </select>
          <select
            value={days}
            onChange={(e) => {
              const next = Number(e.target.value)
              setDays(next)
              void load(next, audience)
            }}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-sm"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last year</option>
          </select>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={exportData}
            disabled={!summary}
            className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            Download CSV
          </button>
        </div>
      </header>

      {error && <p className="text-red-600">{error}</p>}
      {busy && <p className="text-muted">Loading usage…</p>}

      {totals && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Unique users', totals.unique_users],
            ['Events', totals.events],
            ['Property analyses', totals.analyzes],
            ['Compares', totals.compares],
            ['Page views', totals.page_views],
            ['PDF downloads', totals.pdfs],
            ['Share links', totals.shares],
            ['Saved properties', totals.bookmarks],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-2xl border border-border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
              <p className="mt-1 font-display text-2xl font-semibold">{value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-border bg-white p-4 shadow-sm">
          <h2 className="font-display text-xl font-semibold">Most used actions</h2>
          <div className="mt-3 space-y-3">
            {(summary?.actions || []).map((item) => (
              <div key={item.event_type}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-medium">{item.label}</span>
                  <span className="text-muted">
                    {item.events} · {item.unique_users} user{item.unique_users === 1 ? '' : 's'}
                  </span>
                </div>
                <Bar value={item.events} max={maxAction} />
              </div>
            ))}
            {summary && summary.actions.length === 0 && (
              <p className="text-sm text-muted">No actions recorded in this window yet.</p>
            )}
          </div>
        </section>

        <section className="rounded-2xl border border-border bg-white p-4 shadow-sm">
          <h2 className="font-display text-xl font-semibold">Most opened pages</h2>
          <div className="mt-3 space-y-3">
            {(summary?.pages || []).map((item) => (
              <div key={`${item.path}-${item.label}`}>
                <div className="mb-1 flex justify-between gap-3 text-sm">
                  <span className="font-medium">{item.label}</span>
                  <span className="shrink-0 text-muted">{item.events}</span>
                </div>
                <Bar value={item.events} max={maxPage} />
                <p className="mt-0.5 text-xs text-muted">{item.path}</p>
              </div>
            ))}
            {summary && summary.pages.length === 0 && (
              <p className="text-sm text-muted">No page views recorded in this window yet.</p>
            )}
          </div>
        </section>
      </div>

      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">People</h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
                <th className="px-3 py-2 font-medium">Pages</th>
                <th className="px-3 py-2 font-medium">Analyzes</th>
                <th className="px-3 py-2 font-medium">Compares</th>
                <th className="px-3 py-2 font-medium">PDFs</th>
                <th className="px-3 py-2 font-medium">Events</th>
              </tr>
            </thead>
            <tbody>
              {(summary?.users || []).map((user) => (
                <tr key={user.username} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{user.username}</td>
                  <td className="px-3 py-2 text-muted">{user.is_preview ? 'Demo' : 'Registered'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted">
                    {formatWhen(user.last_seen)}
                  </td>
                  <td className="px-3 py-2">{user.page_view_count}</td>
                  <td className="px-3 py-2">{user.analyze_count}</td>
                  <td className="px-3 py-2">{user.compare_count}</td>
                  <td className="px-3 py-2">{user.pdf_count}</td>
                  <td className="px-3 py-2">{user.event_count}</td>
                </tr>
              ))}
              {summary && summary.users.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-muted">
                    No usage yet. After people sign in and use the app, totals appear here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Recent activity</h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr
                  key={event.id || `${event.created_at}-${event.event_type}`}
                  className="border-t border-border"
                >
                  <td className="whitespace-nowrap px-3 py-2 text-muted">
                    {formatWhen(event.created_at)}
                  </td>
                  <td className="px-3 py-2 font-medium">
                    {event.username || '—'}
                    {event.is_preview ? (
                      <span className="ml-2 text-xs font-normal text-muted">demo</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 font-medium">
                    {ACTION_LABELS[event.event_type || ''] || event.event_type}
                  </td>
                  <td className="px-3 py-2">{event.label || extra(event) || '—'}</td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-muted">
                    No recent activity in this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
