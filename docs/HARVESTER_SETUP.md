# Hot Market Harvester — Setup & Automation

## Where is `ADMIN_USER_ID`?

It is **not** a file in your repo by default. You **create** it in:

```text
RealEstateAI/.streamlit/secrets.toml
```

Example (replace with your real UUID):

```toml
ADMIN_USER_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

### How to get the value

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → your project  
2. **Authentication** → **Users**  
3. Click your Google account row  
4. Copy **User UID** (UUID format)

That UUID is your admin identity. Harvested rows are saved with `properties.user_id = ADMIN_USER_ID`.

---

## Localhost vs Streamlit Cloud — what runs where?

| Workload | Where to run | Why |
|----------|--------------|-----|
| **AIUnderwriterv2** (UI, login, analyze) | **Streamlit Cloud** (`*.streamlit.app`) | User-facing app; needs OAuth redirect URLs for production |
| **Harvester** (`python harvester.py`) | **Local PC or always-on machine** | Long API job (~20 properties); Streamlit Cloud sleeps and is not a cron host |
| **Scheduled harvest every 1.5 hrs** | **Other machine / same PC** via Task Scheduler | Must run headless CLI, not the cloud UI |

**Do not** rely on Streamlit Cloud to run the harvester on a schedule. Deploy the **analyzer** to the cloud; run the **harvester** on a machine you control.

Data still lands in the **same Supabase** project — cloud app and local harvester share one database.

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
pip install streamlit supabase google-genai qiskit qiskit-aer pandas matplotlib tldextract
```

(Use your full `requirements.txt` if you have one.)

### 3. Configure secrets

Copy `.streamlit/secrets.toml` from your dev machine **or** create it with:

| Key | Required for harvester |
|-----|-------------------------|
| `GEMINI_API_KEY` | Yes |
| `SUPABASE_URL` | Yes |
| `SUPABASE_KEY` | Yes (anon/publishable) |
| `ADMIN_USER_ID` | Yes (your Auth User UID) |

`OAUTH_REDIRECT_URL` is only needed for the Streamlit login app, not the harvester.

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

Headless harvest uses the **anon** key without a Google JWT. Ensure Supabase policies allow inserts with your `user_id`, or use a **service role** key only on the harvest machine (never commit it).

---

## Automate every 1.5 hours (Windows Task Scheduler)

Logs append to `harvester_scheduled.log` in the project root.

**Create the scheduled task:**

1. Open **Task Scheduler** → **Create Task**
2. **General**
   - Name: `RealEstateAI Harvester`
   - Run whether user is logged on or not (if you want it while logged off, provide password)
   - Run with highest privileges: optional
3. **Triggers** → New → **Daily**, repeat every **1 hour 30 minutes** for duration **Indefinitely**
4. **Actions** → New
   - Action: Start a program
   - Program: `C:\RealEstateAI\venv\Scripts\python.exe`
   - Arguments: `harvester.py`
   - Start in: `C:\RealEstateAI`
5. **Conditions**: Uncheck “Start only on AC power” if on a laptop
6. Save

**Test manually:**

```powershell
cd C:\RealEstateAI
.\venv\Scripts\Activate.ps1
python harvester.py
```

### macOS / Linux (cron)

```cron
0 */1 * * * cd /path/to/RealEstateAI && /path/to/venv/bin/python harvester.py >> harvester_scheduled.log 2>&1
```

For every 90 minutes, use a loop script or systemd timer with `OnUnitActiveSec=90min`.

---

## API quota reminder (per run)

| Stage | Model | Calls per run | Concurrency |
|-------|--------|----------------|-------------|
| Discovery | gemini-2.5-flash → flash-lite → gemma-4-21b-it (API: 26b-a4b) | **1** | Sequential |
| Research | gemma-4-31b-it | up to ~25 | **Parallel** (≤10 calls/min) |
| Synthesis | gemini-3.1-flash-lite-preview | up to ~25 | **Parallel** (≤10 calls/min) |

Stages 2 and 3 run all listings concurrently via `asyncio`, with a per-model sliding-window
rate limiter (10 requests per 60 seconds) to stay under the ~15 RPM account cap.

Every **1.5 hours** ≈ **16 runs/day** → plan Gemini/Supabase limits accordingly.

---

## Streamlit harvest UI (optional)

```powershell
streamlit run harvester.py
```

Same `ADMIN_USER_ID` in secrets. This is for manual “Run Full Harvest” only, not for cloud deployment.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ADMIN_USER_ID is not set` | Fill UUID in `.streamlit/secrets.toml` |
| `Harvest save skipped` | Same as above; restart after saving secrets |
| Runs but no DB rows | Check Supabase RLS policies / use service role for harvest |
| `429` errors | Normal; harvester backs off 60s and retries |
| OAuth errors | Irrelevant to CLI harvester — ignore on harvest machine |
