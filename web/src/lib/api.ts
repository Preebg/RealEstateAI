import { supabase } from './supabase'

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || ''

async function authHeader(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const auth = await authHeader()
  Object.entries(auth).forEach(([k, v]) => headers.set(k, v))

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const err = await res.json()
      detail = err.detail || JSON.stringify(err)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/pdf')) {
    return (await res.blob()) as T
  }
  return res.json() as Promise<T>
}

export type AnalysisJob = {
  job_id: string
  status: string
  property_data: Record<string, unknown> | null
  deferred_tasks: string[]
  deferred_tasks_total: number
  completed_tasks: string[]
  error: string | null
  address?: string | null
  from_kb?: boolean
}

export type FinanceResult = {
  finance: Record<string, number | Record<string, number>>
  quantum_requeued: boolean
}

export type PortfolioItem = {
  address?: string
  price?: number
  predicted_value?: number
  latitude?: number
  longitude?: number
  beds?: number
  baths?: number
  sqft?: number
  location_score?: number
  rent?: number
  strategy?: string
  id?: string
}
