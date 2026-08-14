# Hot Market Harvester — Setup & Automation

## Where is `ADMIN_USER_ID`?

Set it in the harvest machine environment (or a root `.env`):

```text
ADMIN_USER_ID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### How to get the value

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → your project  
2. **Authentication** → **Users**  
3. Click your Google account row  
4. Copy **User UID** (UUID format)

That UUID is your admin identity. Harvested rows are saved with `properties.user_id = ADMIN_USER_ID`.

---

## CapEigen stack — what runs where?

| Workload | Where to run | Why |
|----------|--------------|-----|
| **React web** (`web/`) | Netlify or `npm run dev` | User-facing UI (login, analyze, portfolio) |
| **FastAPI** (`api/`) | Docker / local uvicorn | Analysis jobs, guest shares, PDF |
| **Harvester** (`python harvester.py`) | Local PC or always-on machine | Long API job; not a serverless cron host |
| **Scheduled harvest every 1.5 hrs** | Same harvest machine via Task Scheduler | Headless CLI |

Data lands in **Supabase** by default — web, API, and harvester share one database.

To run **Postgres on the harvest machine** instead (recommended long-term), see [LOCAL_POSTGRES.md](LOCAL_POSTGRES.md). Set `DATABASE_REST_URL=http://127.0.0.1:3001` in `.env` for the host harvester; Auth stays on Supabase. Scheduled runs must use `scripts\run_harvester.cmd` (no arguments) so Docker and the REST gateway are up first.

---

## One-time setup (harvest machine)

### 1. Copy the project

```powershell
git clone <your-repo-url> C:\RealEstateAI
cd C:\RealEstateAI
```

### 2. Python environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure secrets

Set environment variables (or root `.env`):

| Key | Required for harvester |
|-----|-------------------------|
| `GEMINI_API_KEY` | Yes |
| `SUPABASE_URL` | Yes (Auth) |
| `SUPABASE_KEY` | Yes (anon/publishable) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes for Task Scheduler / CLI** |
| `ADMIN_USER_ID` | Yes (your Auth User UID) |
| `DATABASE_REST_URL` | Yes on the harvest machine (`http://127.0.0.1:3001`) |

`APP_URL` / OAuth redirect settings belong to the React web app, not the harvester.

### 4. Test one run

```powershell
cd C:\RealEstateAI
.\venv\Scripts\Activate.ps1
python harvester.py
```

You should see:

```text
Harvest saves will use admin user_id: <your-uuid>
```

Then stage logs and `Saved — Quantum: ...` lines.

Check local Postgres (`psql` / TablePlus on `localhost:5432`) — not hosted Supabase — when `DATABASE_REST_URL` is set. After the website is pointed at `/api/portfolio`, harvested rows appear on Home.

### 5. RLS (Row Level Security)

Headless harvest uses the **service role** key without a Google JWT. Never commit the service role key. Keep `SUPABASE_KEY` as the anon/public key for the React web app.

---

## Automate every 1.5 hours (Windows Task Scheduler)

Use `scripts\run_harvester.cmd` with **no arguments**, running as **SYSTEM**. Do not pick a personal Windows login and do not use the `.ps1` as the program.

The wrapper starts **Docker Desktop Service** (`com.docker.service`, already LocalSystem) and `docker desktop start`, then waits for `http://127.0.0.1:3001/healthz` before launching Python. It never opens the Docker Desktop GUI.

1. Create a task that runs every 90 minutes.
2. **General** → **Change User or Group** → object name: `SYSTEM` → **Check Names** (it becomes `NT AUTHORITY\SYSTEM`) → OK. No password.
3. Check **Run with highest privileges**.
4. Program: `C:\Projects\RealEstateAI\scripts\run_harvester.cmd`
5. Arguments: *(leave empty)*
6. Start in: `C:\Projects\RealEstateAI` (optional; the `.cmd` cds itself)

Or from an **elevated** PowerShell:

```powershell
.\scripts\setup_task.ps1
```

Secrets come from the project `.env`. For local Postgres:

```text
DATABASE_REST_URL=http://127.0.0.1:3001
```

Logs append to `harvester_scheduled.log` in the project root.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `.streamlit\secrets.toml not found` | Outdated wrapper. Use `scripts\run_harvester.cmd` (secrets are in `.env`) |
| Task does nothing / last run 0x1 | Program must be `run_harvester.cmd` with empty arguments, user `SYSTEM` |
| Object name box rejects a name | Type `SYSTEM` and Check Names — not "Docker Desktop User" |
| `SUPABASE_SERVICE_ROLE_KEY is required` | Set service role key in `.env` (any non-empty value works for local PostgREST) |
| `ADMIN_USER_ID is not set` | Set a valid Auth User UUID in `.env` |
| REST gateway not reachable / Docker errors | Start Docker Desktop; `docker compose up -d postgres postgrest rest-gateway` |
| Harvest writes to hosted Supabase instead of local Postgres | Set `DATABASE_REST_URL=http://127.0.0.1:3001` in `.env` |
| DNS / network errors | Confirm `SUPABASE_URL` resolves on the harvest host (Auth still uses hosted Supabase) |
