/** Shared JSON / CORS helpers for Pages Functions. */

export function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
  }
}

export function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(),
    },
  })
}

export function envStr(env, ...keys) {
  if (!env || typeof env !== 'object') return ''
  for (const key of keys) {
    const value = env[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export function onRequestOptions() {
  return new Response(null, { status: 204, headers: corsHeaders() })
}
