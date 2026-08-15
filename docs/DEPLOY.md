# Deploy CapEigen (Cloudflare Pages + Docker API)

## Frontend (Cloudflare Pages)

1. In [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**. Select this repo.
2. Build settings (Workers Git integration — your live URL is `*.workers.dev`):
   - **Root directory:** `web`
   - **Build command:** `npm run build`
   - **Deploy command:** `npm run deploy`
   - Node 20 is pinned in `web/.nvmrc`.

   `npm run deploy` runs `wrangler deploy --keep-vars` so dashboard secrets are not wiped. Do not leave the default `npx wrangler deploy` — that downloads Wrangler on every build and does not keep dashboard vars.
3. Set environment variables for **Production** (and Preview if you use branch deploys). Mark `VITE_*` as available at **build time**. Mark function secrets as available to **Functions** (runtime):

   | Variable | When | Purpose |
   |---|---|---|
   | `VITE_SUPABASE_URL` | Build + Functions | Auth project URL |
   | `VITE_SUPABASE_ANON_KEY` | Build + Functions | Browser-safe anon key |
   | `VITE_API_URL` | Build + Functions | Public HTTPS origin of harvest-machine FastAPI (Cloudflare Tunnel / Caddy). Example: `https://capeigen.preebg.dev` |
   | `VITE_GOOGLE_CLIENT_ID` | Build + Functions | Google Web client ID (public) |
   | `GOOGLE_WEB_CLIENT_ID` | Functions | Same as `VITE_GOOGLE_CLIENT_ID` |
   | `GOOGLE_WEB_CLIENT_SECRET` | Functions (secret) | Google Web client secret |
   | `SUPABASE_SERVICE_ROLE_KEY` | Functions (secret, optional) | Preview-username login fallback if FastAPI is down |
   | `API_URL` | Functions (optional) | Same as `VITE_API_URL` if you prefer a non-`VITE_` name |

4. Deploy. The production URL is `https://<project>.pages.dev` until you attach a custom domain (**Custom domains** in the Pages project).
5. In **Google Cloud** → OAuth client → Authorized redirect URIs, add `https://<your-pages-host>/auth/google/callback` (and the custom domain when you have one).
6. In **Supabase Auth** → URL configuration, allow the Pages site URL (and custom domain) as a redirect / site URL.

The portfolio map reads `/api/portfolio` from the harvest machine (local Postgres). Auth stays on Supabase. Google token exchange and preview-username login run as Pages Functions at `/api/auth/google/exchange` and `/api/auth/demo` (same paths as before). Analysis and other `/api/*` routes use `VITE_API_URL`.

If you see `Unexpected token '<'… is not valid JSON`, the SPA called `/api/*` on Pages and got `index.html` back — set `VITE_API_URL` to the harvest Caddy/Tunnel origin and redeploy.

SPA client routes are rewritten via `web/public/_redirects`. Function routes are listed in `web/functions/_routes.json` so static assets are not billed as Worker invocations.

## Backend (Docker)

1. Copy `.env.example` → `.env` and fill secrets (`SUPABASE_*`, `GEMINI_API_KEY`, `ADMIN_USER_ID`, `CORS_ORIGINS` including the Pages origin, e.g. `https://capeigen.pages.dev`).
2. For self-hosted data on the harvest machine, set `DATABASE_REST_URL` (host) and bring up `postgres` / `postgrest` / `rest-gateway` — see [LOCAL_POSTGRES.md](LOCAL_POSTGRES.md).
3. `docker compose up --build` locally, or build/push the `Dockerfile` to any container host (Fly, Cloud Run, Render, etc.).
4. Confirm `GET /api/health` returns `{"status":"ok",...}` (`data_backend` is `local-postgres` or `supabase`).
5. Restart the API after adding the Pages origin to `CORS_ORIGINS`. Preview `*.pages.dev` URLs are already allowed by the origin regex in `api/main.py`.

## Cutover notes

1. Deploy Pages + API and verify Google login, preview-username login, and Individual Search.
2. Point the product domain at Cloudflare Pages (or keep `*.pages.dev`).
3. Disconnect the Netlify site after the new origin works so you are not maintaining two frontends.
4. CapEigen is FastAPI (`api/`) + React (`web/`) only.
