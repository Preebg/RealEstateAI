/**
 * Worker route: exchange Google auth code (PKCE) for an id_token.
 * Prefers FastAPI (harvest machine already has GOOGLE_WEB_CLIENT_SECRET).
 * Route: POST /api/auth/google/exchange
 */
import { corsHeaders, envStr, json, onRequestOptions } from '../../../_lib/http.js'

const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
const DEFAULT_API_URL = 'https://capeigen.preebg.dev'

export { onRequestOptions }

export async function onRequestPost(ctx) {
  const env = ctx.env

  let body
  try {
    body = await ctx.request.json()
  } catch {
    return json(400, { detail: 'Invalid JSON body' })
  }

  const code = typeof body.code === 'string' ? body.code : ''
  const codeVerifier = typeof body.code_verifier === 'string' ? body.code_verifier : ''
  const redirectUri = typeof body.redirect_uri === 'string' ? body.redirect_uri : ''
  if (!code || !codeVerifier || !redirectUri) {
    return json(400, { detail: 'code, code_verifier, and redirect_uri are required' })
  }

  const api = (envStr(env, 'API_URL', 'VITE_API_URL') || DEFAULT_API_URL).replace(/\/$/, '')
  try {
    const res = await fetch(`${api}/api/auth/google/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        code_verifier: codeVerifier,
        redirect_uri: redirectUri,
      }),
    })
    const payload = await res.text()
    // Do not retry on 4xx: the Google auth code is one-time-use once FastAPI talks to Google.
    if (res.ok || res.status < 500) {
      return new Response(payload, {
        status: res.status,
        headers: {
          'Content-Type': 'application/json',
          ...corsHeaders(),
        },
      })
    }
  } catch {
    // FastAPI unreachable: fall through to Worker-local Google credentials.
  }

  const clientId = envStr(env, 'GOOGLE_WEB_CLIENT_ID', 'VITE_GOOGLE_CLIENT_ID')
  const clientSecret = envStr(env, 'GOOGLE_WEB_CLIENT_SECRET')
  if (!clientId || !clientSecret) {
    return json(503, {
      detail:
        'Google OAuth is not available. The Worker could not reach the API and has no GOOGLE_WEB_CLIENT_SECRET. Confirm https://capeigen.preebg.dev/api/health, then retry.',
    })
  }

  const form = new URLSearchParams({
    code,
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uri: redirectUri,
    grant_type: 'authorization_code',
    code_verifier: codeVerifier,
  })

  let googleRes
  try {
    googleRes = await fetch(GOOGLE_TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    })
  } catch (err) {
    return json(502, {
      detail: err instanceof Error ? err.message : 'Google token request failed',
    })
  }

  const payload = await googleRes.json().catch(() => ({}))
  if (!googleRes.ok) {
    const detail =
      (typeof payload.error_description === 'string' && payload.error_description) ||
      (typeof payload.error === 'string' && payload.error) ||
      'Google token exchange failed'
    return json(400, { detail })
  }

  if (!payload.id_token || typeof payload.id_token !== 'string') {
    return json(502, { detail: 'Google did not return an id_token' })
  }

  return json(200, { id_token: payload.id_token })
}
