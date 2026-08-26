import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, type AnalysisJob, type FinanceResult } from '../lib/api'
import { AdminCatalogEditor } from '../components/AdminCatalogEditor'
import { PropertyAnalysisView } from '../components/PropertyAnalysisView'
import { firstCatalogUuid, fetchPropertyDetail, createPropertyShare, recordPropertyView } from '../lib/portfolio'
import type { Assumptions } from '../lib/propertyAnalysis'
import {
  assumptionPersistSignature,
  assumptionsFromProperty,
  buildOverridePayload,
  hasCriticalAssumptionChanges,
  assumptionMetaFromProperty,
} from '../lib/propertyAnalysis'
import { isAdminUser } from '../lib/admin'
import { useAuthStore } from '../lib/authStore'
import { trackPreviewEvent } from '../lib/previewActivity'

function addressesMatch(a?: unknown, b?: unknown): boolean {
  return String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase()
}

export function SearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const isAdmin = isAdminUser(user)
  const paramAddress = params.get('address') || ''
  const paramId = params.get('id') || ''
  const [query, setQuery] = useState(paramAddress)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const [shareBusy, setShareBusy] = useState(false)
  const [viewCount, setViewCount] = useState<number | null>(null)
  const autoStartedKey = useRef<string | null>(null)
  const lastRecalcSig = useRef<string>('')
  const lastPersistedSig = useRef<string>('')
  const overrideDebounceRef = useRef<number | null>(null)
  const pendingOverrideRef = useRef<{
    assumptions: Assumptions
    overrideNotes: string
  } | null>(null)
  const [assumptionPersistState, setAssumptionPersistState] = useState<
    'idle' | 'unsaved' | 'saving' | 'saved'
  >('idle')

  const jobQuery = useQuery({
    queryKey: ['analysis', jobId],
    enabled: Boolean(jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'done' || s === 'error' ? false : 1500
    },
    queryFn: () => apiFetch<AnalysisJob>(`/api/analysis/${jobId}`),
  })

  const kbQuery = useQuery({
    queryKey: ['kb-property', paramId, paramAddress],
    enabled: Boolean(paramId || paramAddress),
    queryFn: () => fetchPropertyDetail({ id: paramId || null, address: paramAddress || null }),
  })

  const jobProperty = jobQuery.data?.property_data
  const kbProperty = kbQuery.data
  const kbMatch =
    kbProperty &&
    (addressesMatch(kbProperty.address, query) ||
      (Boolean(paramId) && addressesMatch(query, paramAddress)))
      ? kbProperty
      : null
  const property = useMemo(() => {
    const base = jobProperty ?? kbMatch ?? null
    if (!base) return null
    const catalogId = firstCatalogUuid(
      base.id,
      base.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (catalogId && String(base.id || '') !== catalogId) {
      return { ...base, id: catalogId, property_id: catalogId }
    }
    return base
  }, [jobProperty, kbMatch, paramId])

  const catalogId = firstCatalogUuid(
    property?.id,
    property?.property_id,
    kbMatch?.id,
    kbMatch?.property_id,
    paramId,
  )

  const displayProperty = useMemo(() => {
    if (!property) return null
    if (viewCount == null) return property
    return { ...property, app_view_count: viewCount }
  }, [property, viewCount])

  useEffect(() => {
    if (!property) {
      lastPersistedSig.current = ''
      setAssumptionPersistState('idle')
      return
    }
    const baselineAssumptions = assumptionsFromProperty(property)
    const notes = typeof property.override_notes === 'string' ? property.override_notes : ''
    lastPersistedSig.current = assumptionPersistSignature(baselineAssumptions, notes)
    setAssumptionPersistState('idle')
  }, [catalogId, property])

  useEffect(() => {
    setViewCount(null)
    if (!catalogId) return
    let cancelled = false
    void recordPropertyView(catalogId)
      .then((count) => {
        if (!cancelled) setViewCount(count)
      })
      .catch(() => {
        // Viewership is optional.
      })
    return () => {
      cancelled = true
    }
  }, [catalogId])

  useEffect(() => {
    document.title = 'Individual Search · CapEigen'
  }, [])

  useEffect(() => {
    if (paramAddress) setQuery(paramAddress)
  }, [paramAddress])

  async function searchAddresses(q: string) {
    setQuery(q)
    if (q.trim().length < 2) {
      setSuggestions([])
      return
    }
    try {
      const res = await apiFetch<{ addresses: string[] }>(
        `/api/properties/search?q=${encodeURIComponent(q)}&limit=8`,
      )
      setSuggestions(res.addresses)
    } catch {
      setSuggestions([])
    }
  }

  async function startAnalysis(address?: string) {
    const target = (address || query).trim()
    if (!target) return
    setBusy(true)
    setError(null)
    setShareUrl(null)
    lastRecalcSig.current = ''
    lastPersistedSig.current = ''
    setAssumptionPersistState('idle')
    try {
      const res = await apiFetch<{ job_id: string }>('/api/analysis/start', {
        method: 'POST',
        body: JSON.stringify({ address: target }),
      })
      setJobId(res.job_id)
      setQuery(target)
      setSuggestions([])
      trackPreviewEvent('analyze', {
        path: '/search',
        label: target,
        payload: { address: target },
      })
    } catch (err) {
      const catalogHit =
        addressesMatch(paramAddress, target) &&
        (kbQuery.isLoading || Boolean(kbQuery.data) || Boolean(paramId))
      if (!catalogHit) {
        setError(err instanceof Error ? err.message : 'Analysis failed')
      }
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const addr = paramAddress.trim()
    if (!addr) return
    const key = `${paramId}|${addr}`
    if (autoStartedKey.current === key) return
    autoStartedKey.current = key
    void startAnalysis(addr)
    // Auto-run once per home-page click-through. startAnalysis is recreated each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramAddress, paramId])

  async function createShare() {
    const propertyId = firstCatalogUuid(
      property?.id,
      property?.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (!propertyId) {
      setError('Save the property to your account before creating a share link.')
      return
    }
    setError(null)
    setShareCopied(false)
    setShareBusy(true)
    setShareUrl(null)
    try {
      const res = await createPropertyShare({ propertyId })
      setShareUrl(res.share_url)
      trackPreviewEvent('share', {
        path: '/search',
        label: String(property?.address || propertyId),
        payload: { address: property?.address, property_id: propertyId },
      })
      try {
        await navigator.clipboard.writeText(res.share_url)
        setShareCopied(true)
      } catch {
        setShareCopied(false)
      }
    } catch (err) {
      setShareUrl(null)
      setError(err instanceof Error ? err.message : 'Failed to create share link')
    } finally {
      setShareBusy(false)
    }
  }

  async function bookmark() {
    await apiFetch('/api/properties/bookmark', {
      method: 'POST',
      body: JSON.stringify({
        property_id: property?.id || property?.property_id,
        property_data: property,
      }),
    })
    trackPreviewEvent('bookmark', {
      path: '/search',
      label: String(property?.address || ''),
      payload: { address: property?.address, property_id: property?.id },
    })
  }

  async function persistAssumptionOverrides(
    next: Assumptions,
    overrideNotes: string,
    propertySnapshot: Record<string, unknown>,
  ) {
    const propertyId = firstCatalogUuid(
      propertySnapshot.id,
      propertySnapshot.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (!propertyId) {
      pendingOverrideRef.current = { assumptions: next, overrideNotes }
      const meta = assumptionMetaFromProperty(propertySnapshot, next)
      if (hasCriticalAssumptionChanges(meta) || overrideNotes.trim()) {
        setAssumptionPersistState('unsaved')
      }
      return
    }

    const { body, hasChanges } = buildOverridePayload(propertySnapshot, next, overrideNotes)
    if (!hasChanges) {
      setAssumptionPersistState('idle')
      return
    }

    const sig = assumptionPersistSignature(next, overrideNotes)
    if (lastPersistedSig.current === sig) {
      setAssumptionPersistState('saved')
      return
    }

    setAssumptionPersistState('saving')
    try {
      await apiFetch('/api/properties/override', {
        method: 'POST',
        body: JSON.stringify({
          property_id: propertyId,
          address: String(propertySnapshot.address || query || ''),
          ...body,
        }),
      })
      lastPersistedSig.current = sig
      setAssumptionPersistState('saved')
      pendingOverrideRef.current = null
    } catch {
      setAssumptionPersistState('unsaved')
    }
  }

  function scheduleAssumptionPersist(
    next: Assumptions,
    overrideNotes: string,
    propertySnapshot: Record<string, unknown>,
  ) {
    const meta = assumptionMetaFromProperty(propertySnapshot, next)
    if (hasCriticalAssumptionChanges(meta) || overrideNotes.trim()) {
      setAssumptionPersistState((state) => (state === 'saving' ? state : 'unsaved'))
    } else {
      setAssumptionPersistState('idle')
    }

    if (overrideDebounceRef.current) {
      window.clearTimeout(overrideDebounceRef.current)
    }
    overrideDebounceRef.current = window.setTimeout(() => {
      overrideDebounceRef.current = null
      void persistAssumptionOverrides(next, overrideNotes, propertySnapshot)
    }, 800)
  }

  useEffect(() => {
    if (!property || !pendingOverrideRef.current) return
    const propertyId = firstCatalogUuid(
      property.id,
      property.property_id,
      kbMatch?.id,
      kbMatch?.property_id,
      paramId,
    )
    if (!propertyId) return
    const pending = pendingOverrideRef.current
    pendingOverrideRef.current = null
    void persistAssumptionOverrides(pending.assumptions, pending.overrideNotes, property)
  }, [property, kbMatch, paramId])

  function persistFinance(
    next: Assumptions,
    overrideNotes = '',
    propertySnapshot?: Record<string, unknown>,
  ) {
    const activeProperty = propertySnapshot || property
    if (!activeProperty) return
    if (propertySnapshot || property) {
      scheduleAssumptionPersist(next, overrideNotes, activeProperty)
    }
    if (!jobId) return
    const price = Number(activeProperty.price ?? activeProperty.predicted_value) || 0
    const sig = `${jobId}|${next.monthly_rent}|${next.down_payment_pct}|${next.interest_rate}|${next.loan_term}|${next.closing_costs_pct}|${next.tax_rate}|${next.monthly_insurance}|${next.monthly_hoa}|${next.maint_percent}|${next.vacancy_reserve_pct}|${next.management_fee_pct}`
    if (lastRecalcSig.current === sig) return
    lastRecalcSig.current = sig
    void apiFetch<FinanceResult>('/api/finance/recalc', {
      method: 'POST',
      body: JSON.stringify({
        ...next,
        price,
        job_id: jobId,
        location_score: Number(activeProperty.location_score) || 5,
        forecast_rate: Number(activeProperty.forecast_rate) || 0,
      }),
    }).catch(() => {
      // Client-side breakdown is already on screen.
    })
  }

  const deferred = jobQuery.data?.deferred_tasks ?? []
  const total = jobQuery.data?.deferred_tasks_total || 0
  const done = Math.max(total - deferred.length, 0)
  const fromKb = Boolean(jobQuery.data?.from_kb || (property && !jobProperty && kbMatch))
  const jobStatus = jobQuery.data?.status
  const researching =
    busy ||
    (Boolean(jobId) && !property && jobStatus !== 'done' && jobStatus !== 'error')
  const stillComputing =
    jobQuery.data?.status === 'running' && (deferred.length > 0 || !property)

  function onSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void startAnalysis()
  }

  return (
    <PropertyAnalysisView
      variant="account"
      property={displayProperty}
      addressLabel={query}
      sourceLabel={property ? (fromKb ? 'Loaded from knowledge base' : 'AI research') : undefined}
      stillComputing={stillComputing}
      shareBusy={shareBusy}
      shareUrl={shareUrl}
      shareCopied={shareCopied}
      onShare={() => void createShare()}
      onBookmark={() => void bookmark()}
      onAssumptionsChange={(next, _finance, overrideNotes) =>
        persistFinance(next, overrideNotes)
      }
      assumptionPersistState={assumptionPersistState}
      header={
        <>
          <header>
            <h1 className="font-display text-3xl font-semibold">Individual Search</h1>
            <p className="mt-1 text-muted">
              Enter an address to estimate rent, cash flow, and long-term returns.
            </p>
          </header>

          <form className="relative rounded-2xl border border-border bg-card p-4 shadow-sm" onSubmit={onSearchSubmit}>
            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                value={query}
                onChange={(e) => searchAddresses(e.target.value)}
                placeholder="123 Main St, Austin, TX"
                autoComplete="off"
                name="address"
                className="flex-1 rounded-lg border border-border px-3 py-2 outline-none focus:border-primary"
              />
              <button
                type="submit"
                disabled={busy || researching}
                className="rounded-lg bg-primary px-5 py-2 font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
              >
                {busy ? 'Starting…' : researching ? 'Researching…' : 'Analyze Property'}
              </button>
            </div>
            {suggestions.length > 0 && (
              <ul className="absolute left-4 right-4 top-full z-10 mt-1 max-h-48 overflow-auto rounded-lg border border-border bg-card shadow-lg">
                {suggestions.map((addr) => (
                  <li key={addr}>
                    <button
                      type="button"
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-surface"
                      onClick={() => startAnalysis(addr)}
                    >
                      {addr}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </form>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {jobQuery.data?.error && (
            <p className="text-sm text-amber-700">{jobQuery.data.error}</p>
          )}
          {researching && (
            <p className="text-sm text-muted">
              Researching {query || 'this address'}… Harvesting pauses so this search goes first.
            </p>
          )}
          {kbQuery.isLoading && paramAddress && !property && !researching && (
            <p className="text-sm text-muted">Loading property from catalog…</p>
          )}

          {jobId && deferred.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-3 text-sm">
              <p className="mb-2 text-muted">
                Background: {deferred[0]} ({done}/{total})
              </p>
              <div className="h-2 overflow-hidden rounded-full bg-surface">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${total ? (done / total) * 100 : 0}%` }}
                />
              </div>
            </div>
          )}
          {isAdmin && catalogId && displayProperty && (
            <AdminCatalogEditor
              property={displayProperty}
              propertyId={catalogId}
              onSaved={(next) => {
                void queryClient.invalidateQueries({ queryKey: ['kb-property'] })
                void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
                if (jobId && next) {
                  queryClient.setQueryData(['analysis', jobId], (current: AnalysisJob | undefined) =>
                    current
                      ? { ...current, property_data: { ...(current.property_data || {}), ...next } }
                      : current,
                  )
                }
              }}
              onDeleted={() => {
                void queryClient.invalidateQueries({ queryKey: ['kb-property'] })
                void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
                navigate('/', { replace: true })
              }}
            />
          )}
        </>
      }
    />
  )
}
