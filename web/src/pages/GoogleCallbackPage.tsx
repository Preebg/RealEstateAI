import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { readGoogleOAuthCallback } from '../lib/googleOAuth'

export function GoogleCallbackPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function finish() {
      try {
        const { idToken, nonce } = readGoogleOAuthCallback()
        const { error: err } = await supabase.auth.signInWithIdToken({
          provider: 'google',
          token: idToken,
          nonce,
        })
        if (err) throw err
        // Drop the token fragment from history before navigating home.
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
