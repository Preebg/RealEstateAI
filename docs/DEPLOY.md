# Deploy CapEigen (Netlify + Docker API)

## Frontend (Netlify)

1. Connect this repo to Netlify (build config is in `netlify.toml`: base `web`, publish `dist`).
2. Set environment variables:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
   - `VITE_API_URL` = public HTTPS origin of the harvest machine FastAPI (Cloudflare Tunnel / Caddy), **required** for Home/Compare portfolio, Individual Search, and PDF. Example: `https://capeigen.preebg.dev` when that hostname reverse-proxies `/api/*` to `:8000`.
3. In Supabase Auth → URL configuration, allow the Netlify site URL as a redirect.

The portfolio map reads `/api/portfolio` from the harvest machine (local Postgres). Auth stays on Supabase. Analysis and other `/api/*` routes use the same FastAPI origin.

If you see `Unexpected token '<'… is not valid JSON`, the SPA called `/api/*` on Netlify and got `index.html` back — set `VITE_API_URL` to the harvest Caddy/Tunnel origin and redeploy.

## Backend (Docker)

1. Copy `.env.example` → `.env` and fill secrets (`SUPABASE_*`, `GEMINI_API_KEY`, `ADMIN_USER_ID`, `CORS_ORIGINS` including the Netlify origin).
2. For self-hosted data on the harvest machine, set `DATABASE_REST_URL` (host) and bring up `postgres` / `postgrest` / `rest-gateway` — see [LOCAL_POSTGRES.md](LOCAL_POSTGRES.md).
3. `docker compose up --build` locally, or build/push the `Dockerfile` to any container host (Fly, Cloud Run, Render, etc.).
4. Confirm `GET /api/health` returns `{"status":"ok",...}` (`data_backend` is `local-postgres` or `supabase`).

## Cutover notes

1. Deploy API + Netlify SPA and verify login + Individual Search.
2. Point the product domain at Netlify.
3. CapEigen is FastAPI (`api/`) + React (`web/`) only.
