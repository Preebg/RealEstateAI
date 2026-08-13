# Deploy CapEigen (Netlify + Docker API)

## Frontend (Netlify)

1. Connect this repo to Netlify (build config is in `netlify.toml`: base `web`, publish `dist`).
2. Set environment variables:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
   - `VITE_API_URL` = public HTTPS URL of the FastAPI service (optional for Home/Compare portfolio; **required** for Individual Search / analysis / PDF)
3. In Supabase Auth → URL configuration, allow the Netlify site URL as a redirect.

The portfolio map reads Supabase directly from the browser (authenticated). You do **not** need a hosted API for the home page. Analysis and other `/api/*` routes still need FastAPI (local Docker or a host of your choice).

If you see `Unexpected token '<'… is not valid JSON`, the SPA called `/api/*` on Netlify and got `index.html` back — either leave those features for local API, or set `VITE_API_URL` to a deployed FastAPI base URL and redeploy.

## Backend (Docker)

1. Copy `.env.example` → `.env` and fill secrets (`SUPABASE_*`, `GEMINI_API_KEY`, `ADMIN_USER_ID`, `CORS_ORIGINS` including the Netlify origin).
2. For self-hosted data on the harvest machine, set `DATABASE_REST_URL` (host) and bring up `postgres` / `postgrest` / `rest-gateway` — see [LOCAL_POSTGRES.md](LOCAL_POSTGRES.md).
3. `docker compose up --build` locally, or build/push the `Dockerfile` to any container host (Fly, Cloud Run, Render, etc.).
4. Confirm `GET /api/health` returns `{"status":"ok",...}` (`data_backend` is `local-postgres` or `supabase`).

## Cutover notes

1. Deploy API + Netlify SPA and verify login + Individual Search.
2. Point the product domain at Netlify.
3. CapEigen is FastAPI (`api/`) + React (`web/`) only.
