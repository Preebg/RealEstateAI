import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../lib/authStore'

export function LoginPage() {
  const { session, loading } = useAuthStore()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)

  if (!loading && session) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'signin') {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password })
        if (err) throw err
      } else {
        if (!accepted) throw new Error('Accept the Terms and Privacy Policy to sign up.')
        const { error: err } = await supabase.auth.signUp({ email, password })
        if (err) throw err
      }
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  async function googleSignIn() {
    setError(null)
    const { error: err } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/` },
    })
    if (err) setError(err.message)
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12">
      <div className="mb-10 text-center">
        <h1 className="font-display text-4xl font-semibold text-primary">CapEigen</h1>
        <p className="mt-2 text-muted">AI rental underwriting with QAOA portfolio alignment.</p>
      </div>

      <form
        onSubmit={onSubmit}
        className="rounded-2xl border border-border bg-white/90 p-6 shadow-sm"
      >
        <div className="mb-4 flex gap-2 rounded-lg bg-surface p-1">
          {(['signin', 'signup'] as const).map((m) => (
            <button
              key={m}
              type="button"
              className={`flex-1 rounded-md py-2 text-sm font-medium ${
                mode === m ? 'bg-white text-primary shadow-sm' : 'text-muted'
              }`}
              onClick={() => setMode(m)}
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
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
          />
        </label>

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

        <button
          type="button"
          onClick={googleSignIn}
          className="w-full rounded-lg border border-border bg-white py-2.5 text-sm font-medium hover:bg-surface"
        >
          Continue with Google
        </button>
      </form>
    </div>
  )
}
