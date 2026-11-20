import { useEffect } from 'react'
import { X } from 'lucide-react'
import { SERVER_UNAVAILABLE_MESSAGE } from '../lib/serverAvailability'

type ServerUnavailableModalProps = {
  open: boolean
  onClose: () => void
  message?: string
}

/** Shown when a visitor tries to sign in while the agent/API server is offline. */
export function ServerUnavailableModal({
  open,
  onClose,
  message = SERVER_UNAVAILABLE_MESSAGE,
}: ServerUnavailableModalProps) {
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="server-unavailable-title"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Dismiss"
          className="absolute right-3 top-3 rounded-lg p-1.5 text-muted transition hover:bg-surface hover:text-text"
          onClick={onClose}
        >
          <X className="size-4" aria-hidden />
        </button>
        <h2
          id="server-unavailable-title"
          className="pr-8 font-display text-xl font-semibold tracking-tight text-text"
        >
          Access unavailable
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-muted">{message}</p>
        <button
          type="button"
          onClick={onClose}
          className="mt-6 w-full rounded-lg bg-primary py-2.5 text-sm font-semibold text-white transition hover:bg-primary-hover"
        >
          OK
        </button>
      </div>
    </div>
  )
}
