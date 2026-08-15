import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { Link } from 'react-router-dom'
import {
  fetchPortfolio,
  formatAddedAt,
  niceRange,
  propertySearchPath,
  rangeActive,
  type RangeBounds,
} from '../lib/portfolio'
import type { PortfolioItem } from '../lib/api'
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

type Filters = {
  states: string[]
  cities: string[]
  price: RangeBounds
  yearBuilt: RangeBounds
  rentalYield: RangeBounds
  cashFlow: RangeBounds
  locationScore: RangeBounds
}

function roundToStep(n: number, step: number): number {
  if (!Number.isFinite(step) || step <= 0) return n
  const decimals = Math.min((String(step).split('.')[1] || '').length, 8)
  return Number((Math.round(n / step) * step).toFixed(decimals))
}

function RangeFilter({
  label,
  bounds,
  value,
  onChange,
  format,
  step,
}: {
  label: string
  bounds: RangeBounds
  value: RangeBounds
  onChange: (next: RangeBounds) => void
  format: (n: number) => string
  step: number
}) {
  const disabled = bounds.max <= bounds.min
  const span = bounds.max - bounds.min || 1
  const leftPct = ((value.min - bounds.min) / span) * 100
  const rightPct = ((value.max - bounds.min) / span) * 100
  const gap = bounds.max - bounds.min > step ? step : 0
  const [dragging, setDragging] = useState<'min' | 'max' | null>(null)

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-text/90">{label}</span>
        <span className="text-xs text-muted">
          {format(value.min)} – {format(value.max)}
        </span>
      </div>
      <div className="relative h-6">
        <div className="pointer-events-none absolute top-1/2 h-1.5 w-full -translate-y-1/2 rounded-full bg-border" />
        <div
          className="pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary"
          style={{
            left: `${leftPct}%`,
            width: `${Math.max(rightPct - leftPct, 0)}%`,
          }}
        />
        <input
          type="range"
          className="dual-range absolute top-1/2 left-0 w-full -translate-y-1/2"
          style={{ zIndex: dragging === 'min' ? 5 : 3 }}
          min={bounds.min}
          max={bounds.max}
          step={step}
          disabled={disabled}
          value={value.min}
          aria-label={`${label} minimum`}
          onPointerDown={(e) => {
            setDragging('min')
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerUp={() => setDragging(null)}
          onChange={(e) => {
            const min = Math.min(roundToStep(Number(e.target.value), step), value.max - gap)
            onChange({ min, max: value.max })
          }}
        />
        <input
          type="range"
          className="dual-range absolute top-1/2 left-0 w-full -translate-y-1/2"
          style={{ zIndex: dragging === 'max' ? 5 : 4 }}
          min={bounds.min}
          max={bounds.max}
          step={step}
          disabled={disabled}
          value={value.max}
          aria-label={`${label} maximum`}
          onPointerDown={(e) => {
            setDragging('max')
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerUp={() => setDragging(null)}
          onChange={(e) => {
            const max = Math.max(roundToStep(Number(e.target.value), step), value.min + gap)
            onChange({ min: value.min, max })
          }}
        />
      </div>
    </div>
  )
}

function applyFilters(properties: PortfolioItem[], filters: Filters, bounds: {
  price: RangeBounds
  yearBuilt: RangeBounds
  rentalYield: RangeBounds
  cashFlow: RangeBounds
  locationScore: RangeBounds
}): PortfolioItem[] {
  return properties.filter((p) => {
    if (filters.states.length > 0 && !filters.states.includes(p.state_code || '')) {
      return false
    }
    if (filters.cities.length > 0 && !filters.cities.includes(p.market_city || '')) {
      return false
    }

    const price = p.price ?? p.predicted_value
    if (
      rangeActive(filters.price, bounds.price) &&
      (price == null || price < filters.price.min || price > filters.price.max)
    ) {
      return false
    }

    if (rangeActive(filters.yearBuilt, bounds.yearBuilt)) {
      // Unknown year stays visible (matches Streamlit year_built mask).
      if (
        p.year_built != null &&
        (p.year_built < filters.yearBuilt.min || p.year_built > filters.yearBuilt.max)
      ) {
        return false
      }
    }

    if (
      rangeActive(filters.rentalYield, bounds.rentalYield) &&
      (p.rental_yield == null ||
        p.rental_yield < filters.rentalYield.min ||
        p.rental_yield > filters.rentalYield.max)
    ) {
      return false
    }

    if (
      rangeActive(filters.cashFlow, bounds.cashFlow) &&
      (p.monthly_cash_flow == null ||
        p.monthly_cash_flow < filters.cashFlow.min ||
        p.monthly_cash_flow > filters.cashFlow.max)
    ) {
      return false
    }

    if (
      rangeActive(filters.locationScore, bounds.locationScore) &&
      (p.location_score == null ||
        p.location_score < filters.locationScore.min ||
        p.location_score > filters.locationScore.max)
    ) {
      return false
    }

    return true
  })
}

export function HomePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
  })

  const properties = data?.properties ?? []

  const filterBounds = useMemo(() => {
    const currentYear = new Date().getFullYear()
    return {
      price: niceRange(
        properties.map((p) => p.price ?? p.predicted_value),
        { min: 0, max: 1_000_000 },
      ),
      yearBuilt: niceRange(
        properties.map((p) => p.year_built),
        { min: 1900, max: currentYear },
      ),
      rentalYield: niceRange(
        properties.map((p) => p.rental_yield),
        { min: 0, max: 20 },
      ),
      cashFlow: niceRange(
        properties.map((p) => p.monthly_cash_flow),
        { min: -2000, max: 5000 },
      ),
      locationScore: niceRange(
        properties.map((p) => p.location_score),
        { min: 0, max: 10 },
      ),
    }
  }, [properties])

  const stateOptions = useMemo(
    () =>
      [...new Set(properties.map((p) => p.state_code).filter(Boolean) as string[])].sort(),
    [properties],
  )
  const cityOptions = useMemo(
    () =>
      [
        ...new Set(properties.map((p) => p.market_city).filter(Boolean) as string[]),
      ].sort(),
    [properties],
  )

  const [filters, setFilters] = useState<Filters | null>(null)

  useEffect(() => {
    if (filters != null || properties.length === 0) return
    setFilters({
      states: [],
      cities: [],
      price: { min: filterBounds.price.min, max: filterBounds.price.max },
      yearBuilt: { min: filterBounds.yearBuilt.min, max: filterBounds.yearBuilt.max },
      rentalYield: { min: filterBounds.rentalYield.min, max: filterBounds.rentalYield.max },
      cashFlow: { min: filterBounds.cashFlow.min, max: filterBounds.cashFlow.max },
      locationScore: {
        min: filterBounds.locationScore.min,
        max: filterBounds.locationScore.max,
      },
    })
  }, [filterBounds, filters, properties.length])

  const activeFilters = filters ?? {
    states: [],
    cities: [],
    price: { min: filterBounds.price.min, max: filterBounds.price.max },
    yearBuilt: { min: filterBounds.yearBuilt.min, max: filterBounds.yearBuilt.max },
    rentalYield: { min: filterBounds.rentalYield.min, max: filterBounds.rentalYield.max },
    cashFlow: { min: filterBounds.cashFlow.min, max: filterBounds.cashFlow.max },
    locationScore: {
      min: filterBounds.locationScore.min,
      max: filterBounds.locationScore.max,
    },
  }

  const filtered = useMemo(
    () => applyFilters(properties, activeFilters, filterBounds),
    [properties, activeFilters, filterBounds],
  )

  const pinned = filtered.filter(
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

  function resetFilters() {
    setFilters({
      states: [],
      cities: [],
      price: { min: filterBounds.price.min, max: filterBounds.price.max },
      yearBuilt: { min: filterBounds.yearBuilt.min, max: filterBounds.yearBuilt.max },
      rentalYield: { min: filterBounds.rentalYield.min, max: filterBounds.rentalYield.max },
      cashFlow: { min: filterBounds.cashFlow.min, max: filterBounds.cashFlow.max },
      locationScore: {
        min: filterBounds.locationScore.min,
        max: filterBounds.locationScore.max,
      },
    })
  }

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
        <section className="space-y-4 rounded-2xl border border-border bg-white/90 p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-lg font-semibold">Filters</h2>
              <p className="text-sm text-muted">
                Showing {filtered.length.toLocaleString()} of{' '}
                {properties.length.toLocaleString()} properties
              </p>
            </div>
            <button
              type="button"
              onClick={resetFilters}
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
            >
              Reset filters
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="block text-sm">
              <span className="font-medium text-text/90">State</span>
              <select
                multiple
                value={activeFilters.states}
                onChange={(e) =>
                  setFilters({
                    ...activeFilters,
                    states: Array.from(e.target.selectedOptions, (o) => o.value),
                  })
                }
                className="mt-1 h-24 w-full rounded-lg border border-border bg-white px-2 py-1.5 outline-none focus:border-primary"
              >
                {stateOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="font-medium text-text/90">City</span>
              <select
                multiple
                value={activeFilters.cities}
                onChange={(e) =>
                  setFilters({
                    ...activeFilters,
                    cities: Array.from(e.target.selectedOptions, (o) => o.value),
                  })
                }
                className="mt-1 h-24 w-full rounded-lg border border-border bg-white px-2 py-1.5 outline-none focus:border-primary"
              >
                {cityOptions.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-sm text-muted sm:col-span-2 lg:col-span-1 lg:self-end">
              Hold Ctrl/Cmd to select multiple states or cities. Leave empty for all.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <RangeFilter
              label="Price"
              bounds={filterBounds.price}
              value={activeFilters.price}
              step={filterBounds.price.step}
              format={(n) => money(n)}
              onChange={(price) => setFilters({ ...activeFilters, price })}
            />
            <RangeFilter
              label="Year built"
              bounds={filterBounds.yearBuilt}
              value={activeFilters.yearBuilt}
              step={filterBounds.yearBuilt.step}
              format={(n) => String(Math.round(n))}
              onChange={(yearBuilt) => setFilters({ ...activeFilters, yearBuilt })}
            />
            <RangeFilter
              label="Rental yield"
              bounds={filterBounds.rentalYield}
              value={activeFilters.rentalYield}
              step={filterBounds.rentalYield.step}
              format={(n) => pct(n)}
              onChange={(rentalYield) => setFilters({ ...activeFilters, rentalYield })}
            />
            <RangeFilter
              label="Monthly cash flow"
              bounds={filterBounds.cashFlow}
              value={activeFilters.cashFlow}
              step={filterBounds.cashFlow.step}
              format={(n) => money(n)}
              onChange={(cashFlow) => setFilters({ ...activeFilters, cashFlow })}
            />
            <RangeFilter
              label="Location score"
              bounds={filterBounds.locationScore}
              value={activeFilters.locationScore}
              step={filterBounds.locationScore.step}
              format={(n) => n.toFixed(1)}
              onChange={(locationScore) => setFilters({ ...activeFilters, locationScore })}
            />
          </div>
        </section>
      )}

      <div className="overflow-hidden rounded-2xl border border-border shadow-sm">
        <MapContainer
          key={`${center[0]}-${center[1]}-${pinned.length}`}
          center={center}
          zoom={pinned.length ? 10 : 4}
          className="h-[420px] w-full"
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
                  <p title={p.added_at ? new Date(p.added_at).toLocaleString() : undefined}>
                    Added: {formatAddedAt(p.added_at)}
                  </p>
                  <Link
                    className="text-primary underline"
                    to={propertySearchPath(p)}
                  >
                    Analyze
                  </Link>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>

      <section>
        <h2 className="mb-3 font-display text-xl font-semibold">
          Properties ({filtered.length.toLocaleString()})
        </h2>
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
                <th className="px-3 py-2 font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 100).map((p) => (
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
                  <td className="px-3 py-2">
                    {p.location_score != null ? Number(p.location_score).toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-muted">
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
