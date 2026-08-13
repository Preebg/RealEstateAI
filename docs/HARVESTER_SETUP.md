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

To run **Postgres on the harvest machine** instead (recommended long-term), see [LOCAL_POSTGRES.md](LOCAL_POSTGRES.md). Set `DATABASE_REST_URL=http://127.0.0.1:3001` for the host harvester; Auth stays on Supabase.

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
| `SUPABASE_URL` | Yes |
| `SUPABASE_KEY` | Yes (anon/publishable) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes for Task Scheduler / CLI** |
| `ADMIN_USER_ID` | Yes (your Auth User UID) |

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

Check Supabase **Table Editor** → `properties` → filter `user_id` = your `ADMIN_USER_ID`.

### 5. RLS (Row Level Security)

Headless harvest uses the **service role** key without a Google JWT. Never commit the service role key. Keep `SUPABASE_KEY` as the anon/public key for the React web app.

---

## Automate every 1.5 hours (Windows Task Scheduler)

1. Create a task that runs every 90 minutes.
2. Action: start program `C:\RealEstateAI\venv\Scripts\python.exe`
3. Arguments: `harvester.py`
4. Start in: `C:\RealEstateAI`
5. Ensure the task user has the same environment variables (or load them in a wrapper `.ps1`).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SUPABASE_SERVICE_ROLE_KEY is required` | Set service role key in the harvest machine environment |
| `ADMIN_USER_ID is not set` | Set a valid Auth User UUID in the environment |
| DNS / network errors | Confirm `SUPABASE_URL` resolves on the harvest host |
