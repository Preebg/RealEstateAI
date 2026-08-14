/**
 * Netlify function: issue a Supabase session for an allowlisted preview username.
 * Falls back to FastAPI when the service role key is not set on Netlify.
 */
const DEFAULT_USERNAMES = 'salifT'
const EMAIL_DOMAIN = 'demo.capeigen.app'

exports.handler = async function handler(event) {
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers: corsHeaders(), body: '' }
  }
  if (event.httpMethod !== 'POST') {
    return json(405, { detail: 'Method not allowed' })
  }

  let body
  try {
    body = JSON.parse(event.body || '{}')
  } catch {
    return json(400, { detail: 'Invalid JSON body' })
  }

  const username = typeof body.username === 'string' ? body.username.trim() : ''
  const api = String(process.env.API_URL || process.env.VITE_API_URL || '')
    .trim()
    .replace(/\/$/, '')

  // Prefer FastAPI so dashboard-managed usernames apply without a Netlify env change.
  if (api && username) {
    try {
      const res = await fetch(`${api}/api/auth/demo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      })
      const payload = await res.text()
      if (res.ok || res.status === 429) {
        return {
          statusCode: res.status,
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
          },
          body: payload,
        }
      }
      if (!(res.ok || res.status === 429 || res.status === 403)) {
        // 5xx / unexpected: fall through to the local env allowlist.
      }
      // 403: unknown to FastAPI — still allow a Netlify DEMO_USERNAMES fallback.
    } catch {
      // FastAPI unreachable: fall through.
    }
  }

  const display = resolveUsername(username)
  if (!display) {
    return json(403, { detail: 'Unknown preview username.' })
  }

  const serviceKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim()
  if (serviceKey) {
    try {
      const session = await issueSession(display, serviceKey)
      await recordPreviewLogin(display, session.access_token, serviceKey)
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
        'Preview login is not configured. Set SUPABASE_SERVICE_ROLE_KEY or VITE_API_URL on Netlify.',
    })
  }

  try {
    const res = await fetch(`${api}/api/auth/demo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: display }),
    })
    const payload = await res.text()
    return {
      statusCode: res.status,
      headers: {
        'Content-Type': 'application/json',
        ...corsHeaders(),
      },
      body: payload,
    }
  } catch (err) {
    return json(502, {
      detail: err instanceof Error ? err.message : 'Preview login proxy failed',
    })
  }
}

function resolveUsername(username) {
  if (!/^[A-Za-z0-9_]{2,32}$/.test(username)) return null
  const raw = String(process.env.DEMO_USERNAMES || DEFAULT_USERNAMES)
  const mapping = {}
  for (const part of raw.split(',')) {
    const name = part.trim()
    if (/^[A-Za-z0-9_]{2,32}$/.test(name)) mapping[name.toLowerCase()] = name
  }
  return mapping[username.toLowerCase()] || null
}

async function issueSession(display, serviceKey) {
  const url = String(process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '')
    .trim()
    .replace(/\/$/, '')
  const anon = String(process.env.SUPABASE_KEY || process.env.VITE_SUPABASE_ANON_KEY || '').trim()
  if (!url || !anon) {
    throw new Error('Set SUPABASE_URL and SUPABASE_KEY (or VITE_ equivalents) on Netlify.')
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
    linkPayload.hashed_token ||
    (linkPayload.properties && linkPayload.properties.hashed_token)
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

  const access = verifyPayload.access_token || (verifyPayload.session && verifyPayload.session.access_token)
  const refresh =
    verifyPayload.refresh_token || (verifyPayload.session && verifyPayload.session.refresh_token)
  if (!access || !refresh) throw new Error('Preview login did not return a session.')
  return { access_token: access, refresh_token: refresh, username: display }
}

async function recordPreviewLogin(display, access, serviceKey) {
  const api = String(process.env.API_URL || process.env.VITE_API_URL || '')
    .trim()
    .replace(/\/$/, '')
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
          payload: { username: display, source: 'netlify' },
        }),
      })
      if (res.ok) return
    } catch {
      // Fall through to hosted insert.
    }
  }

  const url = String(process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '')
    .trim()
    .replace(/\/$/, '')
  if (!url || !access) return
  let userId
  try {
    const part = access.split('.')[1]
    const padded = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = Buffer.from(padded, 'base64').toString('utf8')
    userId = JSON.parse(json).sub
  } catch {
    return
  }
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
        payload: { username: display, source: 'netlify' },
      }),
    })
  } catch {
    // Login should still succeed if tracking is unavailable.
  }
}

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
  }
}

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(),
    },
    body: JSON.stringify(body),
  }
}
