/**
 * Cloudflare Worker entry for CapEigen SPA + auth routes.
 * Pages-style handlers in functions/ are reused here so `wrangler deploy` works.
 *
 * Routing model (capeigen.preebg.dev Worker route in front of the tunnel):
 * - Marketing SPA + static assets → ASSETS (no Caddy/Docker required)
 * - /api/auth/* → Worker-local handlers (optional FastAPI fallback inside)
 * - Other /api/* → pass through to tunnel origin (Caddy → wake proxy → FastAPI)
 */
import {
  onRequestOptions as demoOptions,
  onRequestPost as demoPost,
} from './functions/api/auth/demo.js'
import {
  onRequestOptions as googleOptions,
  onRequestPost as googlePost,
} from './functions/api/auth/google/exchange.js'
import { json } from './functions/_lib/http.js'

function pagesCtx(request, env, ctx) {
  return {
    request,
    env,
    waitUntil(promise) {
      ctx.waitUntil(promise)
    },
  }
}

function isApiPath(path) {
  return path === '/api' || path.startsWith('/api/')
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url)
    const path = url.pathname.replace(/\/$/, '') || '/'
    const handlerCtx = pagesCtx(request, env, ctx)

    if (path === '/api/auth/demo') {
      if (request.method === 'OPTIONS') return demoOptions()
      if (request.method === 'POST') return demoPost(handlerCtx)
      return json(405, { detail: 'Method not allowed' })
    }

    if (path === '/api/auth/google/exchange') {
      if (request.method === 'OPTIONS') return googleOptions()
      if (request.method === 'POST') return googlePost(handlerCtx)
      return json(405, { detail: 'Method not allowed' })
    }

    // Harvest-machine API: forward to the zone origin (Cloudflare Tunnel → Caddy).
    // When Caddy/Docker are down this returns 502/503 — SPA still loads from ASSETS.
    if (isApiPath(path)) {
      try {
        return await fetch(request)
      } catch {
        return json(503, {
          detail: 'Please contact the website owner to access this website.',
        })
      }
    }

    return env.ASSETS.fetch(request)
  },
}
