"""Health and identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import CurrentUser
from api.schemas import HealthResponse, MeResponse
from authenticate import using_local_database

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    backend = "local-postgres" if using_local_database() else "supabase"
    return HealthResponse(data_backend=backend)


@router.get("/api/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user["id"], email=user.get("email"))
