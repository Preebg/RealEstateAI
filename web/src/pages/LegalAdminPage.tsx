import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { apiFetch } from '../lib/api'

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
      setInfo('Published. The public legal page now shows this copy.')
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
          sign-up.
        </p>
      </header>

      <div className="flex flex-wrap gap-2">
        {DOCS.map((doc) => (
          <button
            key={doc.slug}
            type="button"
            onClick={() => setSlug(doc.slug)}
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
        <form onSubmit={(e) => void onSave(e)} className="space-y-4">
          <p className="text-sm text-muted">
            {meta?.is_default
              ? 'Showing built-in copy. Save to publish an edited version.'
              : `Last published ${formatWhen(meta?.updated_at)}${
                  meta?.updated_by ? ` by ${meta.updated_by}` : ''
                }.`}{' '}
            Public URL:{' '}
            <a className="text-primary underline" href={`/legal/${slug}`} target="_blank" rel="noreferrer">
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
    </div>
  )
}
