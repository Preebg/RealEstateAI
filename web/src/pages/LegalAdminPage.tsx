import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { clsx } from 'clsx'
import { apiFetch } from '../lib/api'
import { LegalDocumentPreview } from '../components/LegalMarkdown'

type LegalSlug = 'terms' | 'privacy'

type LegalDocument = {
  slug: LegalSlug
  title: string
  body: string
  effective_date: string
  updated_at?: string | null
  updated_by?: string | null
  is_default?: boolean
}

const DOCS: Array<{ slug: LegalSlug; heading: string }> = [
  { slug: 'privacy', heading: 'Privacy Policy' },
  { slug: 'terms', heading: 'Terms of Service' },
]

function formatWhen(iso?: string | null) {
  if (!iso) return 'Never published'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

export function LegalAdminPage() {
  const [slug, setSlug] = useState<LegalSlug>('privacy')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [effectiveDate, setEffectiveDate] = useState('')
  const [meta, setMeta] = useState<Pick<LegalDocument, 'updated_at' | 'updated_by' | 'is_default'> | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')

  async function load(next: LegalSlug) {
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const doc = await apiFetch<LegalDocument>(`/api/legal/${next}`)
      setTitle(doc.title)
      setBody(doc.body)
      setEffectiveDate(doc.effective_date)
      setMeta({
        updated_at: doc.updated_at,
        updated_by: doc.updated_by,
        is_default: doc.is_default,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load legal document')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    document.title = 'Legal · CapEigen'
    void load(slug)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  async function onSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setInfo(null)
    try {
      const doc = await apiFetch<LegalDocument>(`/api/legal/${slug}`, {
        method: 'PUT',
        body: JSON.stringify({
          title,
          body,
          effective_date: effectiveDate,
        }),
      })
      setTitle(doc.title)
      setBody(doc.body)
      setEffectiveDate(doc.effective_date)
      setMeta({
        updated_at: doc.updated_at,
        updated_by: doc.updated_by,
        is_default: doc.is_default,
      })
      setInfo(
        'Published. Signed-in users who accepted an older version will be asked to agree again before using the app.',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Legal</h1>
        <p className="mt-1 text-muted">
          Update the Privacy Policy and Terms of Service shown on the public legal pages and at
          sign-up. Preview matches what users see at{' '}
          <Link className="text-primary underline" to={`/legal/${slug}`} target="_blank">
            /legal/{slug}
          </Link>
          .
        </p>
      </header>

      <div className="flex flex-wrap gap-2">
        {DOCS.map((doc) => (
          <button
            key={doc.slug}
            type="button"
            onClick={() => {
              setSlug(doc.slug)
              setMode('edit')
            }}
            className={
              slug === doc.slug
                ? 'rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-white'
                : 'rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface'
            }
          >
            {doc.heading}
          </button>
        ))}
      </div>

      {error && <p className="text-red-600">{error}</p>}
      {info && <p className="text-emerald-700">{info}</p>}
      {busy && <p className="text-muted">Loading…</p>}

      {!busy && (
        <>
          <div className="flex gap-6 border-b border-border/80" role="tablist" aria-label="Editor mode">
            {(
              [
                { id: 'edit', label: 'Edit' },
                { id: 'preview', label: 'Preview' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={mode === tab.id}
                onClick={() => setMode(tab.id)}
                className={clsx(
                  '-mb-px border-b-2 pb-3 text-sm font-medium transition',
                  mode === tab.id
                    ? 'border-primary text-primary'
                    : 'border-transparent text-muted hover:text-text',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {mode === 'preview' ? (
            <div className="relative overflow-hidden rounded-2xl border border-border bg-bg">
              <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
                <div className="absolute -left-1/4 top-0 h-[40vh] w-[70vw] rounded-full bg-primary/[0.07] blur-3xl" />
                <div className="absolute -right-1/4 top-16 h-[30vh] w-[50vw] rounded-full bg-sky-400/[0.06] blur-3xl" />
              </div>
              <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8 sm:py-12">
                <LegalDocumentPreview title={title} effectiveDate={effectiveDate} body={body} />
              </div>
            </div>
          ) : (
            <form onSubmit={(e) => void onSave(e)} className="space-y-4">
              <p className="text-sm text-muted">
                {meta?.is_default
                  ? 'Showing built-in copy. Save to publish an edited version.'
                  : `Last published ${formatWhen(meta?.updated_at)}${
                      meta?.updated_by ? ` by ${meta.updated_by}` : ''
                    }.`}{' '}
                Public URL:{' '}
                <a
                  className="text-primary underline"
                  href={`/legal/${slug}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  /legal/{slug}
                </a>
              </p>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">Title</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  className="w-full rounded-lg border border-border px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">Effective date</span>
                <input
                  type="date"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                  required
                  className="rounded-lg border border-border px-3 py-2"
                />
                <span className="mt-1 block text-xs text-muted">
                  Bumping this date requires every signed-in user to accept the updated documents
                  again.
                </span>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">Document (Markdown)</span>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  required
                  minLength={40}
                  rows={22}
                  className="w-full rounded-lg border border-border px-3 py-2 font-mono text-sm"
                />
              </label>
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
              >
                {saving ? 'Publishing…' : 'Publish'}
              </button>
            </form>
          )}
        </>
      )}
    </div>
  )
}
