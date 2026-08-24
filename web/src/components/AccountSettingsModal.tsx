import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../lib/authStore'
import { apiFetch } from '../lib/api'
import { getGoogleClientId } from '../lib/googleGis'
import { startGoogleOAuthRedirect } from '../lib/googleOAuth'
import { isPreviewUser } from '../lib/previewActivity'

type AccountSettingsModalProps = {
  open: boolean
  onClose: () => void
}

function hasGoogleIdentity(identities: { provider?: string }[] | undefined): boolean {
  return (identities ?? []).some((identity) => identity.provider === 'google')
}

export function AccountSettingsModal({ open, onClose }: AccountSettingsModalProps) {
  const { user, signOut } = useAuthStore()
  const navigate = useNavigate()
  const email = (user?.email || '').trim()
  const googleLinked = hasGoogleIdentity(user?.identities)
  const googleConfigured = Boolean(getGoogleClientId())
  const preview = isPreviewUser(user)

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordBusy, setPasswordBusy] = useState(false)

  const [linkError, setLinkError] = useState<string | null>(null)
  const [linkBusy, setLinkBusy] = useState(false)

  const [deletePassword, setDeletePassword] = useState('')
  const [deleteEmail, setDeleteEmail] = useState('')
  const [deleteUnderstood, setDeleteUnderstood] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setNewPassword('')
    setConfirmPassword('')
    setPasswordMessage(null)
    setPasswordError(null)
    setLinkError(null)
    setDeletePassword('')
    setDeleteEmail('')
    setDeleteUnderstood(false)
    setDeleteError(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !user) return null

  async function onChangePassword(e: FormEvent) {
    e.preventDefault()
    setPasswordError(null)
    setPasswordMessage(null)
    if (newPassword.length < 6) {
      setPasswordError('Password must be at least 6 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('Passwords do not match.')
      return
    }
    setPasswordBusy(true)
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword })
      if (error) throw error
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMessage('Password updated.')
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : 'Could not update password')
    } finally {
      setPasswordBusy(false)
    }
  }

  async function onLinkGoogle() {
    setLinkError(null)
    setLinkBusy(true)
    try {
      await startGoogleOAuthRedirect({ link: true })
    } catch (err) {
      setLinkBusy(false)
      setLinkError(err instanceof Error ? err.message : 'Could not start Google linking')
    }
  }

  async function onDeleteAccount(e: FormEvent) {
    e.preventDefault()
    setDeleteError(null)
    if (!deleteUnderstood) {
      setDeleteError('Confirm that you understand this action cannot be undone.')
      return
    }
    if (deleteEmail.trim().toLowerCase() !== email.toLowerCase()) {
      setDeleteError('Typed email does not match your account email.')
      return
    }
    if (!deletePassword) {
      setDeleteError('Enter your password to delete this account.')
      return
    }
    setDeleteBusy(true)
    try {
      await apiFetch<{ ok: boolean }>('/api/account', {
        method: 'DELETE',
        body: JSON.stringify({
          password: deletePassword,
          email: deleteEmail.trim(),
          acknowledge: true,
        }),
      })
      await signOut()
      onClose()
      navigate('/', { replace: true })
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Could not delete account')
    } finally {
      setDeleteBusy(false)
    }
  }

  const canDelete =
    deleteUnderstood &&
    deletePassword.length > 0 &&
    deleteEmail.trim().toLowerCase() === email.toLowerCase() &&
    !deleteBusy

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-text/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-settings-title"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="absolute right-3 top-3 rounded-lg border border-border bg-card/90 p-1.5 text-muted hover:bg-surface"
          onClick={onClose}
          aria-label="Close account settings"
        >
          <X size={16} />
        </button>

        <div className="space-y-6 p-5 sm:p-6">
          <div>
            <h2 id="account-settings-title" className="font-display text-xl font-semibold text-primary">
              Account settings
            </h2>
            <p className="mt-1 text-sm text-muted">{email || 'Signed in'}</p>
          </div>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-text">Google account</h3>
            {googleLinked ? (
              <p className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm text-muted">
                Google is linked to this account.
              </p>
            ) : googleConfigured ? (
              <div className="space-y-2">
                <p className="text-sm text-muted">
                  Link Google so you can sign in with either email/password or Google.
                </p>
                <button
                  type="button"
                  disabled={linkBusy || preview}
                  onClick={() => void onLinkGoogle()}
                  className="rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium hover:bg-surface disabled:opacity-60"
                >
                  {linkBusy ? 'Redirecting…' : 'Link Google account'}
                </button>
                {preview && (
                  <p className="text-xs text-muted">Preview accounts cannot link Google.</p>
                )}
                {linkError && <p className="text-sm text-red-600">{linkError}</p>}
              </div>
            ) : (
              <p className="text-sm text-muted">
                Google linking needs <code className="text-xs">VITE_GOOGLE_CLIENT_ID</code> in env.
              </p>
            )}
          </section>

          <section className="space-y-3 border-t border-border pt-5">
            <h3 className="text-sm font-semibold text-text">Change password</h3>
            <p className="text-sm text-muted">Enter a new password twice. Both fields must match.</p>
            <form onSubmit={(e) => void onChangePassword(e)} className="space-y-3">
              <label className="block text-sm">
                New password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={6}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
                />
              </label>
              <label className="block text-sm">
                Confirm new password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={6}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
                />
              </label>
              {passwordError && <p className="text-sm text-red-600">{passwordError}</p>}
              {passwordMessage && <p className="text-sm text-primary">{passwordMessage}</p>}
              <button
                type="submit"
                disabled={passwordBusy || !newPassword || !confirmPassword}
                className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
              >
                {passwordBusy ? 'Saving…' : 'Update password'}
              </button>
            </form>
          </section>

          <section className="space-y-3 rounded-xl border border-red-200 bg-red-50/70 p-4 dark:border-red-900/50 dark:bg-red-950/30">
            <h3 className="text-sm font-semibold text-red-800 dark:text-red-300">Danger zone</h3>
            <p className="text-sm text-red-800/90 dark:text-red-300/90">
              Permanently delete your account and personal app data. This cannot be undone.
            </p>
            <form onSubmit={(e) => void onDeleteAccount(e)} className="space-y-3">
              <label className="block text-sm text-red-900 dark:text-red-200">
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  value={deletePassword}
                  onChange={(e) => setDeletePassword(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-red-200 bg-card px-3 py-2 text-text outline-none focus:border-red-400 dark:border-red-900/60"
                />
              </label>
              <label className="block text-sm text-red-900 dark:text-red-200">
                Type your email to confirm
                <input
                  type="email"
                  autoComplete="off"
                  value={deleteEmail}
                  onChange={(e) => setDeleteEmail(e.target.value)}
                  placeholder={email}
                  className="mt-1 w-full rounded-lg border border-red-200 bg-card px-3 py-2 text-text outline-none focus:border-red-400 dark:border-red-900/60"
                />
              </label>
              <label className="flex items-start gap-2 text-sm text-red-900 dark:text-red-200">
                <input
                  type="checkbox"
                  checked={deleteUnderstood}
                  onChange={(e) => setDeleteUnderstood(e.target.checked)}
                  className="mt-1"
                />
                <span>I understand this action cannot be undone.</span>
              </label>
              {deleteError && <p className="text-sm text-red-700 dark:text-red-300">{deleteError}</p>}
              <button
                type="submit"
                disabled={!canDelete}
                className="w-full rounded-lg bg-red-600 py-3 text-sm font-bold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleteBusy ? 'Deleting…' : 'Delete account'}
              </button>
            </form>
            <p className="text-xs text-red-800/80 dark:text-red-300/80">
              Google-only accounts: set a password above first, then delete. See the{' '}
              <Link className="underline" to="/legal/privacy">
                Privacy Policy
              </Link>
              .
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
