import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { clsx } from 'clsx'
import { apiFetch } from '../lib/api'
import { ThemeToggle } from '../components/ThemeToggle'
import { LegalDocumentPreview } from '../components/LegalMarkdown'

type LegalDocument = {
  title: string
  body: string
  effective_date?: string
}

const FALLBACK: Record<string, LegalDocument> = {
  terms: {
    title: 'Terms of Service',
    body: 'Terms of Service could not be loaded. Please try again shortly.',
  },
  privacy: {
    title: 'Privacy Policy',
    body: 'Privacy Policy could not be loaded. Please try again shortly.',
  },
}

export function LegalPage() {
  const { doc } = useParams()
  const slug = doc === 'privacy' ? 'privacy' : 'terms'
  const [legalDoc, setLegalDoc] = useState<LegalDocument | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await apiFetch<LegalDocument>(`/api/legal/${slug}`)
        if (!cancelled) {
          setLegalDoc(payload)
          window.document.title = `${payload.title} · CapEigen`
        }
      } catch (err) {
        if (!cancelled) {
          setLegalDoc(FALLBACK[slug])
          setError(err instanceof Error ? err.message : 'Could not load legal document')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [slug])

  const title = legalDoc?.title || (slug === 'privacy' ? 'Privacy Policy' : 'Terms of Service')

  return (
    <div className="min-h-screen overflow-x-hidden bg-bg text-text">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-bg/90 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="font-display text-xl font-semibold tracking-tight text-primary">
            CapEigen
          </Link>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link
              to="/login"
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-text/80 transition hover:bg-surface hover:text-text"
            >
              Log In
            </Link>
          </div>
        </div>
      </header>

      <main className="relative">
        <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
          <div className="absolute -left-1/4 top-0 h-[50vh] w-[70vw] rounded-full bg-primary/[0.07] blur-3xl" />
          <div className="absolute -right-1/4 top-16 h-[40vh] w-[50vw] rounded-full bg-sky-400/[0.06] blur-3xl" />
        </div>

        <div className="mx-auto max-w-3xl px-4 pb-20 pt-10 sm:px-6 sm:pt-14">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-muted transition hover:text-primary"
          >
            <ArrowLeft className="size-4" aria-hidden />
            Back to CapEigen
          </Link>

          <nav className="mt-8 flex gap-6 border-b border-border/80" aria-label="Legal documents">
            <Link
              to="/legal/terms"
              className={clsx(
                '-mb-px border-b-2 pb-3 text-sm font-medium transition',
                slug === 'terms'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted hover:text-text',
              )}
            >
              Terms of Service
            </Link>
            <Link
              to="/legal/privacy"
              className={clsx(
                '-mb-px border-b-2 pb-3 text-sm font-medium transition',
                slug === 'privacy'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted hover:text-text',
              )}
            >
              Privacy Policy
            </Link>
          </nav>

          {error && (
            <p className="mt-6 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-700 dark:text-red-300">
              {error}
            </p>
          )}

          {loading && !legalDoc ? (
            <p className="mt-10 text-sm text-muted">Loading…</p>
          ) : (
            <LegalDocumentPreview
              className="mt-10"
              title={title}
              effectiveDate={legalDoc?.effective_date}
              body={legalDoc?.body || ''}
            />
          )}
        </div>
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
            <Link to="/" className="hover:text-primary">
              Home
            </Link>
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
