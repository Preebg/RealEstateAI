# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

**CapEigen** is an AI-assisted real-estate underwriting product:

- **Frontend:** React (Vite) SPA in `web/`, deployed on **Netlify**
- **Backend:** FastAPI in `api/`, run via **Docker** / `docker-compose` (Railway/Fly/Cloud Run–ready)
- **Data / auth:** Supabase; property research via Google Gemini

Domain logic lives in root Python modules (`engine.py`, `finance.py`, `knowledge_base.py`, …). The legacy Streamlit app (`AIUnderwriterv2.py`) remains in-repo for reference but is **not** the primary entry.

See `docs/HARVESTER_SETUP.md` for the optional batch harvester (`harvester.py`).

### PATH

`pip install --user` puts CLI tools under `~/.local/bin`. Add it before running uvicorn or pytest:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Secrets

Copy `.env.example` to `.env` for the API:

| Key | Purpose |
|-----|---------|
| `GEMINI_API_KEY` | Gemini API |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/publishable key |
| `SUPABASE_SERVICE_ROLE_KEY` | Trusted jobs (harvester, some admin paths) |
| `ADMIN_USER_ID` | Admin UUID for model-validation API |
| `CORS_ORIGINS` | Comma-separated frontend origins |

Frontend (`web/.env`):

| Key | Purpose |
|-----|---------|
| `VITE_SUPABASE_URL` | Same Supabase URL |
| `VITE_SUPABASE_ANON_KEY` | Anon key (browser-safe) |
| `VITE_API_URL` | Public API base URL (empty in local Vite to use `/api` proxy) |

Add your Netlify URL to Supabase Auth redirect URLs.

### Run locally

**API (Docker):**

```bash
docker compose up --build
# http://localhost:8000/api/health
```

**API (without Docker):**

```bash
export PATH="$HOME/.local/bin:$PATH"
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

**Frontend:**

```bash
cd web
cp .env.example .env
npm install
npm run dev
# http://localhost:5173
```

**Netlify:** builds `web/` via `netlify.toml`. Set `VITE_*` env vars in the Netlify UI. Point `VITE_API_URL` at your deployed API.

### Lint / test / typecheck

Matches `.github/workflows/ci.yml`:

```bash
export PATH="$HOME/.local/bin:$PATH"
export GEMINI_API_KEY=fake_key_for_ci
ruff check .
mypy quantum_portfolio.py engine.py
pytest test_app.py test_api.py -v
cd web && npm ci && npm run build
```

### Services

| Service | Required? | Notes |
|---------|-----------|-------|
| Netlify SPA (`web/`) | Yes | Primary UI |
| FastAPI (`api/`) | Yes | Docker on port 8000 |
| Supabase (cloud) | Yes for real login/data | No local DB in repo |
| Gemini API | Yes for property analysis | Mocked in unit tests |
| Harvester | No | CLI / optional Streamlit control panel |

### Gotchas

- Python **3.11+** expected (Dockerfile uses 3.11).
- Analysis / quantum jobs run **asynchronously** — poll `GET /api/analysis/{job_id}`.
- Multi-replica API needs an external job store (current jobs are in-process memory).
- Full E2E needs real Supabase + Gemini credentials.
- Legacy: `streamlit run AIUnderwriterv2.py` may still work for comparison during migration.
