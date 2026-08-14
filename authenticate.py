"""Headless Supabase / local PostgREST client helpers for CapEigen API and CLI jobs."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from urllib.parse import urlsplit

from supabase import Client, create_client

from config_secrets import (
    load_local_secrets_into_environ,
    normalize_secret_value,
    normalize_supabase_url,
)

# Set by FastAPI request middleware so knowledge_base uses the caller's data client.
_request_supabase_client: ContextVar[Client | None] = ContextVar(
    "request_supabase_client", default=None
)
# User identity from Supabase Auth (may differ from the data client base URL).
_request_user: ContextVar[dict[str, str] | None] = ContextVar(
    "request_user", default=None
)


def set_request_supabase_client(client: Client | None) -> Token:
    """Bind a per-request data client (FastAPI). Returns a reset token."""
    return _request_supabase_client.set(client)


def reset_request_supabase_client(token: Token) -> None:
    """Clear the per-request data client binding."""
    _request_supabase_client.reset(token)


def get_request_supabase_client() -> Client | None:
    """Return the FastAPI-bound data client when present."""
    return _request_supabase_client.get()


def set_request_user(user: dict[str, str] | None) -> Token:
    """Bind authenticated user identity for the current request."""
    return _request_user.set(user)


def reset_request_user(token: Token) -> None:
    """Clear the per-request user binding."""
    _request_user.reset(token)


def _get_secret(name: str) -> str:
    """Require a secret from the environment (optionally seeded from legacy TOML)."""
    load_local_secrets_into_environ()
    value = normalize_secret_value(os.getenv(name))
    if value:
        if name in {"SUPABASE_URL", "SUPABASE_AUTH_URL", "DATABASE_REST_URL"}:
            return normalize_supabase_url(value)
        return value
    raise EnvironmentError(
        f"{name} not set. Add it to environment variables or a local .env / secrets file."
    )


def _get_optional_secret(name: str) -> str | None:
    """Return a secret when set; None if missing (no error)."""
    load_local_secrets_into_environ()
    value = normalize_secret_value(os.getenv(name))
    if not value:
        return None
    if name in {"SUPABASE_URL", "SUPABASE_AUTH_URL", "DATABASE_REST_URL"}:
        return normalize_supabase_url(value)
    return value


def using_local_database() -> bool:
    """True when FastAPI/harvester data should use self-hosted PostgREST."""
    return bool(_get_optional_secret("DATABASE_REST_URL"))


def _drop_local_postgrest_bearer(client: Client) -> Client:
    """
    Local PostgREST has no JWT secret. supabase-py always sets Authorization,
    which makes PostgREST return PGRST300. FastAPI already validated the user JWT.
    """
    if not using_local_database():
        return client
    postgrest = getattr(client, "postgrest", None)
    if postgrest is None:
        return client
    for headers in (
        getattr(postgrest, "headers", None),
        getattr(getattr(postgrest, "session", None), "headers", None),
    ):
        if headers is None:
            continue
        headers.pop("Authorization", None)
        headers.pop("authorization", None)
    return client


def _data_client(url: str, key: str) -> Client:
    return _drop_local_postgrest_bearer(create_client(url, key))


def get_auth_base_url() -> str:
    """Supabase Auth project URL (remote). Falls back to SUPABASE_URL."""
    return _get_optional_secret("SUPABASE_AUTH_URL") or _get_secret("SUPABASE_URL")


def get_data_base_url() -> str:
    """
    Data API base URL for ``create_client`` (expects ``/rest/v1`` underneath).

    When ``DATABASE_REST_URL`` is set (local PostgREST gateway), use that.
    Otherwise use the same project URL as Auth (hosted Supabase).
    """
    return _get_optional_secret("DATABASE_REST_URL") or get_auth_base_url()


def get_supabase() -> Client:
    """Return an anon-key data client."""
    url = get_data_base_url()
    key = _get_secret("SUPABASE_KEY")
    return _data_client(url, key)


def get_auth_client() -> Client:
    """Return a client pointed at Supabase Auth (not the local data gateway)."""
    url = get_auth_base_url()
    key = _get_secret("SUPABASE_KEY")
    return create_client(url, key)


def get_service_client() -> Client | None:
    """
    Service-role data client for trusted headless jobs (harvester, backfill scripts).

    Uses SUPABASE_SERVICE_ROLE_KEY — never expose this key to browsers.
    On local PostgREST, any non-empty key works (JWT verification is disabled).
    """
    key = _get_optional_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    return _data_client(get_data_base_url(), key)


def get_authenticated_client() -> Client | None:
    """Data client bound for the current request (required for RLS on hosted Supabase)."""
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
    Return ``{'id': uid, 'email': email}`` when a request has an authenticated user.

    Prefers the middleware-bound identity (works with local data + remote Auth).
    Headless CLI / jobs without a JWT return None.
    """
    bound = _request_user.get()
    if bound is not None:
        return bound

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


def ensure_catalog_admin_config(admin_user_id: str) -> None:
    """
    Persist ``ADMIN_USER_ID`` into local Postgres ``app_runtime_config``.

    No-op when not using ``DATABASE_REST_URL``.
    """
    if not using_local_database():
        return
    if not admin_user_id:
        return
    client = get_service_client() or get_supabase()
    try:
        client.rpc("set_catalog_admin_user_id", {"p_uid": admin_user_id}).execute()
    except Exception:
        # Best-effort: harvest/API still set user_id on rows explicitly.
        pass


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
