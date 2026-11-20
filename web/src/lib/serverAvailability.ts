/** Probe the harvest-machine FastAPI (agents) without cold-start retries. */

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || ''

const HEALTH_TIMEOUT_MS = 4000

export const SERVER_UNAVAILABLE_MESSAGE =
  'Please contact the website owner to access this website.'

export class ServerUnavailableError extends Error {
  constructor(message: string = SERVER_UNAVAILABLE_MESSAGE) {
    super(message)
    this.name = 'ServerUnavailableError'
  }
}

function healthUrl(): string {
  return `${API_BASE}/api/health`
}

/**
 * Returns true when CapEigen's FastAPI (agent) server answers a healthy status.
 * Used to gate login while keeping marketing/legal pages fully static.
 */
export async function isBackendOnline(): Promise<boolean> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS)
  try {
    const res = await fetch(healthUrl(), {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) return false
    const ct = res.headers.get('content-type') || ''
    if (!ct.includes('application/json')) return false
    const payload = (await res.json()) as { status?: string; service?: string }
    return payload.status === 'ok' || payload.service === 'capeigen-api'
  } catch {
    return false
  } finally {
    window.clearTimeout(timer)
  }
}

export async function requireBackendOnline(): Promise<void> {
  if (!(await isBackendOnline())) {
    throw new ServerUnavailableError()
  }
}
