import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { Link } from 'react-router-dom'
import { apiFetch, type PortfolioItem } from '../lib/api'
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

export function HomePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => apiFetch<{ properties: PortfolioItem[]; count: number }>('/api/portfolio'),
  })

  const pinned =
    data?.properties.filter(
      (p) =>
        typeof p.latitude === 'number' &&
        typeof p.longitude === 'number' &&
        !Number.isNaN(p.latitude) &&
        !Number.isNaN(p.longitude),
    ) ?? []

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

      <div className="overflow-hidden rounded-2xl border border-border shadow-sm">
        <MapContainer center={center} zoom={pinned.length ? 10 : 4} className="h-[420px] w-full">
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
          Properties ({data?.count ?? 0})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Address</th>
                <th className="px-3 py-2 font-medium">Price</th>
                <th className="px-3 py-2 font-medium">Rent</th>
                <th className="px-3 py-2 font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {(data?.properties ?? []).slice(0, 50).map((p) => (
                <tr key={p.address} className="border-t border-border">
                  <td className="px-3 py-2">
                    <Link
                      className="text-primary hover:underline"
                      to={`/search?address=${encodeURIComponent(p.address || '')}`}
                    >
                      {p.address}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{money(Number(p.price ?? p.predicted_value))}</td>
                  <td className="px-3 py-2">{money(Number(p.rent))}</td>
                  <td className="px-3 py-2">
                    {p.location_score != null ? Number(p.location_score).toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
