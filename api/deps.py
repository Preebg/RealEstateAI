"""JWT auth and Supabase / local PostgREST client helpers for the FastAPI layer."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from authenticate import (
    get_auth_base_url,
    get_data_base_url,
    using_local_database,
    _drop_local_postgrest_bearer,
)
from config_secrets import normalize_secret_value

_bearer = HTTPBearer(auto_error=False)


def _require_env(name: str) -> str:
    value = normalize_secret_value(os.getenv(name))
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing required environment variable: {name}",
        )
    return value


def get_supabase_url() -> str:
    """Data API base URL (local gateway or hosted Supabase)."""
    return get_data_base_url()


def get_anon_key() -> str:
    return _require_env("SUPABASE_KEY")


def get_anon_client() -> Client:
    return _drop_local_postgrest_bearer(create_client(get_supabase_url(), get_anon_key()))


def get_auth_anon_client() -> Client:
    """Client for Supabase Auth only (remote project)."""
    return create_client(get_auth_base_url(), get_anon_key())


def get_service_client() -> Client | None:
    key = normalize_secret_value(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not key:
        return None
    return _drop_local_postgrest_bearer(create_client(get_supabase_url(), key))


def get_auth_service_client() -> Client | None:
    """Service-role client pointed at Supabase Auth (never the local PostgREST gateway)."""
    key = normalize_secret_value(os.getenv("SUPABASE_AUTH_SERVICE_ROLE_KEY")) or normalize_secret_value(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not key or not key.startswith("eyJ"):
        return None
    return create_client(get_auth_base_url(), key)


def client_from_jwt(access_token: str) -> Client:
    """Build a data client scoped to the caller's access token (hosted RLS)."""
    client = create_client(get_supabase_url(), get_anon_key())
    client.auth.set_session(access_token, "")
    return _drop_local_postgrest_bearer(client)


def data_client_for_request(access_token: str) -> Client:
    """
    Data client for an authenticated API request.

    Local DB: service-role (or anon) against PostgREST — FastAPI already validated the JWT.
    Hosted Supabase: JWT-scoped client so RLS still applies.
    """
    if using_local_database():
        service = get_service_client()
        if service is not None:
            return service
        return get_anon_client()
    return client_from_jwt(access_token)


def user_from_token(access_token: str) -> dict[str, Any]:
    client = get_auth_anon_client()
    try:
        response = client.auth.get_user(access_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc
    user = getattr(response, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )
    return {
        "id": str(user.id),
        "email": getattr(user, "email", None),
        "user_metadata": getattr(user, "user_metadata", None) or {},
        "app_metadata": getattr(user, "app_metadata", None) or {},
    }


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token required",
        )
    return user_from_token(credentials.credentials)


async def get_optional_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> dict[str, Any] | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return user_from_token(credentials.credentials)
    except HTTPException:
        return None


async def get_user_client(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> Client:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token required",
        )
    user_from_token(credentials.credentials)
    return data_client_for_request(credentials.credentials)


async def get_admin_user(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    admin_id = normalize_secret_value(os.getenv("ADMIN_USER_ID"))
    if not admin_id or user.get("id") != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
OptionalUser = Annotated[dict[str, Any] | None, Depends(get_optional_user)]
UserClient = Annotated[Client, Depends(get_user_client)]
AdminUser = Annotated[dict[str, Any], Depends(get_admin_user)]
