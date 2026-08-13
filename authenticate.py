"""Headless Supabase client helpers for CapEigen API and CLI jobs."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from urllib.parse import urlsplit
from typing import Any

from supabase import Client, create_client

from config_secrets import (
    load_local_secrets_into_environ,
    normalize_secret_value,
    normalize_supabase_url,
)

# Set by FastAPI request middleware so knowledge_base uses the caller's JWT.
_request_supabase_client: ContextVar[Client | None] = ContextVar(
    "request_supabase_client", default=None
)


def set_request_supabase_client(client: Client | None) -> Token:
    """Bind a per-request Supabase client (FastAPI). Returns a reset token."""
    return _request_supabase_client.set(client)


def reset_request_supabase_client(token: Token) -> None:
    """Clear the per-request Supabase client binding."""
    _request_supabase_client.reset(token)


def get_request_supabase_client() -> Client | None:
    """Return the FastAPI-bound client when present."""
    return _request_supabase_client.get()


def _get_secret(name: str) -> str:
    """Require a secret from the environment (optionally seeded from legacy TOML)."""
    load_local_secrets_into_environ()
    value = normalize_secret_value(os.getenv(name))
    if value:
        if name == "SUPABASE_URL":
            return normalize_supabase_url(value)
        return value
    raise EnvironmentError(
        f"{name} not set. Add it to environment variables or a local .env / secrets file."
    )


def _get_optional_secret(name: str) -> str | None:
    """Return a secret when set; None if missing (no error)."""
    load_local_secrets_into_environ()
    return normalize_secret_value(os.getenv(name))


def get_supabase() -> Client:
    """Return an anon-key Supabase client."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    return create_client(url, key)


def get_service_client() -> Client | None:
    """
    Service-role client for trusted headless jobs (harvester, backfill scripts).

    Uses SUPABASE_SERVICE_ROLE_KEY — never expose this key to browsers.
    """
    key = _get_optional_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    url = _get_secret("SUPABASE_URL")
    return create_client(url, key)


def get_authenticated_client() -> Client | None:
    """Supabase client with the logged-in user's JWT (required for RLS)."""
    return _request_supabase_client.get()


def get_db_client() -> Client:
    """Prefer authenticated session; else service role; else anon."""
    auth_client = get_authenticated_client()
    if auth_client is not None:
        return auth_client
    service_client = get_service_client()
    if service_client is not None:
        return service_client
    return get_supabase()


def get_logged_in_user() -> dict[str, str] | None:
    """
    Return ``{'id': uid, 'email': email}`` when a request-bound client has a user.

    Headless CLI / jobs without a JWT return None.
    """
    client = _request_supabase_client.get()
    if client is None:
        return None
    try:
        response = client.auth.get_user()
        user = getattr(response, "user", None)
        if user is None or not getattr(user, "id", None):
            return None
        return {"id": str(user.id), "email": str(getattr(user, "email", None) or "")}
    except Exception:
        return None


def _normalize_app_url(url: str) -> str:
    """Canonical app origin (no path/query/trailing slash)."""
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        return cleaned
    parts = urlsplit(cleaned)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return cleaned


def _is_localhost_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
