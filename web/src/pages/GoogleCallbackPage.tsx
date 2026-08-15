import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { exchangeGoogleAuthCode, readGoogleOAuthCallback } from '../lib/googleOAuth'
import { trackPreviewEvent } from '../lib/previewActivity'

export function GoogleCallbackPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function finish() {
      try {
        const parts = readGoogleOAuthCallback()
        const idToken = await exchangeGoogleAuthCode(parts)
        const { error: err } = await supabase.auth.signInWithIdToken({
          provider: 'google',
          token: idToken,
          nonce: parts.nonce,
        })
        if (err) throw err
        trackPreviewEvent('login', { path: '/login', label: 'Google sign-in' })
        window.history.replaceState(null, '', '/auth/google/callback')
        if (!cancelled) navigate('/', { replace: true })
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Google sign-in failed')
        }
      }
    }

    void finish()
    return () => {
      cancelled = true
    }
  }, [navigate])

  if (error) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12 text-center">
        <h1 className="font-display text-2xl font-semibold text-primary">CapEigen</h1>
        <p className="mt-4 text-sm text-red-600">{error}</p>
        <p className="mt-3 text-xs text-muted">
          In Google Cloud, Authorized redirect URIs must include exactly:{' '}
          <code className="break-all">
            {typeof window !== 'undefined' ? `${window.location.origin}/auth/google/callback` : ''}
          </code>
        </p>
        <Link className="mt-6 text-sm text-primary underline" to="/login">
          Back to sign in
        </Link>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-muted">
      Completing Google sign-in…
    </div>
  )
}
