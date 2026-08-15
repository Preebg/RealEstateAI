/**
 * Pages Function: issue a Supabase session for an allowlisted preview username.
 * Falls back to FastAPI when the service role key is not set on Pages.
 * Route: POST /api/auth/demo
 */
import { corsHeaders, envStr, json, onRequestOptions } from '../../_lib/http.js'

const DEFAULT_USERNAMES = 'salifT'
const EMAIL_DOMAIN = 'demo.capeigen.app'

export { onRequestOptions }

export async function onRequestPost(ctx) {
  const env = ctx.env

  let body
  try {
    body = await ctx.request.json()
  } catch {
    return json(400, { detail: 'Invalid JSON body' })
  }

  const username = typeof body.username === 'string' ? body.username.trim() : ''
  const api = envStr(env, 'API_URL', 'VITE_API_URL').replace(/\/$/, '')

  // Prefer FastAPI so dashboard-managed usernames apply without a Pages env change.
  if (api && username) {
    try {
      const res = await fetch(`${api}/api/auth/demo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      })
      const payload = await res.text()
      if (res.ok || res.status === 429) {
        return new Response(payload, {
          status: res.status,
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
          },
        })
      }
    } catch {
      // FastAPI unreachable: fall through.
    }
  }

  const display = resolveUsername(username, env)
  if (!display) {
    return json(403, { detail: 'Unknown preview username.' })
  }

  const serviceKey = envStr(env, 'SUPABASE_SERVICE_ROLE_KEY')
  if (serviceKey) {
    try {
      const session = await issueSession(display, env, serviceKey)
      ctx.waitUntil(recordPreviewLogin(display, session.access_token, serviceKey, env))
      return json(200, session)
    } catch (err) {
      return json(502, {
        detail: err instanceof Error ? err.message : 'Preview login failed',
      })
    }
  }

  if (!api) {
    return json(503, {
      detail:
        'Preview login is not configured. Set SUPABASE_SERVICE_ROLE_KEY or VITE_API_URL on Cloudflare Pages.',
    })
  }

  try {
    const res = await fetch(`${api}/api/auth/demo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: display }),
    })
    const payload = await res.text()
    return new Response(payload, {
      status: res.status,
      headers: {
        'Content-Type': 'application/json',
        ...corsHeaders(),
      },
    })
  } catch (err) {
    return json(502, {
      detail: err instanceof Error ? err.message : 'Preview login proxy failed',
    })
  }
}

function resolveUsername(username, env) {
  if (!/^[A-Za-z0-9_]{2,32}$/.test(username)) return null
  const raw = envStr(env, 'DEMO_USERNAMES') || DEFAULT_USERNAMES
  const mapping = {}
  for (const part of raw.split(',')) {
    const name = part.trim()
    if (/^[A-Za-z0-9_]{2,32}$/.test(name)) mapping[name.toLowerCase()] = name
  }
  return mapping[username.toLowerCase()] || null
}

async function issueSession(display, env, serviceKey) {
  const url = envStr(env, 'SUPABASE_URL', 'VITE_SUPABASE_URL').replace(/\/$/, '')
  const anon = envStr(env, 'SUPABASE_KEY', 'VITE_SUPABASE_ANON_KEY')
  if (!url || !anon) {
    throw new Error('Set SUPABASE_URL and SUPABASE_KEY (or VITE_ equivalents) on Cloudflare Pages.')
  }

  const email = `${display.toLowerCase()}@${EMAIL_DOMAIN}`
  const adminHeaders = {
    Authorization: `Bearer ${serviceKey}`,
    apikey: serviceKey,
    'Content-Type': 'application/json',
  }

  const createRes = await fetch(`${url}/auth/v1/admin/users`, {
    method: 'POST',
    headers: adminHeaders,
    body: JSON.stringify({
      email,
      email_confirm: true,
      user_metadata: { username: display, full_name: display },
      app_metadata: { preview: true, username: display },
    }),
  })
  if (!createRes.ok && createRes.status !== 422 && createRes.status !== 409) {
    const errBody = await createRes.json().catch(() => ({}))
    const msg =
      (typeof errBody.msg === 'string' && errBody.msg) ||
      (typeof errBody.message === 'string' && errBody.message) ||
      'Could not create preview user.'
    const already = /already|registered|exists/i.test(msg)
    if (!already) throw new Error(msg)
  }

  const linkRes = await fetch(`${url}/auth/v1/admin/generate_link`, {
    method: 'POST',
    headers: adminHeaders,
    body: JSON.stringify({ type: 'magiclink', email }),
  })
  const linkPayload = await linkRes.json().catch(() => ({}))
  if (!linkRes.ok) {
    throw new Error(
      (typeof linkPayload.msg === 'string' && linkPayload.msg) ||
        (typeof linkPayload.message === 'string' && linkPayload.message) ||
        'Could not start preview login.',
    )
  }
  const hashed =
    linkPayload.hashed_token || (linkPayload.properties && linkPayload.properties.hashed_token)
  if (!hashed) throw new Error('Preview login did not return a verification token.')

  const verifyRes = await fetch(`${url}/auth/v1/verify`, {
    method: 'POST',
    headers: {
      apikey: anon,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ type: 'magiclink', token_hash: hashed }),
  })
  let verifyPayload = await verifyRes.json().catch(() => ({}))
  if (!verifyRes.ok) {
    const retry = await fetch(`${url}/auth/v1/verify`, {
      method: 'POST',
      headers: {
        apikey: anon,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ type: 'email', token_hash: hashed }),
    })
    verifyPayload = await retry.json().catch(() => ({}))
    if (!retry.ok) {
      throw new Error(
        (typeof verifyPayload.msg === 'string' && verifyPayload.msg) ||
          (typeof verifyPayload.message === 'string' && verifyPayload.message) ||
          'Could not complete preview login.',
      )
    }
  }

  const access =
    verifyPayload.access_token || (verifyPayload.session && verifyPayload.session.access_token)
  const refresh =
    verifyPayload.refresh_token || (verifyPayload.session && verifyPayload.session.refresh_token)
  if (!access || !refresh) throw new Error('Preview login did not return a session.')
  return { access_token: access, refresh_token: refresh, username: display }
}

async function recordPreviewLogin(display, access, serviceKey, env) {
  const api = envStr(env, 'API_URL', 'VITE_API_URL').replace(/\/$/, '')
  if (api) {
    try {
      const res = await fetch(`${api}/api/preview/events`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${access}`,
        },
        body: JSON.stringify({
          event_type: 'login',
          path: '/login',
          label: 'Preview login',
          payload: { username: display, source: 'pages' },
        }),
      })
      if (res.ok) return
    } catch {
      // Fall through to hosted insert.
    }
  }

  const url = envStr(env, 'SUPABASE_URL', 'VITE_SUPABASE_URL').replace(/\/$/, '')
  if (!url || !access) return
  const userId = jwtSub(access)
  if (!userId) return
  try {
    await fetch(`${url}/rest/v1/preview_events`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${serviceKey}`,
        apikey: serviceKey,
        'Content-Type': 'application/json',
        Prefer: 'return=minimal',
      },
      body: JSON.stringify({
        user_id: userId,
        username: display,
        event_type: 'login',
        path: '/login',
        label: 'Preview login',
        payload: { username: display, source: 'pages' },
        is_preview: true,
      }),
    })
  } catch {
    // Login should still succeed if tracking is unavailable.
  }
}

function jwtSub(access) {
  try {
    const part = access.split('.')[1]
    if (!part) return null
    const padded = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(padded)
    return JSON.parse(json).sub || null
  } catch {
    return null
  }
}
