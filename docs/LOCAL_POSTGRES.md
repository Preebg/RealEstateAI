# Self-hosted Postgres (harvest machine)

CapEigen can run **Auth on Supabase** and **property data on local Postgres** (Docker on the harvest machine). That removes Supabase egress for harvester + FastAPI writes/reads.

## Architecture

| Piece | Where | Role |
|-------|--------|------|
| Postgres 16 | Docker `postgres` | Source of truth for properties / shares / overrides |
| PostgREST | Docker `postgrest` | REST over SQL (`/`) |
| REST gateway | Docker `rest-gateway` (:3001) | Exposes `/rest/v1/*` for `supabase-py` |
| FastAPI | Docker `api` (:8000) | Validates Supabase JWTs; reads/writes local data |
| Harvester | Host Python | Same `DATABASE_REST_URL` as the API |
| React SPA | Netlify / Vite | Still uses Supabase Auth; portfolio should call `/api/portfolio` |

Auth stays remote (`SUPABASE_URL` / `SUPABASE_AUTH_URL`). Do **not** point the browser PostgREST client at your home IP without a VPN/firewall plan.

## One-time bring-up

```powershell
cd C:\Projects\RealEstateAI
copy .env.example .env
# Fill SUPABASE_* (Auth), ADMIN_USER_ID, GEMINI_API_KEY
# For local data on the host harvester, add:
#   DATABASE_REST_URL=http://127.0.0.1:3001
#   SUPABASE_SERVICE_ROLE_KEY=local-service-key
# Compose API defaults to DATABASE_REST_URL_DOCKER=http://rest-gateway:3001

docker compose up --build -d postgres postgrest rest-gateway api
```

Check:

```powershell
curl http://127.0.0.1:8000/api/health
# {"status":"ok","service":"capeigen-api","data_backend":"local-postgres"}

curl http://127.0.0.1:3001/rest/v1/properties?select=id&limit=1 -H "apikey: local-service-key" -H "Authorization: Bearer local-service-key"
```

Harvester on the host (same `.env` with `DATABASE_REST_URL=http://127.0.0.1:3001`):

```powershell
.\venv\Scripts\Activate.ps1
python harvester.py
```

You should see `Harvest data backend: local-postgres`.

Scheduled Task Scheduler runs must use `scripts\run_harvester.ps1`. That wrapper loads `.env`, starts Docker Desktop if needed, brings up `postgres` / `postgrest` / `rest-gateway`, and waits for `http://127.0.0.1:3001/healthz` before launching Python. Direct `python harvester.py` from Task Scheduler will fail when Docker is down or `.env` is not in the process environment.

## Optional: copy rows from Supabase

From a machine with `pg_dump` / `psql` (or use Supabase SQL editor export):

1. Export `properties` (and related tables you need) from the hosted project.
2. `psql` into `localhost:5432` as `capeigen` / password from `.env`.
3. Re-run harvest or set `ADMIN_USER_ID` — API startup calls `set_catalog_admin_user_id`.

Schema lives in `docker/postgres/init/` and runs **only on first volume create**. To reset:

```powershell
docker compose down
docker volume rm realestateai_postgres_data
docker compose up -d postgres postgrest rest-gateway
```

## Host Caddy (public API)

Existing root `Caddyfile` already proxies `/api/*` → `:8000`. Keep Postgres/PostgREST bound to localhost (compose ports). Do not publish `:5432` / `:3001` on the public internet.

## Rollback

Remove `DATABASE_REST_URL` from `.env` and restart API/harvester — they use hosted Supabase again.
