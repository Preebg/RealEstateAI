import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchGuestShare } from '../lib/portfolio'

export function GuestSharePage() {
  const { token = '' } = useParams()

  const share = useQuery({
    queryKey: ['guest-share', token],
    enabled: Boolean(token),
    queryFn: () => fetchGuestShare(token),
  })

  useEffect(() => {
    document.title = 'Shared property · CapEigen'
  }, [])

  if (share.isLoading) return <p className="p-8 text-muted">Validating share link…</p>
  if (share.error || !share.data?.valid || !share.data.property) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        <h1 className="font-display text-2xl font-semibold">Link unavailable</h1>
        <p className="mt-2 text-muted">This share link is invalid or expired.</p>
        <Link to="/login" className="mt-6 inline-block text-primary underline">
          Sign in to CapEigen
        </Link>
      </div>
    )
  }

  const prop = share.data.property

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <p className="font-display text-sm font-semibold text-primary">CapEigen · Guest view</p>
      <h1 className="font-display text-3xl font-semibold">
        {String(prop.address || share.data.address || 'Shared property')}
      </h1>
      <div className="grid gap-3 sm:grid-cols-2">
        {(
          [
            ['Price', prop.price ?? prop.predicted_value],
            ['Rent', prop.rent ?? prop.estimated_rent ?? prop.original_ai_rent],
            ['Location score', prop.location_score],
            ['Strategy', prop.strategy_tag || prop.property_label || prop.strategy],
          ] as Array<[string, unknown]>
        ).map(([label, value]) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="text-xs uppercase text-muted">{label}</p>
            <p className="mt-1 font-display text-lg font-semibold">
              {value == null ? '—' : String(value)}
            </p>
          </div>
        ))}
      </div>
      <Link to="/login" className="inline-block text-sm text-primary underline">
        Sign in for full analysis tools
      </Link>
    </div>
  )
}
