import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../lib/authStore'
import {
  acceptCurrentLegalDocuments,
  fetchLegalAcceptanceStatus,
  type LegalAcceptanceStatus,
} from '../lib/legalAcceptance'
import { formatLegalEffectiveDate } from './LegalMarkdown'

export function LegalAcceptanceModal() {
  const session = useAuthStore((s) => s.session)
  const userId = session?.user?.id
  const [status, setStatus] = useState<LegalAcceptanceStatus | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!userId) {
      setStatus(null)
      setAccepted(false)
      setError(null)
      return
    }
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const next = await fetchLegalAcceptanceStatus()
        if (!cancelled) setStatus(next)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not check legal acceptance')
          // Fail closed: require acceptance if status cannot be loaded.
          setStatus({
            needs_acceptance: true,
            privacy_effective_date: '',
            terms_effective_date: '',
          })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [userId])

  if (!userId || loading || !status?.needs_acceptance) return null

  const privacyLabel = formatLegalEffectiveDate(status.privacy_effective_date)
  const termsLabel = formatLegalEffectiveDate(status.terms_effective_date)
  const effectiveBits = [privacyLabel && `Privacy ${privacyLabel}`, termsLabel && `Terms ${termsLabel}`]
    .filter(Boolean)
    .join(' · ')

  async function onAgree() {
    if (!accepted) return
    setBusy(true)
    setError(null)
    try {
      const next = await acceptCurrentLegalDocuments()
      setStatus(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save acceptance')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-text/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="legal-update-title"
    >
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-xl">
        <div className="h-1.5 bg-primary" />
        <div className="space-y-4 p-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-primary">Legal update</p>
            <h2 id="legal-update-title" className="mt-1 font-display text-2xl font-semibold tracking-tight">
              Updated Terms & Privacy Policy
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              Our Privacy Policy and Terms of Service have changed
              {effectiveBits ? ` (effective ${effectiveBits})` : ''}. Please review the updated
              documents and agree before continuing to use CapEigen.
            </p>
          </div>

          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
            <Link
              className="font-medium text-primary underline"
              to="/legal/privacy"
              target="_blank"
              rel="noreferrer"
            >
              Read Privacy Policy
            </Link>
            <Link
              className="font-medium text-primary underline"
              to="/legal/terms"
              target="_blank"
              rel="noreferrer"
            >
              Read Terms of Service
            </Link>
          </div>

          <label className="flex items-start gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
              className="mt-1"
            />
            <span>
              I have read and agree to the updated{' '}
              <Link className="text-primary underline" to="/legal/terms" target="_blank" rel="noreferrer">
                Terms
              </Link>{' '}
              and{' '}
              <Link className="text-primary underline" to="/legal/privacy" target="_blank" rel="noreferrer">
                Privacy Policy
              </Link>
              .
            </span>
          </label>

          {error && <p className="text-sm text-red-600 dark:text-red-300">{error}</p>}

          <button
            type="button"
            disabled={!accepted || busy}
            onClick={() => void onAgree()}
            className="w-full rounded-lg bg-primary py-3 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {busy ? 'Saving…' : 'Agree and continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
