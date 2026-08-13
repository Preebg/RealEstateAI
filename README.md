# CapEigen

### AI Agentic Underwriting & QAOA Quantum Portfolio Optimization for Real Estate Investment

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Qiskit](https://img.shields.io/badge/Qiskit-Aer-6929C4.svg)](https://qiskit.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/UI-React%20%2B%20Vite-61DAFB.svg)](https://vitejs.dev/)
[![Supabase](https://img.shields.io/badge/data-Supabase%20%2F%20PostgreSQL-3FCF8E.svg)](https://supabase.com/)
[![CI](https://img.shields.io/badge/CI-ruff%20%7C%20mypy%20%7C%20pytest-success.svg)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey.svg)](#license)

<p align="center">
  <img src="assets/capeigen-architecture.png" alt="CapEigen hybrid architecture — SPA, FastAPI, agentic LLM, classical finance, QAOA, Supabase" width="920" />
</p>

<p align="center"><em>Figure 1.</em> CapEigen hybrid stack: presentation → API → agentic / classical / quantum cores → Supabase.</p>

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [End-to-End Analysis Lifecycle](#end-to-end-analysis-lifecycle)
4. [Agentic LLM Workflow](#agentic-llm-workflow)
5. [Classical Financial Engine](#classical-financial-engine)
6. [Quantum Alignment Engine (QAOA)](#quantum-alignment-engine-qaoa)
7. [Data Plane & Knowledge Base](#data-plane--knowledge-base)
8. [Repository Structure](#repository-structure)
9. [Setup & Installation](#setup--installation)
10. [Usage & API Specs](#usage--api-specs)
11. [Testing & Quality Assurance](#testing--quality-assurance)
12. [Further Reading](#further-reading)

---

## Executive Summary

Residential underwriting still leans on static rules of thumb—gross rent multipliers, one-size-fits-all vacancy assumptions, and single-point appreciation guesses—that ignore metro heterogeneity, rent-comp evidence, and the **joint** risk of cash flow versus appreciation.

**CapEigen** (this repository, also known as RealEstateAI) replaces that stack with a **hybrid quantum–classical** pipeline:

| Pillar | Module(s) | Role |
|--------|-----------|------|
| **Agentic research** | `engine.py` | Multi-model Gemini / Gemma chains with Search + Maps grounding, RPM limits, KB-augmented prompts |
| **Classical underwriting** | `finance.py` | Debt service, OpEx, NOI, cap rate, cash-on-cash, rent resolution, tax/insurance normalization, 10-year Monte Carlo appreciation |
| **Quantum alignment** | `quantum_portfolio.py` | Three-qubit QAOA on Qiskit Aer; SciPy COBYLA over \((\gamma,\beta)\); histogram → success probabilities |

The product surface is a **React (Vite) SPA** on Netlify talking to a **FastAPI** backend (Docker). Domain logic lives in root Python modules.

---

## Architecture Overview

### System context

```mermaid
flowchart TB
    subgraph Actors
        INV[Investor / Analyst]
        ADM[Admin / Harvester]
    end

    subgraph CapEigen["CapEigen platform"]
        SPA[React SPA · Netlify]
        API[FastAPI · Docker]
        CORE[engine · finance · QAOA · KB]
    end

    subgraph Externals
        GEM[Google GenAI<br/>Gemini / Gemma + Search & Maps]
        SB[(Supabase Auth + PostgreSQL)]
        LIST[Listing sources<br/>Zillow / Redfin / Realtor]
    end

    INV -->|Analyze · HITL · PDF| SPA
    INV -->|Sign-in JWT| SB
    ADM -->|Harvest · archive| CORE
    SPA -->|CORS / VITE_API_URL| API
    API --> CORE
    CORE -->|generate_content| GEM
    CORE -->|PostgREST / RLS| SB
    CORE -->|optional scrape| LIST
```

### Logical layers (C4-L2)

```mermaid
flowchart TB
    subgraph Presentation["Presentation"]
        SPA["web/ — React + Vite SPA<br/>Netlify"]
    end

    subgraph Edge["API Edge"]
        API["api/main.py — FastAPI<br/>JWT middleware · CORS · OpenAPI"]
        JOBS["api/jobs.py<br/>In-process job store + ThreadPoolExecutor"]
        ROUTES["routes: health · properties · analysis<br/>guest · compare_pdf · validation"]
    end

    subgraph Domain["Domain Core"]
        ENG["engine.py<br/>Agents · RPM · quantum wrappers"]
        FIN["finance.py<br/>Cash flow · MC appreciation"]
        QAOA["quantum_portfolio.py<br/>QAOA · Aer · COBYLA"]
        KB["knowledge_base.py<br/>Catalog · overrides · context"]
        COMPS["comps_analysis.py<br/>rent_comps_analysis.py"]
        SVC["services/<br/>property_analysis_flow<br/>deferred_analysis"]
    end

    subgraph Data["Data & Externals"]
        SB[(Supabase / PostgreSQL)]
        GEM[Google GenAI]
        DISC["discovery/<br/>HTTP + parsers"]
    end

    SPA -->|Bearer JWT / JSON| API
    API --> ROUTES --> JOBS
    JOBS --> SVC
    SVC --> ENG & FIN & QAOA & KB & COMPS
    ENG --> GEM
    ENG --> KB
    KB --> SB
    ENG --> DISC
    API -.->|bind request Supabase client| SB
```

### Deployment topology

```mermaid
flowchart LR
    U[Browser] --> N[Netlify SPA]
    U --> S[Supabase Auth]
    N -->|VITE_API_URL| F[FastAPI container<br/>:8000]
    F -->|anon / service role| P[(Postgres)]
    F -->|GEMINI_API_KEY| G[Gemini API]
    H[harvester.py CLI] -->|service role| P
    H --> G

    style N fill:#e8f4f8,stroke:#1a5f7a
    style F fill:#e8f0e8,stroke:#2d6a4f
    style P fill:#eef6ee,stroke:#40916c
    style G fill:#f5f0e6,stroke:#7a5c2e
```

> **Scale note.** Analysis / quantum jobs are **asynchronous** and stored **in-process** (`api/jobs.py`). Multi-replica API deployments require an external job store (Redis, DB, queue). Poll: `GET /api/analysis/{job_id}`.

---

## End-to-End Analysis Lifecycle

When a user submits an address, CapEigen either **instant-pulls** a catalog hit or runs a full agentic research pass, then queues deferred heavy work (comps → QAOA → forecast chart).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant SPA as React SPA
    participant API as FastAPI
    participant Jobs as Job Worker
    participant KB as knowledge_base
    participant Eng as engine
    participant Fin as finance
    participant Q as quantum_portfolio
    participant DB as Supabase

    User->>SPA: Analyze address
    SPA->>API: POST /api/analysis (JWT)
    API->>Jobs: create_job(queued)

    alt Catalog hit (≤ 30 days)
        Jobs->>KB: lookup_property(address)
        KB->>DB: properties + overrides
        Jobs-->>SPA: property_data (from_kb=true)
    else Fresh research
        Jobs->>Eng: research / synthesis agents
        Eng->>KB: get_kb_context()
        Eng->>Eng: Gemini + Search/Maps
        Jobs-->>SPA: initial property_data
    end

    loop Poll job
        SPA->>API: GET /api/analysis/{job_id}
        API-->>SPA: status + partial results
    end

    Jobs->>Jobs: deferred queue: comps → quantum → forecast
    Jobs->>Fin: analyze_investment / MC forecast
    Jobs->>Q: score_portfolio(CF, rate, loc)
    Q-->>Jobs: AlignmentBreakdown
    Jobs-->>SPA: status=done + quantum_risk

    opt Persist
        SPA->>API: save / override
        API->>KB: upsert properties / user_property_overrides
    end
```

**Deferred task labels** (`services/deferred_analysis.py`):

| Task key | User-visible label |
|----------|--------------------|
| `comps` | Checking comparable sales |
| `quantum` | Running quantum alignment simulation |
| `forecast_chart` | Building appreciation forecast chart |

Finance inputs for QAOA are snapshotted as `(monthly_net_cash_flow, forecast_rate, location_score)` so the quantum stage stays consistent if the user navigates away mid-job.

---

## Agentic LLM Workflow

### Model routing & fallbacks

```mermaid
flowchart LR
    subgraph Discovery
        D1[gemini-2.5-flash] --> D2[gemini-2.5-flash-lite]
        D2 --> D3[gemma-4-26b-a4b-it]
    end

    subgraph Research
        R1[gemma-4-31b-it]
    end

    subgraph Geocode
        G1[gemini-3.1-flash-lite]
    end

    subgraph Synthesis
        S1[gemini-3.5-flash-lite] --> S2[gemini-3.7-flash]
        S2 --> S3[gemini-3.6-flash]
    end

    subgraph Value
        V1[gemma-4-26b-a4b-it] -.->|triggered| V2[gemma-4-31b-it]
    end

    IN[Address / metro] --> Discovery
    Discovery --> Research
    Discovery --> Geocode
    Research --> Value
    Value --> Synthesis
    Geocode --> Synthesis
    KBCTX[get_kb_context] -.-> Synthesis
    TOOLS[Google Search + Maps<br/>on Gemini flash tiers] -.-> Discovery
    MAPS[Maps + Search grounding] -.-> Geocode
```

| Role | Primary | Fallbacks |
|------|---------|-----------|
| Discovery | `gemini-2.5-flash` | `gemini-2.5-flash-lite`, `gemma-4-26b-a4b-it` |
| Research | `gemma-4-31b-it` | — |
| Synthesis | `gemini-3.5-flash-lite` | `gemini-3.7-flash`, `gemini-3.6-flash` |
| Property value | `gemma-4-26b-a4b-it` | triggered `gemma-4-31b-it` |
| Geocoding / Maps | `gemini-3.1-flash-lite` | parallel with research; Maps + Search grounding |

Hot-market discovery targets metros in `HOT_MARKETS` (NY, PA, FL, NC, SC, …).

### Rate limiting & grounding budgets

```mermaid
flowchart TB
    REQ[generate_content request] --> LIM{SharedModelRateLimiter<br/>per-model RPM}
    LIM -->|slot free| CALL[Call Gemini / Gemma]
    LIM -->|window full| WAIT[Sleep until window slides]
    WAIT --> LIM
    CALL --> GROUND{Grounding tools?}
    GROUND -->|Maps| MB[MAP_GROUNDING_DAILY_BUDGET = 500]
    GROUND -->|Search| SB[SEARCH_GROUNDING_DAILY_BUDGET = 1500]
    CALL --> STATE[(.gemini_model_rpm.json<br/>cross-process lock)]
```

RPM enforcement is **disabled** when `PYTEST_CURRENT_TEST` is set.

Example RPM caps (`MODEL_RPM_LIMITS`): flash `5`, flash-lite `10`, Gemma tiers `13` (default `DEFAULT_MODEL_RPM = 13`).

### Knowledge augmentation

Before synthesis, `get_kb_context(user_id)` injects:

- up to **3** recent analyses (address · market · predicted value);
- up to **50** already-scanned addresses (skip rediscovery).

Instant pull: `lookup_property(address)` against the shared `properties` table (30-day active window) with optional `user_property_overrides`.

---

## Classical Financial Engine

```mermaid
flowchart TB
    PD[Property facts<br/>price · rent · tax · insurance · fees] --> NORM[Normalization]
    NORM --> N1[normalize_tax_rate_percent]
    NORM --> N2[normalize_monthly_insurance]
    NORM --> N3[normalize_percent_rate]
    NORM --> N4[resolve_monthly_rent<br/>+ rent comps uplift ≥5%]

    N4 --> AI[analyze_investment]
    AI --> MORT[Mortgage P&amp;I]
    AI --> OPEX[Taxes · Ins · HOA · Maint<br/>Vacancy · Mgmt]
    MORT --> CF[monthly_net_cash_flow]
    OPEX --> CF
    CF --> METRICS[NOI · Cap Rate · Cash-on-Cash]

    PD --> MC[monte_carlo_appreciation_forecast]
    MC --> BASE[Metro historical CAGR]
    MC --> LOC[±1.5%/yr location band]
    MC --> SIM[2000 paths · seed 42]
    SIM --> PCTL[p10 / p50 / p90<br/>10-year value schedule]

    CF --> QIN[QAOA inputs]
    PCTL --> QIN
    PD -->|location_score| QIN
```

| Concern | Behavior |
|---------|----------|
| **Cash flow** | `analyze_investment` → P&I, taxes, insurance, HOA, maint % of rent, vacancy, management → NOI, cap rate, cash-on-cash |
| **Rent** | Priority: saved → AI baseline → stated gross → rent comps → **1% rule**; rejects price-in-thousands LLM artifacts |
| **Rent comps** | `apply_rent_comps_adjustment` fills missing rent or uplifts when comps show ≥5% underrenting |
| **Sale comps** | `comps_analysis` normalizes comparables; may adjust implied market value |
| **Appreciation** | Metro CAGR + location band; Monte Carlo → p10/p50/p90 schedules |
| **ROI screen** | 1-year ROI > 100% → unreliable (foreclosure-like); KB save may refuse |

Currency outputs in underwriting paths are rounded to **two decimal places** where applicable.

---

## Quantum Alignment Engine (QAOA)

<p align="center">
  <img src="assets/capeigen-qaoa-circuit.png" alt="Three-qubit CapEigen QAOA alignment circuit" width="880" />
</p>

<p align="center"><em>Figure 2.</em> Depth-1 QAOA circuit: \(H^{\otimes 3}\) → cost \(R_z / R_{ZZ}\) → mixer \(R_x(2\beta)\) → measure.</p>

### Module boundary

```mermaid
flowchart LR
    UI[UI / jobs / deferred] --> CQR["engine.calculate_quantum_risk<br/>@lru_cache(256)"]
    CQR --> SP["quantum_portfolio.score_portfolio"]
    SP --> BD[AlignmentBreakdown]
    BD --> DICT[to_dict → quantum_risk]
    DICT --> SCORE[quantum_risk_score =<br/>overall_success_pct]
```

Public library API: **`score_portfolio(PortfolioInputs) → AlignmentBreakdown`**.

### Target encoding

| Input | Normalization \(t \in [0,1]\) |
|-------|-------------------------------|
| Monthly cash flow | \(t_{\mathrm{cf}} = \min(\mathrm{CF}/800, 1)\); **≤ 0 → 0** |
| Forecast rate (%/yr) | \(t_{\mathrm{rate}} = \mathrm{clamp}(\mathrm{rate}/8, 0, 1)\) |
| Location score (0–10) | \(t_{\mathrm{loc}} = \mathrm{clamp}(\mathrm{score}/10, 0, 1)\) |

### Cost Hamiltonian (classical form)

\[
C(x_0,x_1,x_2) =
(t_{\mathrm{cf}}-x_0)^2 + (t_{\mathrm{rate}}-x_1)^2 + (t_{\mathrm{loc}}-x_2)^2
+ \lambda\bigl[(x_0-x_1)^2 + (x_1-x_2)^2\bigr], \quad \lambda = 0.15
\]

### Optimization & measurement loop

```mermaid
flowchart TB
    IN[PortfolioInputs] --> T[_success_targets]
    T --> EDGE{All targets 0?}
    EDGE -->|yes| Z[Zero breakdown]
    EDGE -->|CF=rate=0, loc>0| L[Legacy location-only %]
    EDGE -->|else| OPT[COBYLA maximize alignment]

    OPT --> BUILD[_build_qaoa_circuit γ,β]
    BUILD --> RUN1[AerSimulator · 256 shots<br/>seed_simulator=42]
    RUN1 --> COST[Expected C from histogram]
    COST --> COBYLA{Converged / maxiter=30?}
    COBYLA -->|update γ,β<br/>clip to bounds| BUILD
    COBYLA -->|done| FINAL[Final circuit · 1024 shots]
    FINAL --> PROB[_probabilities_from_measurement_counts]
    PROB --> OUT[AlignmentBreakdown 0–100%]

    style OPT fill:#f0f4f8,stroke:#1a5f7a
    style FINAL fill:#e8f0e8,stroke:#2d6a4f
```

**Parameter search:** `scipy.optimize.minimize(..., method="COBYLA")`, `maxiter=30`, `rhobeg=0.35`, initial \((\gamma,\beta)\approx(1.047, 0.524)\).

**Bounds:** \(\gamma \in [0,\pi]\), \(\beta \in [0,\pi/2]\).

**Circuit layers:** Hadamard → \(R_z(\gamma(2t_i-1))\) + \(R_{ZZ}(-\lambda\gamma)\) on \((0,1),(1,2)\) → \(R_x(2\beta)\).

### Score readout

\[
\begin{aligned}
\mathrm{CF\%} &= 100 \cdot t_{\mathrm{cf}} \cdot \mathbb{E}[x_0] \\
\mathrm{App\%} &= 100 \cdot t_{\mathrm{rate}} \cdot \mathbb{E}[x_1] \\
\mathrm{Loc\%} &= 100 \cdot t_{\mathrm{loc}} \cdot \mathbb{E}[x_2] \\
\mathrm{Combined\%} &= 100 \cdot t_{\mathrm{cf}} \cdot t_{\mathrm{rate}} \cdot \mathbb{E}[x_0]\mathbb{E}[x_1] \\
\mathrm{Overall\%} &= 0.45\cdot\mathrm{CF\%} + 0.35\cdot\mathrm{App\%} + 0.20\cdot\mathrm{Loc\%}
\end{aligned}
\]

Negative cash flow cannot inflate cash-flow success because \(t_{\mathrm{cf}}=0\) zeros that term.

> Shipping path uses CPU **`AerSimulator`** for reproducible CI golden values (`seed_simulator=42`). Full Ising derivation: [`docs/QUANTUM_METHOD.md`](docs/QUANTUM_METHOD.md).

---

## Data Plane & Knowledge Base

```mermaid
erDiagram
    properties ||--o{ user_property_overrides : "per-user assumptions"
    properties ||--o{ user_saved_properties : "bookmarks ≤20"
    properties ||--o{ property_comparables : "normalized comps"
    properties ||--o| archived_properties : "age > 30d"

    properties {
        uuid id PK
        text address UK
        float price
        float original_ai_rent
        float monthly_net_cash_flow
        float forecast_rate
        float location_score
        float quantum_risk_score
        jsonb comps_analysis
        timestamptz timestamp
    }

    user_property_overrides {
        uuid user_id
        uuid property_id
        float rent
        float maint_percent
        float vacancy_rate
        float management_fee
        bool is_outlier
    }
```

```mermaid
flowchart LR
    subgraph Reads
        L[lookup_property] --> C[Canonical row ≤30d]
        C --> M[Merge user overrides]
        M --> N[Normalize tax / insurance / rent]
    end

    subgraph Writes
        S[save_canonical_property] --> ROI{1y ROI reliable?}
        ROI -->|no| REJECT[Skip save]
        ROI -->|yes| UPSERT[Upsert on address]
        O[save_user_property_override] --> OV[user_property_overrides]
        H[save_harvest_property] --> UPSERT
        H --> RPC[save_property_comps RPC]
    end

    CTX[get_kb_context] --> PROMPT[LLM synthesis prompt]
```

Auth: browser JWT → FastAPI middleware binds a request-scoped Supabase client. Harvester / archive paths use **`SUPABASE_SERVICE_ROLE_KEY`**. Admin catalog ownership: **`ADMIN_USER_ID`**.

---

## Repository Structure

```
RealEstateAI/
├── api/                      # FastAPI (health, properties, analysis jobs, PDF, validation)
│   ├── main.py               # App, CORS, JWT middleware
│   ├── jobs.py               # In-memory async job store
│   └── routes/               # HTTP surface
├── web/                      # React + Vite SPA (Netlify)
├── assets/                   # README figures (architecture, QAOA circuit)
├── engine.py                 # Gemini agents, rate limits, quantum risk wrappers
├── quantum_portfolio.py      # QAOA portfolio alignment (Aer + COBYLA)
├── finance.py                # Cash flow, appreciation MC, normalizers
├── knowledge_base.py         # Supabase catalog, overrides, KB context
├── comps_analysis.py         # Sale comps
├── rent_comps_analysis.py    # Rental comps + rent uplift
├── harvester.py              # Optional batch discovery CLI
├── discovery/                # Listing source adapters & parsers
├── services/                 # property_analysis_flow, deferred_analysis
├── validation/               # Backtesting helpers
├── docs/                     # DEPLOY, HARVESTER_SETUP, …
├── test_app.py               # Domain / quantum / finance / KB tests
├── test_api.py               # API tests
├── docker-compose.yml
├── Dockerfile
├── netlify.toml
└── .env.example
```

---

## Setup & Installation

### Prerequisites

- **Python 3.11+** (Dockerfile / CI)
- **Node 20+**
- Supabase project (Auth + Postgres)
- Google AI / Gemini API key

### 1. Clone and Python environment

```bash
git clone <repository-url> CapEigen
cd CapEigen

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install pytest ruff mypy   # optional QA tooling
```

Core deps: **`qiskit`**, **`qiskit-aer`**, **`scipy`**, **`google-genai`**, **`supabase`** (PostgREST via client).

### 2. Environment variables

Copy `.env.example` → `.env`:

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google GenAI client |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Anon / publishable key |
| `SUPABASE_SERVICE_ROLE_KEY` | Harvester / admin RPCs |
| `ADMIN_USER_ID` | Admin UUID (catalog / validation) |
| `CORS_ORIGINS` | Comma-separated SPA origins |

Frontend (`web/.env`):

| Variable | Purpose |
|----------|---------|
| `VITE_SUPABASE_URL` | Same project URL |
| `VITE_SUPABASE_ANON_KEY` | Browser-safe anon key |
| `VITE_API_URL` | Public API base (empty locally → Vite `/api` proxy) |

Add your Netlify (or local) origin to Supabase Auth redirect URLs.

### 3. Run the stack

```bash
# API (Docker)
docker compose up --build
# http://localhost:8000/api/health · OpenAPI /docs

# API (local)
uvicorn api.main:app --reload --port 8000

# Frontend
cd web && npm install && npm run dev
# http://localhost:5173

# Tests
# Windows PowerShell:
$env:GEMINI_API_KEY = "fake_key_for_ci"
pytest test_app.py test_api.py -v
```

---

## Usage & API Specs

### Portfolio alignment (library)

```python
from quantum_portfolio import PortfolioInputs, score_portfolio

breakdown = score_portfolio(
    PortfolioInputs(
        monthly_cash_flow=1000.0,
        forecast_rate=10.0,
        location_score=10.0,
    )
)

print(breakdown.overall_success_pct)
print(breakdown.to_dict())
# cashflow_success_pct, appreciation_success_pct,
# location_success_pct, combined_wealth_success_pct, overall_success_pct
```

### Application wrapper (cached)

```python
from engine import calculate_quantum_risk, clear_quantum_risk_cache

risk = calculate_quantum_risk(500.0, 5.0, 5.0)  # CF, rate %, location 0–10
assert 0.0 <= risk["overall_success_pct"] <= 100.0

risk = calculate_quantum_risk(
    cash_flow=800.0,
    forecast_rate=6.5,
    location_score=7.0,
)

clear_quantum_risk_cache()  # before tests that patch the optimizer
```

With Aer seed `42` and COBYLA `maxiter=30`, “perfect” inputs `(1000, 10, 10)` are pinned in `test_app.py` (overall ≈ **50.25%**).

### HTTP surface

| Area | Role |
|------|------|
| `GET /api/health` | Liveness |
| Properties / analysis | Auth underwriting jobs; poll by `job_id` |
| Guest / compare PDF / validation | Sharing, export, admin checks |

OpenAPI: `/docs` when the API is running.

---

## Testing & Quality Assurance

```mermaid
flowchart LR
    CI[GitHub Actions CI] --> RUFF[ruff check .]
    CI --> MYPY[mypy quantum_portfolio.py engine.py]
    CI --> PY[pytest test_app.py test_api.py]
    CI --> WEB[npm ci && npm run build]
    PY --> GOLD[QAOA golden floats]
    PY --> SEED[Aer seed_simulator=42]
    PY --> MOCK[wraps=scipy_minimize]
```

| Layer | Location | Focus |
|-------|----------|-------|
| Domain / quantum | `test_app.py` | Goldens, bounds, determinism, finance MC, rent/tax normalizers, KB, discovery, deferred analysis |
| API | `test_api.py` | FastAPI routes |
| Lint / types | Ruff + mypy | Core modules |
| Frontend | Vite production build | `web/` |

**Quantum instrumentation:**

- Golden snapshots for perfect / average inputs under seed `42`
- `patch("quantum_portfolio.minimize", wraps=scipy_minimize)` — assert COBYLA call/skip
- `patch.object(AerSimulator, "run", ...)` — assert `seed_simulator=42`
- `clear_quantum_risk_cache()` before uncached QAOA assertions
- Gemini / Supabase mocked; CI uses `GEMINI_API_KEY=fake_key_for_ci`

---

## Further Reading

| Document | Contents |
|----------|----------|
| [`docs/QUANTUM_METHOD.md`](docs/QUANTUM_METHOD.md) | Cost Hamiltonian → Ising derivation |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Deployment |
| [`docs/HARVESTER_SETUP.md`](docs/HARVESTER_SETUP.md) | Batch harvester |
| [`AGENTS.md`](AGENTS.md) | Contributor / Cloud agent runbook |

---

## License

Proprietary unless otherwise stated by the repository owner. Contact the maintainers for redistribution terms.
