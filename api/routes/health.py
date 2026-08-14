"""Health and identity endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter

from api.deps import CurrentUser
from api.preview_activity import preview_username_for_user
from api.schemas import HealthResponse, MeResponse
from authenticate import using_local_database
from config_secrets import normalize_secret_value

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    backend = "local-postgres" if using_local_database() else "supabase"
    return HealthResponse(data_backend=backend)


@router.get("/api/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    meta = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    username = meta.get("username") if isinstance(meta, dict) else None
    preview_name = preview_username_for_user(user)
    admin_id = normalize_secret_value(os.getenv("ADMIN_USER_ID"))
    return MeResponse(
        id=user["id"],
        email=user.get("email"),
        username=str(preview_name or username) if (preview_name or username) else None,
        is_admin=bool(admin_id and user.get("id") == admin_id),
        is_preview=preview_name is not None,
    )
