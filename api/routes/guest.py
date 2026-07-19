"""Guest share and authenticated share-link routes."""

from __future__ import annotations

import datetime
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError

from api.deps import CurrentUser, UserClient, get_anon_client
from api.schemas import ShareCreateRequest, ShareCreateResponse
from knowledge_base import is_valid_uuid

router = APIRouter(tags=["guest"])


def _validate_token(token: str) -> dict[str, Any] | None:
    supabase = get_anon_client()
    try:
        response = supabase.rpc(
            "validate_share_token", {"p_token": str(token).strip()}
        ).execute()
    except APIError:
        return None
    payload = response.data
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not payload or not payload.get("valid"):
        return None
    return payload


@router.get("/api/guest/validate")
def guest_validate(token: str = Query(..., min_length=8)) -> dict[str, Any]:
    meta = _validate_token(token)
    if not meta:
        raise HTTPException(status_code=404, detail="Invalid or expired share token")
    return {
        "valid": True,
        "address": meta.get("address"),
        "property_id": meta.get("property_id"),
        "include_assumptions": meta.get("include_assumptions"),
    }


@router.get("/api/guest/portfolio")
def guest_portfolio(token: str = Query(..., min_length=8)) -> dict[str, Any]:
    if not _validate_token(token):
        raise HTTPException(status_code=404, detail="Invalid or expired share token")
    supabase = get_anon_client()
    try:
        response = supabase.rpc(
            "get_guest_portfolio", {"p_share_token": token}
        ).execute()
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"properties": response.data or []}


@router.get("/api/guest/property")
def guest_property(
    token: str = Query(..., min_length=8),
    property_id: str | None = None,
    address: str | None = None,
) -> dict[str, Any]:
    if not _validate_token(token):
        raise HTTPException(status_code=404, detail="Invalid or expired share token")
    supabase = get_anon_client()
    params: dict[str, Any] = {"p_share_token": token}
    if property_id:
        params["p_property_id"] = property_id
    if address:
        params["p_address"] = address
    try:
        response = supabase.rpc("get_guest_property", params).execute()
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    payload = response.data
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not payload or not payload.get("valid"):
        raise HTTPException(status_code=404, detail="Property not found for share")
    prop = payload.get("property")
    return {"property": prop if isinstance(prop, dict) else None}


@router.post("/api/shares", response_model=ShareCreateResponse)
def create_share(
    body: ShareCreateRequest,
    user: CurrentUser,
    client: UserClient,
) -> ShareCreateResponse:
    if not is_valid_uuid(body.property_id):
        raise HTTPException(status_code=400, detail="Invalid property_id")

    token = secrets.token_urlsafe(32)
    expires_at: str | None = None
    if body.expires_days > 0:
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=body.expires_days)
        ).isoformat()

    row = {
        "share_token": token,
        "property_id": body.property_id,
        "created_by": user["id"],
        "include_assumptions": body.include_assumptions,
        "expires_at": expires_at,
    }
    try:
        client.table("property_shares").insert(row).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to create share: {exc}") from exc

    base = (body.base_url or "").strip() or "http://localhost:5173"
    cleaned = base.rstrip("/")
    share_url = f"{cleaned}/share/{token}"
    return ShareCreateResponse(
        share_token=token,
        share_url=share_url,
    )
