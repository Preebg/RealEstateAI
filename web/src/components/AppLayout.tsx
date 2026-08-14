import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Map, Search, GitCompare, FlaskConical, LogOut, Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAuthStore } from '../lib/authStore'
import { apiFetch } from '../lib/api'
import { trackPreviewEvent } from '../lib/previewActivity'
import { clsx } from 'clsx'

const nav = [
  { to: '/', label: 'Home', icon: Map, end: true },
  { to: '/search', label: 'Individual Search', icon: Search },
  { to: '/compare', label: 'Compare', icon: GitCompare },
  { to: '/validation', label: 'Model Validation', icon: FlaskConical },
]

export function AppLayout() {
  const { user, signOut } = useAuthStore()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)

  useEffect(() => {
    void apiFetch<{ is_admin?: boolean }>('/api/me')
      .then((me) => setIsAdmin(Boolean(me.is_admin)))
      .catch(() => setIsAdmin(false))
  }, [user?.id])

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <aside
        className={clsx(
          'border-r border-border bg-white/80 backdrop-blur-sm lg:sticky lg:top-0 lg:h-screen',
          open ? 'block' : 'hidden lg:block',
        )}
      >
        <div className="flex h-full flex-col p-5">
          <div className="mb-8">
            <p className="font-display text-2xl font-semibold text-primary">CapEigen</p>
            <p className="mt-1 text-sm text-muted">AI rental underwriting</p>
          </div>
          <nav className="flex flex-1 flex-col gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-text/80 hover:bg-surface',
                  )
                }
              >
                <Icon size={18} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-6 border-t border-border pt-4">
            <p className="truncate text-xs text-muted">
              {(typeof user?.app_metadata?.username === 'string' && user.app_metadata.username) ||
                (typeof user?.user_metadata?.username === 'string' && user.user_metadata.username) ||
                user?.email}
            </p>
            <button
              type="button"
              className="mt-3 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-text/80 hover:bg-surface"
              onClick={async () => {
                trackPreviewEvent('sign_out', { path: '/login', label: 'Signed out' })
                await signOut()
                navigate('/login')
              }}
            >
              <LogOut size={16} />
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header
          className={clsx(
            'sticky top-0 z-20 flex items-center justify-between border-b border-border bg-bg/90 px-4 py-3 backdrop-blur',
            !isAdmin && 'lg:hidden',
          )}
        >
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded-lg border border-border p-2 lg:hidden"
              onClick={() => setOpen((v) => !v)}
              aria-label="Toggle menu"
            >
              {open ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span className="font-display text-lg font-semibold text-primary lg:hidden">
              CapEigen
            </span>
          </div>
          {isAdmin && (
            <NavLink
              to="/activity"
              className={({ isActive }) =>
                clsx(
                  'rounded-lg border px-3 py-1.5 text-sm font-medium',
                  isActive
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-white/80 text-text hover:bg-surface',
                )
              }
            >
              Preview
            </NavLink>
          )}
        </header>
        <main className="px-4 py-6 sm:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
