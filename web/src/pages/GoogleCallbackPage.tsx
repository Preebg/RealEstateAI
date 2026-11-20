import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'
import {
  consumeGoogleOAuthLinkMode,
  exchangeGoogleAuthCode,
  markOpenAccountSettings,
  readGoogleOAuthCallback,
} from '../lib/googleOAuth'
import { trackPreviewEvent } from '../lib/previewActivity'
import { prefetchHome, prefetchHomeChunk } from '../lib/prefetchHome'
import {
  isBackendOnline,
  SERVER_UNAVAILABLE_MESSAGE,
} from '../lib/serverAvailability'
import { ServerUnavailableModal } from '../components/ServerUnavailableModal'

export function GoogleCallbackPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('Completing Google sign-in…')
  const [unavailableOpen, setUnavailableOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    prefetchHomeChunk()

    async function finish() {
      try {
        const linking = consumeGoogleOAuthLinkMode()
        if (linking) setStatus('Linking Google account…')

        if (!linking && !(await isBackendOnline())) {
          if (!cancelled) setUnavailableOpen(true)
          return
        }

        const parts = readGoogleOAuthCallback()
        const idToken = await exchangeGoogleAuthCode(parts)

        if (linking) {
          const { error: err } = await supabase.auth.linkIdentity({
            provider: 'google',
            token: idToken,
            nonce: parts.nonce,
          })
          if (err) throw err
          markOpenAccountSettings()
          window.history.replaceState(null, '', '/auth/google/callback')
          if (!cancelled) {
            navigate('/', { replace: true })
          }
          return
        }

        const { error: err } = await supabase.auth.signInWithIdToken({
          provider: 'google',
          token: idToken,
          nonce: parts.nonce,
        })
        if (err) throw err
        trackPreviewEvent('login', { path: '/login', label: 'Google sign-in' })
        window.history.replaceState(null, '', '/auth/google/callback')
        if (!cancelled) {
          prefetchHome(queryClient)
          navigate('/', { replace: true })
        }
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
  }, [navigate, queryClient])

  if (unavailableOpen) {
    return (
      <div className="relative min-h-screen">
        <ServerUnavailableModal
          open
          message={SERVER_UNAVAILABLE_MESSAGE}
          onClose={() => navigate('/login', { replace: true })}
        />
      </div>
    )
  }

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
        <p className="mt-2 text-xs text-muted">
          Linking Google also requires Manual linking enabled in the Supabase Auth providers settings.
        </p>
        <Link className="mt-6 text-sm text-primary underline" to="/login">
          Back to sign in
        </Link>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-muted">{status}</div>
  )
}
