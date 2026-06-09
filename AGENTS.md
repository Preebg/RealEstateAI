# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

**AI Property Scout** is a Python Streamlit app (`AIUnderwriterv2.py`) for AI-assisted real-estate underwriting. Auth and data use **Supabase**; property research uses **Google Gemini**. See `docs/HARVESTER_SETUP.md` for the optional batch harvester (`harvester.py`).

### PATH

`pip install --user` puts CLI tools under `~/.local/bin`. Add it before running Streamlit or pytest:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Secrets (required for the UI)

Create `.streamlit/secrets.toml` (gitignored) with at least:

| Key | Purpose |
|-----|---------|
| `GEMINI_API_KEY` | Gemini API |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/publishable key |
| `OAUTH_REDIRECT_URL` | Optional locally; defaults to `http://localhost:8501` |

The app reads some values via `st.secrets` (not only `os.environ`), so a `secrets.toml` file is required even when env vars are set.

Harvester-only keys: `ADMIN_USER_ID`, `SUPABASE_SERVICE_ROLE_KEY` (`docs/HARVESTER_SETUP.md`).

### Run the app

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /workspace
streamlit run AIUnderwriterv2.py --server.enableCORS false --server.enableXsrfProtection false
```

Dev server: **http://localhost:8501**

### Lint / test / typecheck

Matches `.github/workflows/ci.yml`:

```bash
export PATH="$HOME/.local/bin:$PATH"
export GEMINI_API_KEY=fake_key_for_ci
ruff check .
mypy quantum_portfolio.py engine.py --follow-imports=silent
pytest test_app.py -v
```

CI sets `GEMINI_API_KEY=fake_key_for_ci` because tests mock external APIs.

### Services

| Service | Required? | Notes |
|---------|-----------|-------|
| Streamlit app | Yes | Single dev process on port 8501 |
| Supabase (cloud) | Yes for real login/data | No local DB in repo |
| Gemini API | Yes for property analysis | Mocked in unit tests |
| Harvester | No | Separate CLI/Streamlit job |

### Gotchas

- Python **3.11+** expected (devcontainer uses 3.11; cloud VM may have 3.12).
- No `docker-compose` or local Supabase — all backend is hosted.
- Full E2E (login, search, save) needs **real** Supabase + Gemini credentials; placeholder secrets only prove the login shell loads.
- `verify_app.py` references legacy `APP_PASSWORD`; production auth is in `authenticate.py` (Supabase OAuth + email/password).
