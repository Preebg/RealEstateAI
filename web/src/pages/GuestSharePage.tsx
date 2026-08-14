import { useEffect, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PropertyAnalysisView } from '../components/PropertyAnalysisView'
import { useAuthStore } from '../lib/authStore'
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

  if (share.isLoading) {
    return (
      <GuestShell>
        <p className="p-8 text-muted">Validating share link…</p>
      </GuestShell>
    )
  }

  if (share.error || !share.data?.valid || !share.data.property) {
    return (
      <GuestShell>
        <div className="mx-auto max-w-lg px-4 py-16 text-center">
          <h1 className="font-display text-2xl font-semibold">Link unavailable</h1>
          <p className="mt-2 text-muted">This share link is invalid or expired.</p>
          <Link to="/login" className="mt-6 inline-block text-primary underline">
            Sign in to CapEigen
          </Link>
        </div>
      </GuestShell>
    )
  }

  const property = share.data.property
  const address = String(property.address || share.data.address || 'Shared property')

  return (
    <GuestShell>
      <main className="px-4 py-6 sm:px-8">
        <PropertyAnalysisView
          variant="guest"
          property={property}
          addressLabel={address}
          sourceLabel="Shared analysis · sliders update locally"
          emptyHint="Loading assumptions…"
          header={
            <header>
              <p className="font-display text-sm font-semibold text-primary">
                CapEigen · Guest view
              </p>
              <h1 className="font-display text-3xl font-semibold">Shared analysis</h1>
              <p className="mt-1 text-muted">
                Move the sliders to recast cash flow, then download a PDF. Searching
                new addresses and comparing listings require a CapEigen account.
              </p>
            </header>
          }
        />
      </main>
    </GuestShell>
  )
}

function GuestShell({ children }: { children: ReactNode }) {
  const session = useAuthStore((s) => s.session)
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-bg/90 px-4 py-3 backdrop-blur sm:px-8">
        <span className="font-display text-lg font-semibold text-primary">CapEigen</span>
        <Link
          to={session ? '/' : '/login'}
          className="text-sm font-medium text-primary hover:underline"
        >
          {session ? 'Open my account' : 'Sign in'}
        </Link>
      </header>
      {children}
    </div>
  )
}
