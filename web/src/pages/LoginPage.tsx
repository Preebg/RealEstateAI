import { useRef, useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../lib/authStore'
import { signInWithPreviewUsername } from '../lib/demoLogin'
import { getGoogleClientId } from '../lib/googleGis'
import { startGoogleOAuthRedirect } from '../lib/googleOAuth'
import { trackPreviewEvent } from '../lib/previewActivity'
import { prefetchHome, prefetchHomeChunk } from '../lib/prefetchHome'
import {
  consumeIdleLogoutNotice,
  IDLE_LOGOUT_MESSAGE,
} from '../lib/idleSession'
import { ThemeToggle } from '../components/ThemeToggle'

export function LoginPage() {
  const { session, loading } = useAuthStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const homePrefetched = useRef(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [mode, setMode] = useState<'signin' | 'signup'>(() =>
    searchParams.get('mode') === 'signup' ? 'signup' : 'signin',
  )
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [previewAccepted, setPreviewAccepted] = useState(false)
  const [previewUsername, setPreviewUsername] = useState('')
  const [showPreview, setShowPreview] = useState(
    () => searchParams.get('preview') === '1' || searchParams.get('demo') === '1',
  )
  const [idleNotice, setIdleNotice] = useState(() => consumeIdleLogoutNotice())
  const googleConfigured = Boolean(getGoogleClientId())

  useEffect(() => {
    if (searchParams.get('mode') === 'signup') setMode('signup')
    if (searchParams.get('preview') === '1' || searchParams.get('demo') === '1') {
      setShowPreview(true)
    }
  }, [searchParams])

  function warmHomeChunk(): void {
    if (homePrefetched.current) return
    homePrefetched.current = true
    prefetchHomeChunk()
  }

  function goHomeAfterAuth(): void {
    prefetchHome(queryClient)
    navigate('/')
  }

  if (!loading && session) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setInfo(null)
    setBusy(true)
    try {
      if (mode === 'signin') {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password })
        if (err) throw err
        trackPreviewEvent('login', { path: '/login', label: 'Email sign-in' })
        goHomeAfterAuth()
        return
      }

      if (!accepted) throw new Error('Accept the Terms and Privacy Policy to sign up.')
      if (password !== confirmPassword) throw new Error('Passwords do not match.')

      const { data, error: err } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/` },
      })
      if (err) throw err

      if (data.session) {
        trackPreviewEvent('login', { path: '/login', label: 'Email sign-up' })
        goHomeAfterAuth()
        return
      }

      const { error: signInErr } = await supabase.auth.signInWithPassword({ email, password })
      if (signInErr) {
        setMode('signin')
        setConfirmPassword('')
        setInfo('Account created. Sign in with your email and password.')
        return
      }
      trackPreviewEvent('login', { path: '/login', label: 'Email sign-up' })
      goHomeAfterAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  async function previewSignIn(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setInfo(null)
    setBusy(true)
    try {
      if (!previewAccepted) {
        throw new Error('Accept the Terms and Privacy Policy to continue.')
      }
      await signInWithPreviewUsername(previewUsername)
      goHomeAfterAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview login failed')
    } finally {
      setBusy(false)
    }
  }

  async function googleSignIn() {
    setError(null)
    setInfo(null)
    setBusy(true)
    warmHomeChunk()
    try {
      await startGoogleOAuthRedirect()
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : 'Google sign-in failed')
    }
  }

  return (
    <div className="relative min-h-screen">
      {idleNotice && (
        <div
          className="fixed inset-x-0 top-0 z-20 border-b border-amber-200 bg-amber-50 px-4 py-3 text-center text-sm text-amber-950 shadow-sm"
          role="status"
        >
          <div className="mx-auto flex max-w-2xl items-start justify-center gap-3">
            <p className="flex-1 pt-0.5">{IDLE_LOGOUT_MESSAGE}</p>
            <button
              type="button"
              aria-label="Dismiss"
              className="shrink-0 rounded px-2 py-0.5 text-amber-800/70 hover:bg-amber-100 hover:text-amber-950"
              onClick={() => setIdleNotice(false)}
            >
              ×
            </button>
          </div>
        </div>
      )}
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <ThemeToggle />
        <div className="relative">
        <button
          type="button"
          onClick={() => {
            setShowPreview((open) => !open)
            setError(null)
          }}
          className="rounded-lg border border-border bg-card/90 px-3 py-1.5 text-sm font-medium text-text shadow-sm hover:bg-surface"
        >
          Preview
        </button>
        {showPreview && (
          <form
            onSubmit={(e) => void previewSignIn(e)}
            className="absolute right-0 mt-2 w-80 rounded-2xl border border-primary/30 bg-card p-5 shadow-lg"
          >
            <h2 className="text-sm font-semibold text-primary">Preview access</h2>
            <p className="mt-2 mb-3 text-sm text-muted">Enter your username. No password.</p>
            <label className="mb-3 block text-sm">
              Username
              <input
                type="text"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                value={previewUsername}
                onChange={(e) => setPreviewUsername(e.target.value)}
                className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
              />
            </label>
            <label className="mb-3 flex items-start gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={previewAccepted}
                onChange={(e) => setPreviewAccepted(e.target.checked)}
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
            <button
              type="submit"
              disabled={busy || !previewAccepted || previewUsername.trim().length < 2}
              className="w-full rounded-lg bg-primary py-2.5 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
            >
              {busy ? 'Please wait…' : 'Continue with username'}
            </button>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </form>
        )}
        </div>
      </div>

      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12">
      <div className="mb-10 text-center">
        <Link to="/" className="font-display text-4xl font-semibold text-primary hover:opacity-90">
          CapEigen
        </Link>
        <p className="mt-2 text-muted">AI rental underwriting with QAOA portfolio alignment.</p>
      </div>

      <form
        onSubmit={onSubmit}
        className="rounded-2xl border border-border bg-card/90 p-6 shadow-sm"
      >
        <div className="mb-4 flex gap-2 rounded-lg bg-surface p-1">
          {(['signin', 'signup'] as const).map((m) => (
            <button
              key={m}
              type="button"
              className={`flex-1 rounded-md py-2 text-sm font-medium ${
                mode === m ? 'bg-card text-primary shadow-sm' : 'text-muted'
              }`}
              onClick={() => {
                setMode(m)
                setError(null)
                setInfo(null)
                setConfirmPassword('')
              }}
            >
              {m === 'signin' ? 'Sign in' : 'Sign up'}
            </button>
          ))}
        </div>

        <label className="mb-3 block text-sm">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
          />
        </label>
        <label className="mb-4 block text-sm">
          Password
          <input
            type="password"
            required
            minLength={6}
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            value={password}
            onFocus={warmHomeChunk}
            onChange={(e) => {
              warmHomeChunk()
              setPassword(e.target.value)
            }}
            className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
          />
        </label>

        {mode === 'signup' && (
          <label className="mb-4 block text-sm">
            Confirm password
            <input
              type="password"
              required
              minLength={6}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
            />
          </label>
        )}

        {mode === 'signup' && (
          <label className="mb-4 flex items-start gap-2 text-sm text-muted">
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
        )}

        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
        {info && <p className="mb-3 text-sm text-primary">{info}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-primary py-2.5 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>

        <div className="my-4 flex items-center gap-3 text-xs text-muted">
          <div className="h-px flex-1 bg-border" />
          or
          <div className="h-px flex-1 bg-border" />
        </div>

        {googleConfigured ? (
          <button
            type="button"
            onClick={() => void googleSignIn()}
            disabled={busy}
            className="w-full rounded-lg border border-border bg-card py-2.5 text-sm font-medium hover:bg-surface disabled:opacity-60"
          >
            Continue with Google
          </button>
        ) : (
          <p className="text-center text-sm text-muted">
            Google sign-in needs <code className="text-xs">VITE_GOOGLE_CLIENT_ID</code> in env.
          </p>
        )}
      </form>
      </div>
    </div>
  )
}
