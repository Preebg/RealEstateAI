import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  motion,
  useReducedMotion,
  type Variants,
} from 'framer-motion'
import {
  BarChart3,
  ShieldCheck,
  Crosshair,
  Map,
  GitCompare,
  Sparkles,
  ArrowRight,
  Menu,
  X,
  LineChart,
  Building2,
  Search,
} from 'lucide-react'
import { clsx } from 'clsx'
import { signInWithPreviewUsername } from '../lib/demoLogin'
import { prefetchHome, prefetchHomeChunk } from '../lib/prefetchHome'
import { ThemeToggle } from '../components/ThemeToggle'

const WHY = [
  {
    icon: BarChart3,
    title: 'Automated analytics',
    body: 'Rent comps, NOI, cash-on-cash, and 10-year forecasts—assembled the moment you look at an address.',
  },
  {
    icon: ShieldCheck,
    title: 'Risk mitigation',
    body: 'QAOA portfolio alignment surfaces cash-flow and appreciation risk together, not as isolated guesses.',
  },
  {
    icon: Crosshair,
    title: 'Streamlined deal sourcing',
    body: 'Filter metro inventory by yield, cash flow, and fit so you spend time on deals that clear your bar.',
  },
] as const

const FEATURES = [
  {
    id: 'underwrite',
    icon: Building2,
    title: 'AI rental underwriting',
    body: 'Agentic research pulls rent evidence and classical finance math into one clear underwriting brief.',
    accent: 'from-primary/20 via-primary/5 to-transparent',
  },
  {
    id: 'portfolio',
    icon: Map,
    title: 'Portfolio map & filters',
    body: 'See holdings and prospects on a live map, then tighten the list with cash-flow and yield ranges.',
    accent: 'from-sky-500/15 via-sky-500/5 to-transparent',
  },
  {
    id: 'compare',
    icon: GitCompare,
    title: 'Side-by-side compare',
    body: 'Stack listings on the metrics that matter—price, yield, cash flow—before you write an offer.',
    accent: 'from-emerald-500/15 via-emerald-500/5 to-transparent',
  },
  {
    id: 'quantum',
    icon: Sparkles,
    title: 'QAOA alignment',
    body: 'A quantum-inspired risk score ranks how well a deal fits your cash-flow and appreciation thesis.',
    accent: 'from-amber-500/15 via-amber-500/5 to-transparent',
  },
] as const

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 28 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
  },
}

const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1, delayChildren: 0.06 } },
}

function SectionReveal({
  children,
  className,
  id,
}: {
  children: ReactNode
  className?: string
  id?: string
}) {
  const reduce = useReducedMotion()
  return (
    <motion.section
      id={id}
      className={className}
      initial={reduce ? false : 'hidden'}
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      variants={stagger}
    >
      {children}
    </motion.section>
  )
}

const MOCK_PROPERTIES = [
  {
    address: '214 Oak Ridge Dr, Austin, TX',
    price: '$425,000',
    rent: '$2,450',
    yield: '5.8%',
    cashFlow: '+$312',
    coc: '7.2%',
  },
  {
    address: '88 Maple Ave, Columbus, OH',
    price: '$198,500',
    rent: '$1,375',
    yield: '6.9%',
    cashFlow: '+$241',
    coc: '9.1%',
  },
  {
    address: '1201 Pine St, Raleigh, NC',
    price: '$356,000',
    rent: '$2,100',
    yield: '5.4%',
    cashFlow: '+$188',
    coc: '6.4%',
  },
] as const

function DashboardMockup() {
  return (
    <div
      className="relative w-full overflow-hidden rounded-t-2xl border border-border bg-bg shadow-[0_-16px_60px_rgba(26,26,46,0.1)]"
      aria-hidden
    >
      <div className="flex min-h-[320px] sm:min-h-[380px]">
        {/* Sidebar — mirrors AppLayout */}
        <aside className="hidden w-[200px] shrink-0 border-r border-border bg-card/80 p-4 sm:block">
          <p className="font-display text-lg font-semibold text-primary">CapEigen</p>
          <p className="mt-0.5 text-[11px] text-muted">AI rental underwriting</p>
          <nav className="mt-6 space-y-1">
            {[
              { label: 'Home', active: true, Icon: Map },
              { label: 'Individual Search', active: false, Icon: Search },
              { label: 'Compare', active: false, Icon: GitCompare },
            ].map(({ label, active, Icon }) => (
              <div
                key={label}
                className={clsx(
                  'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs font-medium',
                  active ? 'bg-primary/10 text-primary' : 'text-text/70',
                )}
              >
                <Icon className="size-3.5 shrink-0" />
                {label}
              </div>
            ))}
          </nav>
        </aside>

        {/* Main — mirrors Portfolio map home */}
        <div className="min-w-0 flex-1 space-y-3 p-3 sm:p-4">
          <div>
            <p className="font-display text-lg font-semibold sm:text-xl">Portfolio map</p>
            <p className="mt-0.5 text-[11px] text-muted sm:text-xs">
              Browse researched properties. Click a pin to open Individual Search.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-lg border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-text/80">
              Filters
            </span>
            <span className="text-[11px] text-muted">Showing 3 of 3 properties</span>
          </div>

          <div className="relative h-[140px] overflow-hidden rounded-2xl border border-border shadow-sm sm:h-[160px]">
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(160deg, #dce8d4 0%, #c5d9c0 35%, #b8cfc8 60%, #d4e0ea 100%)',
              }}
            />
            <div
              className="absolute inset-0 opacity-30"
              style={{
                backgroundImage:
                  'linear-gradient(rgba(26,26,46,0.12) 1px, transparent 1px), linear-gradient(90deg, rgba(26,26,46,0.12) 1px, transparent 1px)',
                backgroundSize: '24px 24px',
              }}
            />
            {/* Leaflet-style pins */}
            <div className="absolute left-[22%] top-[38%] flex flex-col items-center">
              <span className="size-3 rounded-full border-2 border-white bg-[#2a81cb] shadow" />
              <span className="-mt-0.5 h-2 w-px bg-[#2a81cb]/80" />
            </div>
            <div className="absolute left-[48%] top-[52%] flex flex-col items-center">
              <span className="size-3 rounded-full border-2 border-white bg-[#2a81cb] shadow" />
              <span className="-mt-0.5 h-2 w-px bg-[#2a81cb]/80" />
            </div>
            <div className="absolute left-[68%] top-[30%] flex flex-col items-center">
              <span className="size-3 rounded-full border-2 border-white bg-[#2a81cb] shadow" />
              <span className="-mt-0.5 h-2 w-px bg-[#2a81cb]/80" />
            </div>
            <div className="absolute bottom-2 left-2 rounded bg-card/90 px-1.5 py-0.5 text-[9px] text-muted shadow-sm">
              © OSM
            </div>
          </div>

          <div>
            <p className="mb-2 font-display text-sm font-semibold">Properties (3)</p>
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <table className="w-full text-left text-[10px] sm:text-xs">
                <thead className="bg-surface text-muted">
                  <tr>
                    <th className="px-2 py-1.5 font-medium sm:px-3">Address</th>
                    <th className="hidden px-2 py-1.5 font-medium sm:table-cell sm:px-3">Price</th>
                    <th className="px-2 py-1.5 font-medium sm:px-3">Rent</th>
                    <th className="px-2 py-1.5 font-medium sm:px-3">Yield</th>
                    <th className="hidden px-2 py-1.5 font-medium md:table-cell md:px-3">
                      Cash flow
                    </th>
                    <th className="hidden px-2 py-1.5 font-medium lg:table-cell lg:px-3">
                      Cash on cash
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {MOCK_PROPERTIES.map((p) => (
                    <tr key={p.address} className="border-t border-border">
                      <td className="max-w-[9rem] truncate px-2 py-1.5 text-primary sm:max-w-none sm:px-3">
                        {p.address}
                      </td>
                      <td className="hidden px-2 py-1.5 sm:table-cell sm:px-3">{p.price}</td>
                      <td className="px-2 py-1.5 sm:px-3">{p.rent}</td>
                      <td className="px-2 py-1.5 sm:px-3">{p.yield}</td>
                      <td className="hidden px-2 py-1.5 md:table-cell md:px-3">{p.cashFlow}</td>
                      <td className="hidden px-2 py-1.5 lg:table-cell lg:px-3">{p.coc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function DemoLoginForm({ className }: { className?: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (!accepted) throw new Error('Accept the Terms and Privacy Policy to continue.')
      prefetchHomeChunk()
      await signInWithPreviewUsername(username)
      prefetchHome(queryClient)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      className={clsx(
        'rounded-2xl border border-border bg-card p-5 shadow-sm',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <LineChart className="size-4 text-primary" aria-hidden />
        <h3 className="font-display text-base font-semibold text-text">Demo access</h3>
      </div>
      <p className="mt-2 text-sm text-muted">Enter your username. No password required.</p>
      <label className="mt-4 block text-sm">
        Username
        <input
          type="text"
          autoComplete="username"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="mt-1 w-full rounded-lg border border-border px-3 py-2.5 outline-none transition focus:border-primary"
          placeholder="your-demo-name"
        />
      </label>
      <label className="mt-3 flex items-start gap-2 text-sm text-muted">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
          className="mt-1"
        />
        <span>
          I agree to the{' '}
          <Link className="text-primary underline" to="/legal/terms">
            Terms
          </Link>{' '}
          and{' '}
          <Link className="text-primary underline" to="/legal/privacy">
            Privacy Policy
          </Link>
          .
        </span>
      </label>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={busy || !accepted || username.trim().length < 2}
        className="mt-4 w-full rounded-lg bg-primary py-2.5 text-sm font-semibold text-white transition hover:bg-primary-hover disabled:opacity-60"
      >
        {busy ? 'Signing in…' : 'Continue with username'}
      </button>
    </form>
  )
}

export function LandingPage() {
  const reduce = useReducedMotion()
  const [navOpen, setNavOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    document.title = 'CapEigen · AI rental underwriting'
  }, [])

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const motionOff = reduce ? false : undefined

  return (
    <div className="min-h-screen overflow-x-hidden bg-bg text-text">
      <header
        className={clsx(
          'fixed inset-x-0 top-0 z-40 transition-all duration-300',
          scrolled
            ? 'border-b border-border/80 bg-bg/90 shadow-sm backdrop-blur-md'
            : 'bg-transparent',
        )}
      >
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <a href="#top" className="font-display text-xl font-semibold tracking-tight text-primary">
            CapEigen
          </a>
          <nav className="hidden items-center gap-8 md:flex">
            <a href="#features" className="text-sm font-medium text-text/75 transition hover:text-primary">
              Features
            </a>
            <a href="#why" className="text-sm font-medium text-text/75 transition hover:text-primary">
              Why CapEigen
            </a>
          </nav>
          <div className="hidden items-center gap-3 md:flex">
            <ThemeToggle />
            <Link
              to="/login"
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-text/80 transition hover:bg-surface hover:text-text"
            >
              Log In
            </Link>
            <a
              href="#get-started"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary-hover"
            >
              Get Started
            </a>
          </div>
          <div className="flex items-center gap-2 md:hidden">
            <ThemeToggle />
            <button
              type="button"
              className="rounded-lg p-2 text-text/80 hover:bg-surface"
              aria-label={navOpen ? 'Close menu' : 'Open menu'}
              onClick={() => setNavOpen((o) => !o)}
            >
              {navOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>
        {navOpen && (
          <div className="border-t border-border bg-bg/95 px-4 py-4 backdrop-blur-md md:hidden">
            <div className="flex flex-col gap-3">
              <a
                href="#features"
                className="rounded-lg px-3 py-2 text-sm font-medium hover:bg-surface"
                onClick={() => setNavOpen(false)}
              >
                Features
              </a>
              <a
                href="#why"
                className="rounded-lg px-3 py-2 text-sm font-medium hover:bg-surface"
                onClick={() => setNavOpen(false)}
              >
                Why CapEigen
              </a>
              <Link
                to="/login"
                className="rounded-lg px-3 py-2 text-sm font-medium hover:bg-surface"
                onClick={() => setNavOpen(false)}
              >
                Log In
              </Link>
              <a
                href="#get-started"
                className="rounded-lg bg-primary px-3 py-2.5 text-center text-sm font-semibold text-white"
                onClick={() => setNavOpen(false)}
              >
                Get Started
              </a>
            </div>
          </div>
        )}
      </header>

      <main id="top">
        {/* Hero — brand, one headline, subtitle, CTAs, full-bleed mockup */}
        <section className="relative pt-16">
          <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
            <div className="absolute -left-1/4 top-0 h-[70vh] w-[70vw] rounded-full bg-primary/[0.07] blur-3xl" />
            <div className="absolute -right-1/4 top-24 h-[50vh] w-[50vw] rounded-full bg-sky-400/[0.06] blur-3xl" />
          </div>

          <div className="mx-auto max-w-6xl px-4 pb-8 pt-14 sm:px-6 sm:pt-20 lg:pt-24">
            <motion.div
              initial={motionOff ?? { opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              className="mx-auto max-w-3xl text-center"
            >
              <p className="font-display text-4xl font-semibold tracking-tight text-primary sm:text-5xl lg:text-6xl">
                CapEigen
              </p>
              <h1 className="mt-5 font-display text-2xl font-semibold leading-snug tracking-tight text-text sm:text-3xl lg:text-[2.15rem] lg:leading-snug">
                Financial clarity for every real estate decision
              </h1>
              <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted sm:text-lg">
                AI underwriting and quantum-aligned portfolio risk so investors underwrite faster
                and with fewer blind spots.
              </p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <a
                  href="#get-started"
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-white transition hover:bg-primary-hover"
                >
                  Get Started
                  <ArrowRight className="size-4" aria-hidden />
                </a>
                <Link
                  to="/login"
                  className="inline-flex items-center rounded-lg border border-border bg-card/80 px-5 py-3 text-sm font-semibold text-text transition hover:bg-surface"
                >
                  Log In
                </Link>
              </div>
            </motion.div>
          </div>

          <motion.div
            initial={motionOff ?? { opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.75, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="mx-auto max-w-5xl px-4 sm:px-6"
          >
            <DashboardMockup />
          </motion.div>
        </section>

        {/* Why CapEigen */}
        <SectionReveal id="why" className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
          <motion.div variants={fadeUp} className="mx-auto max-w-2xl text-center">
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
              Why CapEigen
            </h2>
            <p className="mt-3 text-muted">
              Built for investors who need clear numbers—not another spreadsheet of assumptions.
            </p>
          </motion.div>
          <div className="mt-14 grid gap-6 sm:grid-cols-3">
            {WHY.map(({ icon: Icon, title, body }) => (
              <motion.div
                key={title}
                variants={fadeUp}
                whileHover={reduce ? undefined : { y: -4 }}
                className="group rounded-2xl border border-transparent bg-transparent p-1 transition hover:border-border hover:bg-card/70"
              >
                <div className="p-5">
                  <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary transition group-hover:bg-primary group-hover:text-white">
                    <Icon className="size-5" aria-hidden />
                  </div>
                  <h3 className="mt-5 font-display text-lg font-semibold">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </SectionReveal>

        {/* Features */}
        <SectionReveal
          id="features"
          className="border-y border-border/70 bg-card/50 py-20 sm:py-28"
        >
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <motion.div variants={fadeUp} className="mx-auto max-w-2xl text-center">
              <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
                Core tools, revealed in context
              </h2>
              <p className="mt-3 text-muted">
                From a single address to a portfolio thesis—each step stays transparent and actionable.
              </p>
            </motion.div>
            <div className="mt-14 space-y-6">
              {FEATURES.map(({ id, icon: Icon, title, body, accent }, i) => (
                <motion.article
                  key={id}
                  variants={fadeUp}
                  className="relative overflow-hidden rounded-2xl border border-border bg-card"
                >
                  <div
                    className={clsx(
                      'pointer-events-none absolute inset-0 bg-gradient-to-r opacity-80',
                      accent,
                    )}
                  />
                  <div className="relative flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:gap-8 sm:p-8">
                    <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-card text-primary shadow-sm ring-1 ring-border">
                      <Icon className="size-5" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted">
                        {String(i + 1).padStart(2, '0')}
                      </p>
                      <h3 className="mt-1 font-display text-xl font-semibold">{title}</h3>
                      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted sm:text-base">
                        {body}
                      </p>
                    </div>
                  </div>
                </motion.article>
              ))}
            </div>
          </div>
        </SectionReveal>

        {/* Final CTA */}
        <SectionReveal id="get-started" className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
          <div className="grid items-start gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:gap-14">
            <motion.div variants={fadeUp}>
              <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
                Start underwriting with confidence
              </h2>
              <p className="mt-4 max-w-lg text-muted">
                Create an account for full access, or sign in with your demo username if you were
                invited to preview CapEigen.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  to="/login?mode=signup"
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-white transition hover:bg-primary-hover"
                >
                  Create account
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
                <Link
                  to="/login"
                  className="inline-flex items-center rounded-lg border border-border bg-card px-5 py-3 text-sm font-semibold transition hover:bg-surface"
                >
                  Log In
                </Link>
              </div>
            </motion.div>
            <motion.div variants={fadeUp}>
              <DemoLoginForm />
            </motion.div>
          </div>
        </SectionReveal>
      </main>

      <footer className="border-t border-border bg-card/60">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <p className="font-display text-lg font-semibold text-primary">CapEigen</p>
            <p className="mt-1 text-sm text-muted">
              AI rental underwriting with QAOA portfolio alignment.
            </p>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
            <a href="#features" className="hover:text-primary">
              Features
            </a>
            <a href="#why" className="hover:text-primary">
              Why CapEigen
            </a>
            <Link to="/legal/terms" className="hover:text-primary">
              Terms
            </Link>
            <Link to="/legal/privacy" className="hover:text-primary">
              Privacy
            </Link>
            <Link to="/login" className="hover:text-primary">
              Log In
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
