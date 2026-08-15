import { supabase } from './supabase'

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || ''

async function authHeader(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function apiMisconfiguredMessage(): string {
  if (import.meta.env.PROD && !API_BASE) {
    return (
      'API is not configured. Set VITE_API_URL in Netlify to your FastAPI base URL ' +
      '(e.g. https://your-api.example.com), then redeploy the site.'
    )
  }
  return (
    'API returned HTML instead of JSON. Is the FastAPI server running, and is ' +
    'VITE_API_URL pointing at it? Locally leave VITE_API_URL empty and use the Vite /api proxy.'
  )
}

async function readJsonOrThrow(res: Response): Promise<unknown> {
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/pdf')) {
    return res.blob()
  }
  const buffer = await res.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  if (bytes[0] === 0x25 && bytes[1] === 0x50 && bytes[2] === 0x44 && bytes[3] === 0x46) {
    return new Blob([buffer], { type: 'application/pdf' })
  }
  const text = new TextDecoder().decode(buffer)
  const trimmed = text.trimStart()
  if (
    !ct.includes('application/json') &&
    (trimmed.startsWith('<!DOCTYPE') ||
      trimmed.startsWith('<!doctype') ||
      trimmed.startsWith('<html'))
  ) {
    throw new Error(apiMisconfiguredMessage())
  }
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new Error(apiMisconfiguredMessage())
  }
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

  const url = `${API_BASE}${path}`
  const res = await fetch(url, { ...init, headers })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const err = (await readJsonOrThrow(res)) as { detail?: unknown }
      detail = err?.detail ?? err
    } catch (e) {
      if (e instanceof Error && e.message.includes('API')) throw e
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  return (await readJsonOrThrow(res)) as T
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
  year_built?: number
  monthly_cash_flow?: number
  rental_yield?: number
  one_year_roi?: number
  market_city?: string
  state_code?: string
  quantum_success?: number
  strategy?: string
  id?: string
  added_at?: string
}
