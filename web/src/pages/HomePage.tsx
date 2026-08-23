import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { Link } from 'react-router-dom'
import { ArrowUpDown, Check, ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'
import {
  CASH_FLOW_STEP,
  CASH_ON_CASH_STEP,
  fetchPortfolio,
  fixedStepRange,
  formatAddedAt,
  niceRange,
  PRICE_SLIDER_MAX,
  PRICE_SLIDER_MIN,
  PRICE_SLIDER_STEP,
  propertySearchPath,
  YEAR_BUILT_MIN,
} from '../lib/portfolio'
import { apiFetch, type PortfolioItem } from '../lib/api'
import { isAdminUser } from '../lib/admin'
import { useAuthStore } from '../lib/authStore'
import {
  applyFilters,
  defaultFilters,
  PortfolioFilters,
  type FilterBounds,
  type Filters,
} from '../components/PortfolioFilters'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

// Fix default marker icons under Vite
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

function money(n?: number) {
  if (n == null || Number.isNaN(n)) return '—'
  const rounded = Math.round(n)
  if (rounded < 0) return `-$${Math.abs(rounded).toLocaleString()}`
  return `$${rounded.toLocaleString()}`
}

function pct(n?: number, digits = 1) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(digits)}%`
}

const SORT_OPTIONS = [
  { id: 'added_desc', label: 'Newest added' },
  { id: 'added_asc', label: 'Oldest added' },
  { id: 'year_desc', label: 'Youngest (year built)' },
  { id: 'year_asc', label: 'Oldest (year built)' },
  { id: 'cashflow_desc', label: 'Highest cash flow' },
  { id: 'cashflow_asc', label: 'Lowest cash flow' },
  { id: 'coc_desc', label: 'Highest cash on cash' },
  { id: 'price_desc', label: 'Highest price' },
  { id: 'price_asc', label: 'Lowest price' },
  { id: 'views_desc', label: 'Most viewed' },
] as const

type SortId = (typeof SORT_OPTIONS)[number]['id']

const HOME_VIEW_STORAGE_PREFIX = 'capeigen.homeView.'

type HomeViewPersisted = {
  filters: Filters
  sortBy: SortId
}

function homeViewStorageKey(userId: string): string {
  return `${HOME_VIEW_STORAGE_PREFIX}${userId}`
}

function isRangeBounds(v: unknown): v is { min: number; max: number } {
  if (v == null || typeof v !== 'object') return false
  const r = v as { min?: unknown; max?: unknown }
  return typeof r.min === 'number' && Number.isFinite(r.min) && typeof r.max === 'number' && Number.isFinite(r.max)
}

function isFiltersShape(v: unknown): v is Filters {
  if (v == null || typeof v !== 'object') return false
  const f = v as Filters
  return (
    Array.isArray(f.states) &&
    Array.isArray(f.cities) &&
    f.states.every((s) => typeof s === 'string') &&
    f.cities.every((c) => typeof c === 'string') &&
    isRangeBounds(f.price) &&
    isRangeBounds(f.yearBuilt) &&
    isRangeBounds(f.rentalYield) &&
    isRangeBounds(f.cashFlow) &&
    isRangeBounds(f.cashOnCash) &&
    isRangeBounds(f.locationScore)
  )
}

function isSortId(v: unknown): v is SortId {
  return typeof v === 'string' && SORT_OPTIONS.some((o) => o.id === v)
}

function clampRange(
  selected: { min: number; max: number },
  bounds: { min: number; max: number },
): { min: number; max: number } {
  let min = Math.min(Math.max(selected.min, bounds.min), bounds.max)
  let max = Math.min(Math.max(selected.max, bounds.min), bounds.max)
  if (min > max) {
    min = bounds.min
    max = bounds.max
  }
  return { min, max }
}

function sanitizeFilters(raw: Filters, bounds: FilterBounds): Filters {
  return {
    states: raw.states,
    cities: raw.cities,
    price: clampRange(raw.price, bounds.price),
    yearBuilt: clampRange(raw.yearBuilt, bounds.yearBuilt),
    rentalYield: clampRange(raw.rentalYield, bounds.rentalYield),
    cashFlow: clampRange(raw.cashFlow, bounds.cashFlow),
    cashOnCash: clampRange(raw.cashOnCash, bounds.cashOnCash),
    locationScore: clampRange(raw.locationScore, bounds.locationScore),
  }
}

function loadHomeView(userId: string | undefined): HomeViewPersisted | null {
  if (!userId || typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(homeViewStorageKey(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { filters?: unknown; sortBy?: unknown }
    if (!isFiltersShape(parsed.filters)) return null
    return {
      filters: parsed.filters,
      sortBy: isSortId(parsed.sortBy) ? parsed.sortBy : 'added_desc',
    }
  } catch {
    return null
  }
}

function saveHomeView(userId: string | undefined, state: HomeViewPersisted): void {
  if (!userId || typeof window === 'undefined') return
  try {
    window.localStorage.setItem(homeViewStorageKey(userId), JSON.stringify(state))
  } catch {
    // Quota / private mode — ignore
  }
}

function compareNullable(
  a: number | undefined,
  b: number | undefined,
  dir: 1 | -1,
): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  return (a - b) * dir
}

function sortProperties(items: PortfolioItem[], sortBy: SortId): PortfolioItem[] {
  const copy = [...items]
  copy.sort((a, b) => {
    switch (sortBy) {
      case 'added_asc':
        return (a.added_at || '').localeCompare(b.added_at || '')
      case 'added_desc':
        return (b.added_at || '').localeCompare(a.added_at || '')
      case 'year_asc':
        return compareNullable(a.year_built, b.year_built, 1)
      case 'year_desc':
        return compareNullable(a.year_built, b.year_built, -1)
      case 'cashflow_asc':
        return compareNullable(a.monthly_cash_flow, b.monthly_cash_flow, 1)
      case 'cashflow_desc':
        return compareNullable(a.monthly_cash_flow, b.monthly_cash_flow, -1)
      case 'coc_desc':
        return compareNullable(a.cash_on_cash, b.cash_on_cash, -1)
      case 'price_asc':
        return compareNullable(a.price ?? a.predicted_value, b.price ?? b.predicted_value, 1)
      case 'price_desc':
        return compareNullable(a.price ?? a.predicted_value, b.price ?? b.predicted_value, -1)
      case 'views_desc':
        return compareNullable(a.app_view_count, b.app_view_count, -1)
      default:
        return 0
    }
  })
  return copy
}

function SortMenu({
  sortBy,
  onChange,
}: {
  sortBy: SortId
  onChange: (next: SortId) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const current = SORT_OPTIONS.find((o) => o.id === sortBy) ?? SORT_OPTIONS[0]

  useEffect(() => {
    if (!open) return
    function onPointer(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-white/95 px-3 py-2 text-sm font-medium shadow-sm backdrop-blur hover:bg-white"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <ArrowUpDown size={15} />
        {current.label}
        <ChevronDown size={14} className={clsx('text-muted transition', open && 'rotate-180')} />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 z-[1200] mt-1.5 max-h-80 w-64 overflow-y-auto rounded-xl border border-border bg-white py-1 shadow-lg"
        >
          {SORT_OPTIONS.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                role="option"
                aria-selected={option.id === sortBy}
                onClick={() => {
                  onChange(option.id)
                  setOpen(false)
                }}
                className={clsx(
                  'flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-surface',
                  option.id === sortBy && 'bg-primary/5 text-primary',
                )}
              >
                {option.label}
                {option.id === sortBy && <Check size={14} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function HomePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const isAdmin = isAdminUser(user)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
  })

  const properties = data?.properties ?? []

  async function removeCatalogProperty(item: PortfolioItem) {
    const propertyId = item.id
    if (!propertyId) return
    if (
      !window.confirm(
        `Remove “${item.address || propertyId}” from the harvest Postgres catalog? End users will no longer see it.`,
      )
    ) {
      return
    }
    setRemovingId(propertyId)
    try {
      await apiFetch(`/api/admin/properties/${encodeURIComponent(propertyId)}`, {
        method: 'DELETE',
      })
      await queryClient.invalidateQueries({ queryKey: ['portfolio'] })
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Could not remove property')
    } finally {
      setRemovingId(null)
    }
  }

  const filterBounds: FilterBounds = useMemo(() => {
    const currentYear = new Date().getFullYear()
    return {
      price: {
        min: PRICE_SLIDER_MIN,
        max: PRICE_SLIDER_MAX,
        step: PRICE_SLIDER_STEP,
      },
      yearBuilt: {
        min: YEAR_BUILT_MIN,
        max: currentYear,
        step: 1,
      },
      rentalYield: niceRange(
        properties.map((p) => p.rental_yield),
        { min: 0, max: 20 },
      ),
      cashFlow: fixedStepRange(
        properties.map((p) => p.monthly_cash_flow),
        { fallbackMin: -2000, fallbackMax: 5000, step: CASH_FLOW_STEP },
      ),
      cashOnCash: fixedStepRange(
        properties.map((p) => p.cash_on_cash),
        { fallbackMin: -20, fallbackMax: 40, step: CASH_ON_CASH_STEP },
      ),
      locationScore: niceRange(
        properties.map((p) => p.location_score),
        { min: 0, max: 10 },
      ),
    }
  }, [properties])

  const [filters, setFilters] = useState<Filters | null>(() => null)
  const [sortBy, setSortBy] = useState<SortId>(() => loadHomeView(user?.id)?.sortBy ?? 'added_desc')
  const userId = user?.id
  const [viewUserId, setViewUserId] = useState<string | undefined>(userId)

  // Keep home view scoped to the signed-in user (React “adjust state when prop changes”).
  if (userId !== viewUserId) {
    setViewUserId(userId)
    setFilters(null)
    setSortBy(loadHomeView(userId)?.sortBy ?? 'added_desc')
  }

  useEffect(() => {
    if (filters != null || properties.length === 0) return
    const saved = loadHomeView(userId)
    if (saved) {
      setFilters(sanitizeFilters(saved.filters, filterBounds))
    } else {
      setFilters(defaultFilters(filterBounds))
    }
  }, [filterBounds, filters, properties.length, userId])

  useEffect(() => {
    if (filters == null || !userId) return
    saveHomeView(userId, { filters, sortBy })
  }, [filters, sortBy, userId])

  const activeFilters = filters ?? defaultFilters(filterBounds)

  const filtered = useMemo(
    () => applyFilters(properties, activeFilters, filterBounds),
    [properties, activeFilters, filterBounds],
  )

  const displayed = useMemo(
    () => sortProperties(filtered, sortBy),
    [filtered, sortBy],
  )

  const pinned = displayed.filter(
    (p) =>
      typeof p.latitude === 'number' &&
      typeof p.longitude === 'number' &&
      !Number.isNaN(p.latitude) &&
      !Number.isNaN(p.longitude),
  )

  const center: [number, number] =
    pinned.length > 0
      ? [pinned[0].latitude as number, pinned[0].longitude as number]
      : [39.5, -98.35]

  useEffect(() => {
    document.title = 'Home · CapEigen'
  }, [])

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Portfolio map</h1>
        <p className="mt-1 text-muted">
          Browse researched properties. Click a pin to open Individual Search.
        </p>
      </header>

      {isLoading && <p className="text-muted">Loading portfolio…</p>}
      {error && <p className="text-red-600">{(error as Error).message}</p>}

      {!isLoading && !error && (
        <PortfolioFilters
          filters={activeFilters}
          bounds={filterBounds}
          properties={properties}
          matchCount={filtered.length}
          onChange={setFilters}
          onReset={() => setFilters(defaultFilters(filterBounds))}
        />
      )}

      <div className="relative">
        <div className="overflow-hidden rounded-2xl border border-border shadow-sm">
          <MapContainer
            key={`${center[0]}-${center[1]}-${pinned.length}`}
            center={center}
            zoom={pinned.length ? 10 : 4}
            className="z-0 h-[420px] w-full"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {pinned.map((p) => (
              <Marker
                key={`${p.address}-${p.latitude}-${p.longitude}`}
                position={[p.latitude as number, p.longitude as number]}
              >
                <Popup>
                  <div className="space-y-1 text-sm">
                    <p className="font-semibold">{p.address}</p>
                    <p>Price: {money(p.price ?? p.predicted_value)}</p>
                    <p>Year built: {p.year_built != null ? p.year_built : '—'}</p>
                    <p>Rent: {money(p.rent)}/mo</p>
                    <p>Yield: {pct(p.rental_yield)}</p>
                    <p>Cash on cash: {pct(p.cash_on_cash)}</p>
                    <p>Views: {(p.app_view_count ?? 0).toLocaleString()}</p>
                    <p title={p.added_at ? new Date(p.added_at).toLocaleString() : undefined}>
                      Added: {formatAddedAt(p.added_at)}
                    </p>
                    <Link
                      className="text-primary underline"
                      to={propertySearchPath(p)}
                    >
                      Analyze
                    </Link>
                    {isAdmin && p.id && (
                      <button
                        type="button"
                        disabled={removingId === p.id}
                        onClick={() => void removeCatalogProperty(p)}
                        className="block text-red-700 underline disabled:opacity-60"
                      >
                        {removingId === p.id ? 'Removing…' : 'Remove'}
                      </button>
                    )}
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
        <div className="pointer-events-none absolute top-3 right-3 z-[1100]">
          <div className="pointer-events-auto">
            <SortMenu sortBy={sortBy} onChange={setSortBy} />
          </div>
        </div>
      </div>

      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-xl font-semibold">
            Properties ({filtered.length.toLocaleString()})
          </h2>
        </div>
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Address</th>
                <th className="px-3 py-2 font-medium">Added</th>
                <th className="px-3 py-2 font-medium">Price</th>
                <th className="px-3 py-2 font-medium">Rent</th>
                <th className="px-3 py-2 font-medium">Yield</th>
                <th className="px-3 py-2 font-medium">Year built</th>
                <th className="px-3 py-2 font-medium">Cash flow</th>
                <th className="px-3 py-2 font-medium">Cash on cash</th>
                <th className="px-3 py-2 font-medium">Score</th>
                <th className="px-3 py-2 font-medium">Views</th>
                {isAdmin && <th className="px-3 py-2 font-medium">Admin</th>}
              </tr>
            </thead>
            <tbody>
              {displayed.slice(0, 100).map((p) => (
                <tr key={p.id || p.address} className="border-t border-border">
                  <td className="px-3 py-2">
                    <Link
                      className="text-primary hover:underline"
                      to={propertySearchPath(p)}
                    >
                      {p.address}
                    </Link>
                  </td>
                  <td
                    className="px-3 py-2 whitespace-nowrap text-muted"
                    title={p.added_at ? new Date(p.added_at).toLocaleString() : undefined}
                  >
                    {formatAddedAt(p.added_at)}
                  </td>
                  <td className="px-3 py-2">{money(p.price ?? p.predicted_value)}</td>
                  <td className="px-3 py-2">{money(p.rent)}</td>
                  <td className="px-3 py-2">{pct(p.rental_yield)}</td>
                  <td className="px-3 py-2">
                    {p.year_built != null ? p.year_built : '—'}
                  </td>
                  <td className="px-3 py-2">{money(p.monthly_cash_flow)}</td>
                  <td className="px-3 py-2">{pct(p.cash_on_cash)}</td>
                  <td className="px-3 py-2">
                    {p.location_score != null ? Number(p.location_score).toFixed(1) : '—'}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {(p.app_view_count ?? 0).toLocaleString()}
                  </td>
                  {isAdmin && (
                    <td className="px-3 py-2">
                      {p.id ? (
                        <button
                          type="button"
                          disabled={removingId === p.id}
                          onClick={() => void removeCatalogProperty(p)}
                          className="rounded-lg border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          {removingId === p.id ? 'Removing…' : 'Remove'}
                        </button>
                      ) : (
                        '—'
                      )}
                    </td>
                  )}
                </tr>
              ))}
              {filtered.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={isAdmin ? 11 : 10} className="px-3 py-6 text-center text-muted">
                    No properties match the current filters. Widen a range or reset.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
