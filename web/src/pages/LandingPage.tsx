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
} from 'lucide-react'
import { clsx } from 'clsx'
import { signInWithPreviewUsername } from '../lib/demoLogin'
import { prefetchHome, prefetchHomeChunk } from '../lib/prefetchHome'

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

function DashboardMockup() {
  return (
    <div
      className="relative w-full overflow-hidden rounded-t-2xl border border-white/10 bg-[#0c1020] shadow-[0_-20px_80px_rgba(15,23,42,0.35)]"
      aria-hidden
    >
      <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
        <span className="size-2.5 rounded-full bg-rose-400/80" />
        <span className="size-2.5 rounded-full bg-amber-400/80" />
        <span className="size-2.5 rounded-full bg-emerald-400/80" />
        <span className="ml-3 font-display text-xs tracking-wide text-white/45">
          CapEigen · Portfolio
        </span>
      </div>
      <div className="grid gap-4 p-4 sm:grid-cols-[1fr_1.15fr] sm:p-5">
        <div className="space-y-3">
          <div className="rounded-xl border border-white/8 bg-white/[0.04] p-4">
            <p className="text-[11px] uppercase tracking-[0.14em] text-white/40">Cash flow</p>
            <p className="mt-1 font-display text-2xl font-semibold text-white">+$1,842</p>
            <p className="mt-1 text-xs text-emerald-400/90">+6.2% vs last month</p>
            <div className="mt-4 flex h-16 items-end gap-1.5">
              {[40, 55, 48, 62, 58, 72, 68, 80, 76, 88, 84, 95].map((h, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-sm bg-gradient-to-t from-indigo-500/30 to-indigo-400/80"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Avg. CoC', value: '8.4%' },
              { label: 'QAOA fit', value: '91%' },
            ].map((stat) => (
              <div
                key={stat.label}
                className="rounded-xl border border-white/8 bg-white/[0.04] p-3"
              >
                <p className="text-[11px] text-white/40">{stat.label}</p>
                <p className="mt-1 font-display text-lg font-semibold text-white">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="relative min-h-[200px] overflow-hidden rounded-xl border border-white/8 bg-gradient-to-br from-slate-800/80 to-slate-950">
          <div
            className="absolute inset-0 opacity-40"
            style={{
              backgroundImage:
                'linear-gradient(rgba(99,102,241,0.25) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.25) 1px, transparent 1px)',
              backgroundSize: '28px 28px',
            }}
          />
          <div className="absolute left-[18%] top-[28%] size-3 rounded-full bg-indigo-400 shadow-[0_0_20px_rgba(129,140,248,0.8)]" />
          <div className="absolute left-[42%] top-[48%] size-2.5 rounded-full bg-emerald-400/90" />
          <div className="absolute left-[62%] top-[36%] size-2.5 rounded-full bg-sky-400/90" />
          <div className="absolute left-[74%] top-[58%] size-2 rounded-full bg-amber-400/80" />
          <div className="absolute bottom-3 left-3 right-3 rounded-lg border border-white/10 bg-[#0c1020]/90 p-3 backdrop-blur">
            <p className="text-xs font-medium text-white/90">214 Oak Ridge · Austin, TX</p>
            <p className="mt-1 text-[11px] text-white/50">Cap rate 5.8% · Risk score 87%</p>
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
        'rounded-2xl border border-border bg-white p-5 shadow-sm',
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
          <button
            type="button"
            className="rounded-lg p-2 text-text/80 hover:bg-surface md:hidden"
            aria-label={navOpen ? 'Close menu' : 'Open menu'}
            onClick={() => setNavOpen((o) => !o)}
          >
            {navOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
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
                  className="inline-flex items-center rounded-lg border border-border bg-white/80 px-5 py-3 text-sm font-semibold text-text transition hover:bg-surface"
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
                className="group rounded-2xl border border-transparent bg-transparent p-1 transition hover:border-border hover:bg-white/70"
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
          className="border-y border-border/70 bg-white/50 py-20 sm:py-28"
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
                  whileHover={reduce ? undefined : { scale: 1.01 }}
                  className={clsx(
                    'group relative overflow-hidden rounded-2xl border border-border bg-white transition',
                    'hover:border-primary/25 hover:shadow-[0_12px_40px_rgba(26,26,46,0.06)]',
                  )}
                >
                  <div
                    className={clsx(
                      'pointer-events-none absolute inset-0 bg-gradient-to-r opacity-80',
                      accent,
                    )}
                  />
                  <div className="relative flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:gap-8 sm:p-8">
                    <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-white text-primary shadow-sm ring-1 ring-border">
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
                    <ArrowRight
                      className="hidden size-5 shrink-0 text-primary/40 transition group-hover:translate-x-1 group-hover:text-primary sm:block"
                      aria-hidden
                    />
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
                  className="inline-flex items-center rounded-lg border border-border bg-white px-5 py-3 text-sm font-semibold transition hover:bg-surface"
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

      <footer className="border-t border-border bg-white/60">
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
        <div className="border-t border-border/70 py-4 text-center text-xs text-muted">
          © {new Date().getFullYear()} CapEigen. All rights reserved.
        </div>
      </footer>
    </div>
  )
}
