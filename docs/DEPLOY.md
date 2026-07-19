# Deploy CapEigen (Netlify + Docker API)

## Frontend (Netlify)

1. Connect this repo to Netlify (build config is in `netlify.toml`: base `web`, publish `dist`).
2. Set environment variables:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
   - `VITE_API_URL` = public HTTPS URL of the FastAPI service
3. In Supabase Auth → URL configuration, allow the Netlify site URL as a redirect.

## Backend (Docker)

1. Copy `.env.example` → `.env` and fill secrets (`SUPABASE_*`, `GEMINI_API_KEY`, `ADMIN_USER_ID`, `CORS_ORIGINS` including the Netlify origin).
2. `docker compose up --build` locally, or build/push the `Dockerfile` to Railway / Fly / Cloud Run.
3. Confirm `GET /api/health` returns `{"status":"ok",...}`.

## Cutover from Streamlit Cloud

1. Deploy API + Netlify SPA and verify login + Individual Search.
2. Point the product domain at Netlify; retire Streamlit Cloud traffic.
3. Keep `AIUnderwriterv2.py` only as a legacy reference until a follow-up cleanup PR.
