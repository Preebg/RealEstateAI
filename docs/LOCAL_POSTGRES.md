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
| React SPA | Cloudflare Pages / Vite | Supabase Auth; catalog reads `/api/portfolio` on the harvest machine |

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

Scheduled Task Scheduler runs must use `scripts\run_harvester.cmd` with **no arguments**, as **SYSTEM**. That wrapper starts Docker Desktop Service (LocalSystem) and `docker desktop start`, brings up the stack via `scripts\wake_stack.cmd`, and waits for `http://127.0.0.1:3001/healthz` before launching Python. After each harvest it stops the stack unless `STACK_ALWAYS_ON=1` is set in `.env`. In the object-name box type `SYSTEM` (Check Names → `NT AUTHORITY\SYSTEM`).

### Energy / on-demand stack

| Piece | Role |
|-------|------|
| `scripts/run_wake_proxy.cmd` | Always-on (~negligible CPU). Caddy `/api/*` proxies here; wakes Docker on first request. |
| `scripts/stack_idle_guard.cmd` | Stops the stack after `STACK_IDLE_MINUTES` (default 30) with no API traffic. Register via `scripts/setup_idle_guard.ps1`. |
| `STACK_ALWAYS_ON=1` | Keep containers running (dev machines). |
| `STACK_STOP_DOCKER=0` | Stop containers when idle but leave Docker Desktop running. |

For local dev with hot reload: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

## Copy hosted Supabase catalog into local Postgres

Run this **on the harvest machine** (Docker Postgres must be up). It copies `properties`, comps, shares, overrides, saved listings, and related catalog tables. It does **not** copy `auth.users` (login stays on Supabase) or oauth handoff tokens.

Local harvest rows are kept: matching `id` or address is skipped so the two new synthesized listings are not overwritten.

```powershell
cd C:\Projects\RealEstateAI
docker compose up -d postgres postgrest rest-gateway
.\venv\Scripts\Activate.ps1
# If SUPABASE_SERVICE_ROLE_KEY is a local dummy (not a JWT), set:
#   SUPABASE_AUTH_SERVICE_ROLE_KEY=<hosted service_role JWT>
python scripts/migrate_supabase_to_local.py --dry-run
python scripts/migrate_supabase_to_local.py
```

Expect ~905 properties and ~3760 comparables from hosted, plus your local harvest rows. Then hard-refresh the website (it reads `/api/portfolio` from this machine).

Guest share SQL functions are applied from `docker/postgres/init/04_guest_share_functions.sql` during the migrate (existing volumes do not re-run init). Demo-account usernames use `docker/postgres/init/05_preview_usernames.sql` the same way.

Schema lives in `docker/postgres/init/` and runs **only on first volume create**. To apply newer init scripts on an existing volume without a full migrate:

```powershell
Get-Content -Raw .\docker\postgres\init\05_preview_usernames.sql | docker compose exec -T postgres psql -U capeigen -d capeigen -v ON_ERROR_STOP=1
Get-Content -Raw .\docker\postgres\init\08_legal_acceptances.sql | docker compose exec -T postgres psql -U capeigen -d capeigen -v ON_ERROR_STOP=1
docker compose restart postgrest
```

To reset:

```powershell
docker compose down
docker volume rm realestateai_postgres_data
docker compose up -d postgres postgrest rest-gateway
```

## Host Caddy (public API)

Existing root `Caddyfile` proxies `/api*` → wake proxy `:8088` → FastAPI `:8000`. Keep Postgres/PostgREST bound to localhost (compose ports). Do not publish `:5432` / `:3001` on the public internet.

The Pages SPA must call this origin: set `VITE_API_URL` to the Cloudflare Tunnel hostname (no trailing slash) and redeploy. Confirm with:

```powershell
curl https://capeigen.preebg.dev/api/health
# {"status":"ok","service":"capeigen-api","data_backend":"local-postgres"}
```

## Rollback

Remove `DATABASE_REST_URL` from `.env` and restart API/harvester — they use hosted Supabase again.
