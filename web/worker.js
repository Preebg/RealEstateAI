/**
 * Cloudflare Worker entry for CapEigen SPA + auth routes.
 * Pages-style handlers in functions/ are reused here so `wrangler deploy` works.
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

export default {
  async fetch(request, env, ctx) {
    const path = new URL(request.url).pathname.replace(/\/$/, '') || '/'
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

    return env.ASSETS.fetch(request)
  },
}
