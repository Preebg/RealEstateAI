import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { useAuthStore } from '../lib/authStore'
import {
  fetchPropertyOfTheDay,
  propertySearchPath,
  type PropertyOfDayPayload,
} from '../lib/portfolio'

function money(n?: number) {
  if (n == null || Number.isNaN(n)) return '—'
  const rounded = Math.round(n)
  if (rounded < 0) return `-$${Math.abs(rounded).toLocaleString()}`
  return `$${rounded.toLocaleString()}`
}

export function PropertyOfTheDayModal() {
  const session = useAuthStore((s) => s.session)
  const userId = session?.user?.id
  const [payload, setPayload] = useState<PropertyOfDayPayload | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!userId) {
      setPayload(null)
      setOpen(false)
      return
    }
    let cancelled = false
    async function load() {
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
        const data = await fetchPropertyOfTheDay(tz)
        if (cancelled) return
        if (data.show && data.property?.address) {
          setPayload(data)
          setOpen(true)
        }
      } catch {
        // Highlight is optional; never block the app.
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [userId])

  if (!open || !payload?.property) return null
  const property = payload.property

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-text/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="property-of-the-day-title"
    >
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-xl">
        <button
          type="button"
          className="absolute right-3 top-3 z-10 rounded-lg border border-border bg-card/90 p-1.5 text-muted hover:bg-surface"
          onClick={() => setOpen(false)}
          aria-label="Dismiss property of the day"
        >
          <X size={16} />
        </button>
        {property.primary_image_url ? (
          <img
            src={property.primary_image_url}
            alt=""
            className="h-40 w-full object-cover"
          />
        ) : (
          <div className="h-3 bg-primary" />
        )}
        <div className="space-y-4 p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-primary">
              Property of the Day
            </p>
            <h2 id="property-of-the-day-title" className="mt-1 font-display text-xl font-semibold">
              {property.address}
            </h2>
            <p className="mt-1 text-sm text-muted">
              A cash-flowing listing with lower simulated risk
              {(property.location_score ?? 0) >= 7 ? ' in a stronger neighborhood' : ''}.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-xl bg-surface/80 p-3">
              <dt className="text-xs uppercase tracking-wide text-muted">Cash flow / mo</dt>
              <dd className="mt-1 font-display text-lg font-semibold">
                {money(property.monthly_cash_flow)}
              </dd>
            </div>
            <div className="rounded-xl bg-surface/80 p-3">
              <dt className="text-xs uppercase tracking-wide text-muted">Quantum alignment</dt>
              <dd className="mt-1 font-display text-lg font-semibold">
                {property.quantum_success != null
                  ? `${property.quantum_success.toFixed(1)}%`
                  : '—'}
              </dd>
            </div>
            <div className="rounded-xl bg-surface/80 p-3">
              <dt className="text-xs uppercase tracking-wide text-muted">Location</dt>
              <dd className="mt-1 font-display text-lg font-semibold">
                {property.location_score != null
                  ? `${Number(property.location_score).toFixed(1)}/10`
                  : '—'}
              </dd>
            </div>
            <div className="rounded-xl bg-surface/80 p-3">
              <dt className="text-xs uppercase tracking-wide text-muted">In-app views</dt>
              <dd className="mt-1 font-display text-lg font-semibold">
                {(property.app_view_count ?? 0).toLocaleString()}
              </dd>
            </div>
          </dl>
          {payload.reasons.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-text/80">
              {payload.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface"
              onClick={() => setOpen(false)}
            >
              Maybe later
            </button>
            <Link
              to={propertySearchPath(property)}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover"
              onClick={() => setOpen(false)}
            >
              Analyze this property
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
