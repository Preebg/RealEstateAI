"""CapEigen FastAPI entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.deps import data_client_for_request, user_from_token
from api.routes import (
    analysis,
    auth_demo,
    auth_google,
    compare_pdf,
    guest,
    health,
    preview_activity,
    properties,
    validation,
)
from authenticate import (
    ensure_catalog_admin_config,
    reset_request_supabase_client,
    reset_request_user,
    set_request_supabase_client,
    set_request_user,
)
from config_secrets import load_local_secrets_into_environ, normalize_secret_value


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    load_local_secrets_into_environ()
    admin_id = normalize_secret_value(os.getenv("ADMIN_USER_ID"))
    if admin_id:
        ensure_catalog_admin_config(admin_id)
    yield


app = FastAPI(title="CapEigen API", version="1.0.0", lifespan=lifespan)

_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8888,https://capeigen.preebg.dev",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?netlify\.app",
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
    reset_client_token = None
    reset_user_token = None
    if token:
        try:
            user = user_from_token(token)
            reset_user_token = set_request_user(
                {"id": str(user["id"]), "email": str(user.get("email") or "")}
            )
            client = data_client_for_request(token)
            reset_client_token = set_request_supabase_client(client)
        except Exception:
            if reset_user_token is not None:
                reset_request_user(reset_user_token)
                reset_user_token = None
            reset_client_token = None
    try:
        return await call_next(request)
    finally:
        if reset_client_token is not None:
            reset_request_supabase_client(reset_client_token)
        if reset_user_token is not None:
            reset_request_user(reset_user_token)


app.include_router(health.router)
app.include_router(auth_demo.router)
app.include_router(auth_google.router)
app.include_router(preview_activity.router)
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
