import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'

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

  useEffect(() => {
    let cancelled = false
    async function load() {
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
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [slug])

  const title = legalDoc?.title || (slug === 'privacy' ? 'Privacy Policy' : 'Terms of Service')
  const body = legalDoc?.body || ''

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <Link to="/login" className="text-sm text-primary hover:underline">
        ← Back to login
      </Link>
      <h1 className="mt-4 font-display text-3xl font-semibold">{title}</h1>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <article className="prose prose-sm mt-6 whitespace-pre-wrap text-text/90">{body}</article>
    </div>
  )
}
