import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Map, Search, GitCompare, FlaskConical, Users, BarChart3, ScrollText, LogOut, Menu, X } from 'lucide-react'
import { useAuthStore } from '../lib/authStore'
import { isAdminUser } from '../lib/admin'
import { trackPreviewEvent } from '../lib/previewActivity'
import { consumeOpenAccountSettings } from '../lib/googleOAuth'
import { PropertyOfTheDayModal } from './PropertyOfTheDayModal'
import { LegalAcceptanceModal } from './LegalAcceptanceModal'
import { AccountSettingsModal } from './AccountSettingsModal'
import { ThemeToggle } from './ThemeToggle'
import { clsx } from 'clsx'

const nav: Array<{
  to: string
  label: string
  icon: typeof Map
  end?: boolean
}> = [
  { to: '/', label: 'Home', icon: Map, end: true },
  { to: '/search', label: 'Individual Search', icon: Search },
  { to: '/compare', label: 'Compare', icon: GitCompare },
]

const adminNav: typeof nav = [
  { to: '/activity', label: 'Demo accounts', icon: Users },
  { to: '/usage', label: 'Site usage', icon: BarChart3 },
  { to: '/legal-admin', label: 'Legal', icon: ScrollText },
  { to: '/validation', label: 'Model Validation', icon: FlaskConical },
]

export function AppLayout() {
  const { user, signOut } = useAuthStore()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const isAdmin = isAdminUser(user)
  const navItems = isAdmin ? [...nav, ...adminNav] : nav
  const displayName =
    (typeof user?.app_metadata?.username === 'string' && user.app_metadata.username) ||
    (typeof user?.user_metadata?.username === 'string' && user.user_metadata.username) ||
    user?.email ||
    'Account'

  useEffect(() => {
    if (consumeOpenAccountSettings()) {
      setSettingsOpen(true)
    }
  }, [])

  useEffect(() => {
    if (!accountMenuOpen) return
    function onPointerDown(event: MouseEvent) {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false)
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setAccountMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [accountMenuOpen])

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <aside
        className={clsx(
          'border-r border-border bg-card/80 backdrop-blur-sm lg:sticky lg:top-0 lg:h-screen',
          open ? 'block' : 'hidden lg:block',
        )}
      >
        <div className="flex h-full flex-col p-5">
          <div className="mb-8">
            <p className="font-display text-2xl font-semibold text-primary">CapEigen</p>
            <p className="mt-1 text-sm text-muted">AI rental underwriting</p>
          </div>
          <nav className="flex flex-1 flex-col gap-1">
            {navItems.map(({ to, label, icon: Icon, end }) => (
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
            <div className="relative" ref={accountMenuRef}>
              <button
                type="button"
                className="w-full truncate rounded-lg px-2 py-1.5 text-left text-xs text-muted hover:bg-surface hover:text-text"
                aria-haspopup="menu"
                aria-expanded={accountMenuOpen}
                onClick={() => setAccountMenuOpen((v) => !v)}
              >
                {displayName}
              </button>
              {accountMenuOpen && (
                <div
                  role="menu"
                  className="absolute bottom-full left-0 z-30 mb-2 w-full min-w-[12rem] rounded-xl border border-border bg-card p-1.5 shadow-lg"
                >
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-text hover:bg-surface"
                    onClick={() => {
                      setAccountMenuOpen(false)
                      setSettingsOpen(true)
                    }}
                  >
                    Account settings
                  </button>
                </div>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <ThemeToggle />
              <button
                type="button"
                className="flex flex-1 items-center gap-2 rounded-lg px-3 py-2 text-sm text-text/80 hover:bg-surface"
                onClick={async () => {
                  trackPreviewEvent('sign_out', { path: '/login', label: 'Signed out' })
                  await signOut()
                  navigate('/')
                }}
              >
                <LogOut size={16} />
                Sign out
              </button>
            </div>
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
          <div className="flex items-center gap-2">
            <div className="lg:hidden">
              <ThemeToggle />
            </div>
            {isAdmin && (
              <NavLink
                to="/usage"
                className={({ isActive }) =>
                  clsx(
                    'rounded-lg border px-3 py-1.5 text-sm font-medium',
                    isActive
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-card/80 text-text hover:bg-surface',
                  )
                }
              >
                Usage
              </NavLink>
            )}
          </div>
        </header>
        <main className="px-4 py-6 sm:px-8">
          <Outlet />
        </main>
        <LegalAcceptanceModal />
        <PropertyOfTheDayModal />
        <AccountSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </div>
  )
}
