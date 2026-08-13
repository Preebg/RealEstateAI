import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { Link } from 'react-router-dom'
import {
  fetchPortfolio,
  numericBounds,
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
  return `$${Math.round(n).toLocaleString()}`
}

function pct(n?: number, digits = 1) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(digits)}%`
}

type Filters = {
  states: string[]
  cities: string[]
  price: RangeBounds
  homeAge: RangeBounds
  rentalYield: RangeBounds
  cashFlow: RangeBounds
  locationScore: RangeBounds
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
  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-text/90">{label}</span>
        <span className="text-xs text-muted">
          {format(value.min)} – {format(value.max)}
        </span>
      </div>
      <label className="block">
        <span className="sr-only">{label} minimum</span>
        <input
          type="range"
          min={bounds.min}
          max={bounds.max}
          step={step}
          disabled={disabled}
          value={value.min}
          onChange={(e) => {
            const min = Number(e.target.value)
            onChange({ min: Math.min(min, value.max), max: value.max })
          }}
          className="w-full accent-primary disabled:opacity-40"
        />
      </label>
      <label className="block">
        <span className="sr-only">{label} maximum</span>
        <input
          type="range"
          min={bounds.min}
          max={bounds.max}
          step={step}
          disabled={disabled}
          value={value.max}
          onChange={(e) => {
            const max = Number(e.target.value)
            onChange({ min: value.min, max: Math.max(max, value.min) })
          }}
          className="w-full accent-primary disabled:opacity-40"
        />
      </label>
    </div>
  )
}

function applyFilters(properties: PortfolioItem[], filters: Filters, bounds: {
  price: RangeBounds
  homeAge: RangeBounds
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

    if (rangeActive(filters.homeAge, bounds.homeAge)) {
      // Unknown age stays visible (matches Streamlit year_built mask).
      if (
        p.home_age != null &&
        (p.home_age < filters.homeAge.min || p.home_age > filters.homeAge.max)
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
    return {
      price: numericBounds(
        properties.map((p) => p.price ?? p.predicted_value),
        { min: 0, max: 1_000_000 },
      ),
      homeAge: numericBounds(
        properties.map((p) => p.home_age),
        { min: 0, max: 100 },
      ),
      rentalYield: numericBounds(
        properties.map((p) => p.rental_yield),
        { min: 0, max: 20 },
      ),
      cashFlow: numericBounds(
        properties.map((p) => p.monthly_cash_flow),
        { min: -2000, max: 5000 },
      ),
      locationScore: numericBounds(
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
      price: { ...filterBounds.price },
      homeAge: { ...filterBounds.homeAge },
      rentalYield: { ...filterBounds.rentalYield },
      cashFlow: { ...filterBounds.cashFlow },
      locationScore: { ...filterBounds.locationScore },
    })
  }, [filterBounds, filters, properties.length])

  const activeFilters = filters ?? {
    states: [],
    cities: [],
    price: filterBounds.price,
    homeAge: filterBounds.homeAge,
    rentalYield: filterBounds.rentalYield,
    cashFlow: filterBounds.cashFlow,
    locationScore: filterBounds.locationScore,
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
      price: { ...filterBounds.price },
      homeAge: { ...filterBounds.homeAge },
      rentalYield: { ...filterBounds.rentalYield },
      cashFlow: { ...filterBounds.cashFlow },
      locationScore: { ...filterBounds.locationScore },
    })
  }

  const priceStep = Math.max(
    1000,
    Math.round((filterBounds.price.max - filterBounds.price.min) / 100) || 1000,
  )
  const yieldStep = Math.max(
    0.1,
    Number(((filterBounds.rentalYield.max - filterBounds.rentalYield.min) / 100).toFixed(2)) ||
      0.1,
  )
  const cashStep = Math.max(
    50,
    Math.round((filterBounds.cashFlow.max - filterBounds.cashFlow.min) / 100) || 50,
  )
  const locationStep = Math.max(
    0.1,
    Number(
      ((filterBounds.locationScore.max - filterBounds.locationScore.min) / 20).toFixed(1),
    ) || 0.1,
  )

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
              step={priceStep}
              format={(n) => money(n)}
              onChange={(price) => setFilters({ ...activeFilters, price })}
            />
            <RangeFilter
              label="Home age (years)"
              bounds={filterBounds.homeAge}
              value={activeFilters.homeAge}
              step={1}
              format={(n) => `${Math.round(n)} yrs`}
              onChange={(homeAge) => setFilters({ ...activeFilters, homeAge })}
            />
            <RangeFilter
              label="Rental yield"
              bounds={filterBounds.rentalYield}
              value={activeFilters.rentalYield}
              step={yieldStep}
              format={(n) => pct(n)}
              onChange={(rentalYield) => setFilters({ ...activeFilters, rentalYield })}
            />
            <RangeFilter
              label="Monthly cash flow"
              bounds={filterBounds.cashFlow}
              value={activeFilters.cashFlow}
              step={cashStep}
              format={(n) => money(n)}
              onChange={(cashFlow) => setFilters({ ...activeFilters, cashFlow })}
            />
            <RangeFilter
              label="Location score"
              bounds={filterBounds.locationScore}
              value={activeFilters.locationScore}
              step={locationStep}
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
                  <p>Rent: {money(p.rent)}/mo</p>
                  <p>Yield: {pct(p.rental_yield)}</p>
                  <Link
                    className="text-primary underline"
                    to={`/search?address=${encodeURIComponent(p.address || '')}`}
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
                <th className="px-3 py-2 font-medium">Price</th>
                <th className="px-3 py-2 font-medium">Rent</th>
                <th className="px-3 py-2 font-medium">Yield</th>
                <th className="px-3 py-2 font-medium">Age</th>
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
                      to={`/search?address=${encodeURIComponent(p.address || '')}`}
                    >
                      {p.address}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{money(p.price ?? p.predicted_value)}</td>
                  <td className="px-3 py-2">{money(p.rent)}</td>
                  <td className="px-3 py-2">{pct(p.rental_yield)}</td>
                  <td className="px-3 py-2">
                    {p.home_age != null ? `${p.home_age} yrs` : '—'}
                  </td>
                  <td className="px-3 py-2">{money(p.monthly_cash_flow)}</td>
                  <td className="px-3 py-2">
                    {p.location_score != null ? Number(p.location_score).toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-muted">
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
