"""Preview-user tracking ingest and admin activity feed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.deps import AdminUser, CurrentUser
from api.preview_activity import (
    ALLOWED_EVENT_TYPES,
    list_preview_events,
    preview_username_for_user,
    record_preview_event,
)
from api.schemas import PreviewEventCreateRequest, PreviewEventListResponse

router = APIRouter(tags=["preview"])


@router.post("/api/preview/events")
def ingest_preview_event(
    body: PreviewEventCreateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    username = preview_username_for_user(user)
    if username is None:
        raise HTTPException(status_code=403, detail="Preview tracking is only for demo logins.")
    kind = body.event_type.strip().lower()
    if kind not in ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown event type.")
    ok = record_preview_event(
        user_id=str(user["id"]),
        username=username,
        event_type=kind,
        path=body.path,
        label=body.label,
        payload=body.payload,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Could not record preview activity.")
    return {"ok": True}


@router.get("/api/preview/activity", response_model=PreviewEventListResponse)
def preview_activity(
    _admin: AdminUser,
    username: str | None = Query(default="salifT"),
    limit: int = Query(default=200, ge=1, le=500),
) -> PreviewEventListResponse:
    events = list_preview_events(username=username, limit=limit)
    return PreviewEventListResponse(events=events, count=len(events))
