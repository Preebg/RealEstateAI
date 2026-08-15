import { supabase } from './supabase'

export type PreviewLoginResult = {
  access_token: string
  refresh_token: string
  username: string
}

function previewLoginEndpoints(): string[] {
  const host = window.location.hostname
  const local = host === 'localhost' || host === '127.0.0.1'
  if (local) return ['/api/auth/demo']

  const urls = ['/api/auth/demo']
  const api = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '')
  if (api) urls.push(`${api}/api/auth/demo`)
  return urls
}

async function postPreviewLogin(
  url: string,
  username: string,
): Promise<{ ok: true; data: PreviewLoginResult } | { ok: false; status: number; detail: string }> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  })
  const raw = await res.text()
  let payload: { access_token?: string; refresh_token?: string; username?: string; detail?: unknown } =
    {}
  try {
    payload = raw
      ? (JSON.parse(raw) as {
          access_token?: string
          refresh_token?: string
          username?: string
          detail?: unknown
        })
      : {}
  } catch {
    return {
      ok: false,
      status: res.status,
      detail: `Non-JSON response from ${url} (HTTP ${res.status})`,
    }
  }
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      detail:
        typeof payload.detail === 'string'
          ? payload.detail
          : `Preview login failed (HTTP ${res.status})`,
    }
  }
  if (!payload.access_token || !payload.refresh_token) {
    return { ok: false, status: res.status, detail: 'Preview login did not return a session.' }
  }
  return {
    ok: true,
    data: {
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      username: payload.username || username,
    },
  }
}

/** Sign in with an allowlisted preview username (no account signup). */
export async function signInWithPreviewUsername(username: string): Promise<string> {
  const errors: string[] = []
  for (const url of previewLoginEndpoints()) {
    let result: Awaited<ReturnType<typeof postPreviewLogin>>
    try {
      result = await postPreviewLogin(url, username)
    } catch (err) {
      errors.push(`${url}: ${err instanceof Error ? err.message : 'request failed'}`)
      continue
    }
    if (result.ok) {
      const { error } = await supabase.auth.setSession({
        access_token: result.data.access_token,
        refresh_token: result.data.refresh_token,
      })
      if (error) throw error
      return result.data.username
    }
    errors.push(`${url}: ${result.detail}`)
    if (result.status === 403 || result.status === 429) {
      throw new Error(result.detail)
    }
  }
  throw new Error(errors.join(' | ') || 'Preview login failed.')
}
