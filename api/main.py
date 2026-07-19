"""CapEigen FastAPI entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.deps import client_from_jwt
from api.routes import analysis, compare_pdf, guest, health, properties, validation
from authenticate import reset_request_supabase_client, set_request_supabase_client
from config_secrets import load_streamlit_secrets_into_environ


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    load_streamlit_secrets_into_environ()
    yield


app = FastAPI(title="CapEigen API", version="1.0.0", lifespan=lifespan)

_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8888",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def bind_supabase_jwt(request: Request, call_next):  # type: ignore[no-untyped-def]
    auth = request.headers.get("Authorization") or ""
    token = None
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    reset_token = None
    if token:
        try:
            client = client_from_jwt(token)
            reset_token = set_request_supabase_client(client)
        except Exception:
            reset_token = None
    try:
        return await call_next(request)
    finally:
        if reset_token is not None:
            reset_request_supabase_client(reset_token)


app.include_router(health.router)
app.include_router(properties.router)
app.include_router(analysis.router)
app.include_router(guest.router)
app.include_router(compare_pdf.router)
app.include_router(validation.router)


@app.get("/")
def root() -> dict[str, str]:
    """Browser landing for the API host (UI is the Netlify/Vite SPA)."""
    return {
        "service": "capeigen-api",
        "health": "/api/health",
        "docs": "/docs",
        "frontend_hint": "Run the UI with: cd web && npm run dev → http://localhost:5173",
    }
