import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { clsx } from 'clsx'
import { apiFetch } from '../lib/api'
import { ThemeToggle } from '../components/ThemeToggle'

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

function formatEffectiveDate(iso?: string) {
  if (!iso) return null
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /\*\*(.+?)\*\*/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index))
    }
    parts.push(
      <strong key={key++} className="font-semibold text-text">
        {match[1]}
      </strong>,
    )
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function stripDuplicateTitle(markdown: string, title: string): string {
  const trimmed = markdown.trim()
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return trimmed
    .replace(new RegExp(`^#{1,6}\\s*${escaped}\\s*\\n+`, 'i'), '')
    .replace(new RegExp(`^\\*\\*Effective date:\\*\\*[^\\n]*\\n+`, 'i'), '')
    .trim()
}

function LegalBody({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => {
    const lines = markdown.replace(/\r\n/g, '\n').split('\n')
    const nodes: ReactNode[] = []
    let i = 0
    let key = 0

    while (i < lines.length) {
      const line = lines[i]
      const trimmed = line.trim()

      if (!trimmed) {
        i += 1
        continue
      }

      if (trimmed === '---') {
        nodes.push(<hr key={key++} className="my-8 border-border" />)
        i += 1
        continue
      }

      const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed)
      if (heading) {
        const level = heading[1].length
        const content = renderInline(heading[2].trim())
        if (level <= 3) {
          nodes.push(
            <h2
              key={key++}
              className="mt-10 font-display text-xl font-semibold tracking-tight text-text first:mt-0"
            >
              {content}
            </h2>,
          )
        } else {
          nodes.push(
            <h3
              key={key++}
              className="mt-8 font-display text-base font-semibold tracking-tight text-text first:mt-0"
            >
              {content}
            </h3>,
          )
        }
        i += 1
        continue
      }

      if (trimmed.startsWith('- ')) {
        const items: string[] = []
        while (i < lines.length && lines[i].trim().startsWith('- ')) {
          items.push(lines[i].trim().slice(2))
          i += 1
        }
        nodes.push(
          <ul key={key++} className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-muted">
            {items.map((item, idx) => (
              <li key={idx}>{renderInline(item)}</li>
            ))}
          </ul>,
        )
        continue
      }

      const para: string[] = [trimmed]
      i += 1
      while (i < lines.length) {
        const next = lines[i].trim()
        if (
          !next ||
          next === '---' ||
          next.startsWith('#') ||
          next.startsWith('- ')
        ) {
          break
        }
        para.push(next)
        i += 1
      }
      nodes.push(
        <p key={key++} className="mt-3 text-[15px] leading-relaxed text-muted first:mt-0">
          {renderInline(para.join(' '))}
        </p>,
      )
    }

    return nodes
  }, [markdown])

  return <div className="legal-body">{blocks}</div>
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
  const effectiveLabel = formatEffectiveDate(legalDoc?.effective_date)
  const bodyMarkdown = useMemo(
    () => stripDuplicateTitle(legalDoc?.body || '', title),
    [legalDoc?.body, title],
  )

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

          <header className="mt-10">
            <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
              {title}
            </h1>
            {effectiveLabel && (
              <p className="mt-3 text-sm text-muted">Effective {effectiveLabel}</p>
            )}
          </header>

          {error && (
            <p className="mt-6 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-700 dark:text-red-300">
              {error}
            </p>
          )}

          {loading && !legalDoc ? (
            <p className="mt-10 text-sm text-muted">Loading…</p>
          ) : (
            <article className="mt-8">
              <LegalBody markdown={bodyMarkdown} />
            </article>
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
