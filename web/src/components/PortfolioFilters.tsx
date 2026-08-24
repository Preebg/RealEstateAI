import { useEffect, useMemo, useState } from 'react'
import { SlidersHorizontal, X } from 'lucide-react'
import { clsx } from 'clsx'
import type { PortfolioItem } from '../lib/api'
import {
  CASH_FLOW_STEP,
  CASH_ON_CASH_STEP,
  PRICE_SLIDER_MAX,
  PRICE_SLIDER_STEP,
  rangeActive,
  type RangeBounds,
  type RangeSpec,
} from '../lib/portfolio'

export type Filters = {
  states: string[]
  cities: string[]
  price: RangeBounds
  yearBuilt: RangeBounds
  rentalYield: RangeBounds
  cashFlow: RangeBounds
  cashOnCash: RangeBounds
  locationScore: RangeBounds
}

export type FilterBounds = {
  price: RangeSpec
  yearBuilt: RangeSpec
  rentalYield: RangeSpec
  cashFlow: RangeSpec
  cashOnCash: RangeSpec
  locationScore: RangeSpec
}

export function defaultFilters(bounds: FilterBounds): Filters {
  return {
    states: [],
    cities: [],
    price: { min: bounds.price.min, max: bounds.price.max },
    yearBuilt: { min: bounds.yearBuilt.min, max: bounds.yearBuilt.max },
    rentalYield: { min: bounds.rentalYield.min, max: bounds.rentalYield.max },
    cashFlow: { min: bounds.cashFlow.min, max: bounds.cashFlow.max },
    cashOnCash: { min: bounds.cashOnCash.min, max: bounds.cashOnCash.max },
    locationScore: { min: bounds.locationScore.min, max: bounds.locationScore.max },
  }
}

export function countActiveFilters(filters: Filters, bounds: FilterBounds): number {
  let n = 0
  if (filters.states.length > 0) n += 1
  if (filters.cities.length > 0) n += 1
  if (rangeActive(filters.price, bounds.price)) n += 1
  if (rangeActive(filters.yearBuilt, bounds.yearBuilt)) n += 1
  if (rangeActive(filters.rentalYield, bounds.rentalYield)) n += 1
  if (rangeActive(filters.cashFlow, bounds.cashFlow)) n += 1
  if (rangeActive(filters.cashOnCash, bounds.cashOnCash)) n += 1
  if (rangeActive(filters.locationScore, bounds.locationScore)) n += 1
  return n
}

function roundToStep(n: number, step: number): number {
  if (!Number.isFinite(step) || step <= 0) return n
  const decimals = Math.min((String(step).split('.')[1] || '').length, 8)
  return Number((Math.round(n / step) * step).toFixed(decimals))
}

function money(n?: number) {
  if (n == null || Number.isNaN(n)) return '—'
  const rounded = Math.round(n)
  if (rounded < 0) return `-$${Math.abs(rounded).toLocaleString()}`
  return `$${rounded.toLocaleString()}`
}

function compactMoney(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1000) {
    const k = n / 1000
    const text = Number.isInteger(k) ? String(k) : k.toFixed(0)
    return n < 0 ? `-$${text}k` : `$${text}k`
  }
  return money(n)
}

function pct(n?: number, digits = 1) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(digits)}%`
}

function itemPrice(p: PortfolioItem): number | undefined {
  return p.price ?? p.predicted_value
}

/** At the slider cap, treat max as open-ended (400k+), like Zillow. */
function effectivePriceMax(selectedMax: number, boundMax: number): number {
  if (selectedMax >= boundMax - 1e-6) return Number.POSITIVE_INFINITY
  return selectedMax
}

export function applyFilters(
  properties: PortfolioItem[],
  filters: Filters,
  bounds: FilterBounds,
): PortfolioItem[] {
  const priceMax = effectivePriceMax(filters.price.max, bounds.price.max)
  const priceMinActive = filters.price.min > bounds.price.min + 1e-6
  const priceMaxActive = Number.isFinite(priceMax)

  return properties.filter((p) => {
    if (filters.states.length > 0 && !filters.states.includes(p.state_code || '')) {
      return false
    }
    if (filters.cities.length > 0 && !filters.cities.includes(p.market_city || '')) {
      return false
    }

    const price = itemPrice(p)
    if (priceMinActive || priceMaxActive) {
      if (price == null || price < filters.price.min || price > priceMax) {
        return false
      }
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
      rangeActive(filters.cashOnCash, bounds.cashOnCash) &&
      (p.cash_on_cash == null ||
        p.cash_on_cash < filters.cashOnCash.min ||
        p.cash_on_cash > filters.cashOnCash.max)
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

function buildHistogram(values: number[], bounds: RangeBounds, buckets = 20): number[] {
  const counts = Array.from({ length: buckets }, () => 0)
  const span = bounds.max - bounds.min || 1
  const width = span / buckets
  for (const v of values) {
    if (!Number.isFinite(v)) continue
    let i = Math.floor((v - bounds.min) / width)
    if (i < 0) continue
    if (i >= buckets) i = buckets - 1
    counts[i] += 1
  }
  return counts
}

function PriceHistogram({
  prices,
  bounds,
  value,
  step,
  onChange,
}: {
  prices: number[]
  bounds: RangeBounds
  value: RangeBounds
  step: number
  onChange: (next: RangeBounds) => void
}) {
  const buckets = 20
  const counts = useMemo(() => buildHistogram(prices, bounds, buckets), [prices, bounds])
  const peak = Math.max(1, ...counts)
  const span = bounds.max - bounds.min || 1
  const width = span / buckets

  return (
    <div className="flex h-14 items-end gap-px" role="img" aria-label="Price distribution">
      {counts.map((count, i) => {
        const bucketMin = bounds.min + i * width
        const bucketMax = i === buckets - 1 ? bounds.max : bounds.min + (i + 1) * width
        const selected = bucketMax > value.min && bucketMin < value.max
        const height = count === 0 ? 4 : Math.max(6, (count / peak) * 100)
        const maxLabel =
          i === buckets - 1 && bounds.max >= PRICE_SLIDER_MAX - 1e-6
            ? `${compactMoney(bucketMin)}+`
            : `${compactMoney(bucketMin)}–${compactMoney(bucketMax)}`
        return (
          <button
            key={i}
            type="button"
            title={`${maxLabel} · ${count.toLocaleString()} ${count === 1 ? 'home' : 'homes'}`}
            aria-label={`${maxLabel}, ${count} properties`}
            onClick={() =>
              onChange({
                min: roundToStep(bucketMin, step),
                max: roundToStep(bucketMax, step),
              })
            }
            className={clsx(
              'min-w-0 flex-1 rounded-t-[2px] transition-colors',
              selected ? 'bg-primary/85 hover:bg-primary' : 'bg-border hover:bg-muted/40',
            )}
            style={{ height: `${height}%` }}
          />
        )
      })}
    </div>
  )
}

/** Draft text while typing; round/clamp only on blur or Enter so large steps don't fight keystrokes. */
function RangeNumberField({
  value,
  disabled,
  ariaLabel,
  onCommit,
}: {
  value: number
  disabled?: boolean
  ariaLabel: string
  onCommit: (n: number) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const display = draft ?? String(value)

  function commit(raw: string) {
    const trimmed = raw.trim()
    if (trimmed === '' || trimmed === '-' || trimmed === '.' || trimmed === '-.') {
      setDraft(null)
      return
    }
    const n = Number(trimmed)
    if (Number.isFinite(n)) onCommit(n)
    setDraft(null)
  }

  return (
    <input
      type="text"
      inputMode="decimal"
      className="mt-1 w-full rounded-lg border border-border bg-card px-2 py-1.5 text-sm text-text outline-none focus:border-primary"
      disabled={disabled}
      value={display}
      aria-label={ariaLabel}
      onFocus={() => setDraft(String(value))}
      onChange={(e) => {
        const next = e.target.value
        if (next === '' || /^-?\d*\.?\d*$/.test(next)) setDraft(next)
      }}
      onBlur={() => {
        if (draft != null) commit(draft)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          ;(e.target as HTMLInputElement).blur()
        } else if (e.key === 'Escape') {
          setDraft(null)
          ;(e.target as HTMLInputElement).blur()
        }
      }}
    />
  )
}

function RangeFilter({
  label,
  bounds,
  value,
  onChange,
  format,
  step,
  histogram,
  openEndedMax = false,
}: {
  label: string
  bounds: RangeSpec
  value: RangeBounds
  onChange: (next: RangeBounds) => void
  format: (n: number) => string
  step: number
  histogram?: number[]
  openEndedMax?: boolean
}) {
  const disabled = bounds.max <= bounds.min
  const span = bounds.max - bounds.min || 1
  const leftPct = ((value.min - bounds.min) / span) * 100
  const rightPct = ((value.max - bounds.min) / span) * 100
  const gap = bounds.max - bounds.min > step ? step : 0
  const [dragging, setDragging] = useState<'min' | 'max' | null>(null)
  const atOpenMax = openEndedMax && value.max >= bounds.max - 1e-6

  function setMin(raw: number) {
    const min = Math.min(roundToStep(raw, step), value.max - gap)
    onChange({ min: Math.max(min, bounds.min), max: value.max })
  }

  function setMax(raw: number) {
    const max = Math.max(roundToStep(raw, step), value.min + gap)
    onChange({ min: value.min, max: Math.min(max, bounds.max) })
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-text/90">{label}</span>
        <span className="text-xs text-muted">
          {format(value.min)} – {atOpenMax ? `${format(value.max)}+` : format(value.max)}
        </span>
      </div>
      {histogram && (
        <PriceHistogram
          prices={histogram}
          bounds={bounds}
          value={value}
          step={step}
          onChange={onChange}
        />
      )}
      <div className={clsx('relative', histogram ? '-mt-1 h-5' : 'h-6')}>
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
          onChange={(e) => setMin(Number(e.target.value))}
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
          onChange={(e) => setMax(Number(e.target.value))}
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-xs text-muted">
          Min
          <RangeNumberField
            value={value.min}
            disabled={disabled}
            ariaLabel={`${label} minimum value`}
            onCommit={setMin}
          />
        </label>
        <label className="block text-xs text-muted">
          Max
          <RangeNumberField
            value={value.max}
            disabled={disabled}
            ariaLabel={`${label} maximum value`}
            onCommit={setMax}
          />
        </label>
      </div>
    </div>
  )
}

function MultiCheckList({
  label,
  options,
  selected,
  onChange,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const [query, setQuery] = useState('')
  const filtered = options.filter((o) => o.toLowerCase().includes(query.trim().toLowerCase()))

  function toggle(option: string) {
    if (selected.includes(option)) {
      onChange(selected.filter((s) => s !== option))
    } else {
      onChange([...selected, option])
    }
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-text/90">{label}</span>
        {selected.length > 0 && (
          <button
            type="button"
            className="text-xs text-primary hover:underline"
            onClick={() => onChange([])}
          >
            Clear
          </button>
        )}
      </div>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={`Search ${label.toLowerCase()}…`}
        className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm outline-none focus:border-primary"
      />
      <div className="max-h-36 overflow-y-auto rounded-lg border border-border">
        {filtered.length === 0 && (
          <p className="px-2.5 py-2 text-xs text-muted">No matches</p>
        )}
        {filtered.map((option) => {
          const checked = selected.includes(option)
          return (
            <label
              key={option}
              className={clsx(
                'flex cursor-pointer items-center gap-2 px-2.5 py-1.5 hover:bg-surface',
                checked && 'bg-primary/5',
              )}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(option)}
                className="accent-primary"
              />
              <span>{option}</span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

export function PortfolioFilters({
  filters,
  bounds,
  properties,
  matchCount,
  onChange,
  onReset,
}: {
  filters: Filters
  bounds: FilterBounds
  properties: PortfolioItem[]
  matchCount: number
  onChange: (next: Filters) => void
  onReset: () => void
}) {
  const [open, setOpen] = useState(false)
  const activeCount = countActiveFilters(filters, bounds)
  const prices = useMemo(
    () =>
      properties
        .map((p) => itemPrice(p))
        .filter((n): n is number => n != null && Number.isFinite(n)),
    [properties],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open])

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={clsx(
            'inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium shadow-sm transition',
            activeCount > 0
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border bg-card hover:bg-surface',
          )}
          aria-expanded={open}
          aria-haspopup="dialog"
        >
          <SlidersHorizontal size={16} />
          Filters
          {activeCount > 0 && (
            <span className="rounded-full bg-primary px-1.5 py-0.5 text-[11px] font-semibold leading-none text-white">
              {activeCount}
            </span>
          )}
        </button>
        <p className="text-sm text-muted">
          Showing {matchCount.toLocaleString()} of {properties.length.toLocaleString()} properties
        </p>
      </div>

      {open && (
        <div className="fixed inset-0 z-[1200]">
          <button
            type="button"
            className="absolute inset-0 bg-black/35"
            aria-label="Close filters"
            onClick={() => setOpen(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="portfolio-filters-title"
            className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-card shadow-2xl"
          >
            <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <h2 id="portfolio-filters-title" className="font-display text-lg font-semibold">
                  Filters
                </h2>
                <p className="text-xs text-muted">
                  {matchCount.toLocaleString()} match
                  {matchCount === 1 ? '' : 'es'} · drag sliders or type exact values
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onReset}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-text"
                  aria-label="Close filters"
                >
                  <X size={18} />
                </button>
              </div>
            </header>

            <div className="flex-1 space-y-8 overflow-y-auto px-5 py-5">
              <section className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Location</h3>
                <div className="grid gap-4 sm:grid-cols-2">
                  <MultiCheckList
                    label="State"
                    options={[
                      ...new Set(
                        properties.map((p) => p.state_code).filter(Boolean) as string[],
                      ),
                    ].sort()}
                    selected={filters.states}
                    onChange={(states) => onChange({ ...filters, states })}
                  />
                  <MultiCheckList
                    label="City"
                    options={[
                      ...new Set(
                        properties.map((p) => p.market_city).filter(Boolean) as string[],
                      ),
                    ].sort()}
                    selected={filters.cities}
                    onChange={(cities) => onChange({ ...filters, cities })}
                  />
                </div>
              </section>

              <section className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Purchase price</h3>
                <RangeFilter
                  label="Purchase price"
                  bounds={bounds.price}
                  value={filters.price}
                  step={PRICE_SLIDER_STEP}
                  format={(n) => money(n)}
                  histogram={prices}
                  openEndedMax
                  onChange={(price) => onChange({ ...filters, price })}
                />
                <p className="text-xs text-muted">
                  Slider tops out at {money(PRICE_SLIDER_MAX)}. Leave the max at the cap to include
                  homes above that price.
                </p>
              </section>

              <section className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Property</h3>
                <RangeFilter
                  label="Year built"
                  bounds={bounds.yearBuilt}
                  value={filters.yearBuilt}
                  step={1}
                  format={(n) => String(Math.round(n))}
                  onChange={(yearBuilt) => onChange({ ...filters, yearBuilt })}
                />
                <RangeFilter
                  label="Location score"
                  bounds={bounds.locationScore}
                  value={filters.locationScore}
                  step={bounds.locationScore.step}
                  format={(n) => n.toFixed(1)}
                  onChange={(locationScore) => onChange({ ...filters, locationScore })}
                />
              </section>

              <section className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Returns</h3>
                <RangeFilter
                  label="Monthly cash flow"
                  bounds={bounds.cashFlow}
                  value={filters.cashFlow}
                  step={CASH_FLOW_STEP}
                  format={(n) => money(n)}
                  onChange={(cashFlow) => onChange({ ...filters, cashFlow })}
                />
                <RangeFilter
                  label="Cash on cash"
                  bounds={bounds.cashOnCash}
                  value={filters.cashOnCash}
                  step={CASH_ON_CASH_STEP}
                  format={(n) => pct(n)}
                  onChange={(cashOnCash) => onChange({ ...filters, cashOnCash })}
                />
                <RangeFilter
                  label="Rental yield"
                  bounds={bounds.rentalYield}
                  value={filters.rentalYield}
                  step={bounds.rentalYield.step}
                  format={(n) => pct(n)}
                  onChange={(rentalYield) => onChange({ ...filters, rentalYield })}
                />
              </section>
            </div>

            <footer className="border-t border-border px-5 py-4">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-hover"
              >
                Show {matchCount.toLocaleString()} properties
              </button>
            </footer>
          </aside>
        </div>
      )}
    </>
  )
}
