import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
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

type PreviewAccount = {
  username: string
  active: boolean
  source: string
  created_at?: string | null
  created_by?: string | null
  last_seen?: string | null
  event_count: number
  login_count: number
  analyze_count: number
  compare_count: number
  pdf_count: number
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

function formatWhen(iso?: string | null) {
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

function sourceLabel(source: string) {
  if (source === 'dashboard') return 'Dashboard'
  if (source === 'environment') return 'Env fallback'
  return 'Past activity'
}

export function ActivityPage() {
  const [accounts, setAccounts] = useState<PreviewAccount[]>([])
  const [events, setEvents] = useState<PreviewEvent[]>([])
  const [filterUser, setFilterUser] = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)

  async function load(username?: string) {
    setBusy(true)
    setError(null)
    const query = username ? `?limit=200&username=${encodeURIComponent(username)}` : '?limit=200'
    try {
      const [accountRes, eventRes] = await Promise.all([
        apiFetch<{ accounts: PreviewAccount[]; count: number }>('/api/preview/accounts'),
        apiFetch<{ events: PreviewEvent[]; count: number }>(`/api/preview/activity${query}`),
      ])
      setAccounts(accountRes.accounts || [])
      setEvents(eventRes.events || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load demo dashboard')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    document.title = 'Demo accounts · CapEigen'
    void load()
  }, [])

  const activeCount = useMemo(
    () => accounts.filter((account) => account.active).length,
    [accounts],
  )

  async function onAdd(e: FormEvent) {
    e.preventDefault()
    const username = newUsername.trim()
    if (!username) return
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch<{ accounts: PreviewAccount[] }>('/api/preview/accounts', {
        method: 'POST',
        body: JSON.stringify({ username }),
      })
      setAccounts(res.accounts || [])
      setNewUsername('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add username')
    } finally {
      setSaving(false)
    }
  }

  async function onRemove(username: string) {
    if (
      !window.confirm(
        `Remove “${username}” from demo login? They will not be able to sign in with that name.`,
      )
    ) {
      return
    }
    setRemoving(username)
    setError(null)
    try {
      const res = await apiFetch<{ accounts: PreviewAccount[] }>(
        `/api/preview/accounts/${encodeURIComponent(username)}`,
        { method: 'DELETE' },
      )
      setAccounts(res.accounts || [])
      if (filterUser.toLowerCase() === username.toLowerCase()) {
        setFilterUser('')
        await load()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove username')
    } finally {
      setRemoving(null)
    }
  }

  async function onRestore(username: string) {
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch<{ accounts: PreviewAccount[] }>('/api/preview/accounts', {
        method: 'POST',
        body: JSON.stringify({ username }),
      })
      setAccounts(res.accounts || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not restore username')
    } finally {
      setSaving(false)
    }
  }

  async function onFilter(username: string) {
    const next = filterUser === username ? '' : username
    setFilterUser(next)
    await load(next || undefined)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold">Demo accounts</h1>
          <p className="mt-1 text-muted">
            Add or remove preview usernames and watch how they use CapEigen. Changes apply to
            login immediately — no .env or Netlify restart.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load(filterUser || undefined)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
        >
          Refresh
        </button>
      </header>

      <form
        onSubmit={(e) => void onAdd(e)}
        className="flex flex-wrap items-end gap-3 rounded-2xl border border-border bg-white p-4 shadow-sm"
      >
        <label className="min-w-[16rem] flex-1 text-sm">
          <span className="mb-1 block font-medium">Add preview username</span>
          <input
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            placeholder="letters, numbers, underscore"
            pattern="[A-Za-z0-9_]{2,32}"
            maxLength={32}
            required
            className="w-full rounded-lg border border-border px-3 py-2"
          />
        </label>
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Add username'}
        </button>
        <p className="w-full text-xs text-muted">
          {activeCount} active demo login{activeCount === 1 ? '' : 's'}. People sign in on the
          login page with this exact name — no password.
        </p>
      </form>

      {error && <p className="text-red-600">{error}</p>}
      {busy && <p className="text-muted">Loading demo dashboard…</p>}

      {!busy && (
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Username</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
                <th className="px-3 py-2 font-medium">Logins</th>
                <th className="px-3 py-2 font-medium">Analyzes</th>
                <th className="px-3 py-2 font-medium">Compares</th>
                <th className="px-3 py-2 font-medium">PDFs</th>
                <th className="px-3 py-2 font-medium">Events</th>
                <th className="px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.username} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{account.username}</td>
                  <td className="px-3 py-2">
                    <span className={account.active ? 'text-emerald-700' : 'text-muted'}>
                      {account.active ? 'Active' : 'Removed'}
                    </span>
                    <span className="ml-2 text-xs text-muted">{sourceLabel(account.source)}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted">
                    {formatWhen(account.last_seen)}
                  </td>
                  <td className="px-3 py-2">{account.login_count}</td>
                  <td className="px-3 py-2">{account.analyze_count}</td>
                  <td className="px-3 py-2">{account.compare_count}</td>
                  <td className="px-3 py-2">{account.pdf_count}</td>
                  <td className="px-3 py-2">{account.event_count}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void onFilter(account.username)}
                        className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-surface"
                      >
                        {filterUser === account.username ? 'Show all' : 'Activity'}
                      </button>
                      {account.active ? (
                        <button
                          type="button"
                          disabled={removing === account.username}
                          onClick={() => void onRemove(account.username)}
                          className="rounded-lg border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          {removing === account.username ? 'Removing…' : 'Remove'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => void onRestore(account.username)}
                          className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-surface disabled:opacity-60"
                        >
                          Restore
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {accounts.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-muted">
                    No demo usernames yet. Add one above to let someone sign in on the preview
                    login form.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">
          {filterUser ? `Activity · ${filterUser}` : 'Recent activity'}
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">User</th>
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
                  <td className="px-3 py-2 font-medium">{event.username || '—'}</td>
                  <td className="px-3 py-2 font-medium">
                    {LABELS[event.event_type || ''] || event.event_type}
                  </td>
                  <td className="px-3 py-2">{event.label || extra(event) || '—'}</td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-muted">
                    No activity yet. After a preview user logs in, actions appear here.
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
