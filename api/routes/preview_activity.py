"""Usage tracking ingest, admin activity feed, and legal document admin."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from api.deps import AdminUser, CurrentUser
from api.legal_store import (
    get_legal_acceptance_status,
    get_legal_document,
    save_legal_acceptance,
    save_legal_document,
)
from api.preview_activity import (
    ALLOWED_EVENT_TYPES,
    actor_for_user,
    list_preview_events,
    record_preview_event,
    summarize_usage,
)
from api.preview_usernames import (
    add_preview_username,
    list_preview_accounts,
    permanently_delete_preview_username,
    remove_preview_username,
)
from api.schemas import (
    LegalAcceptanceRequest,
    LegalAcceptanceStatusResponse,
    LegalDocumentResponse,
    LegalDocumentUpdateRequest,
    PreviewAccountCreateRequest,
    PreviewAccountListResponse,
    PreviewEventCreateRequest,
    PreviewEventListResponse,
    UsageSummaryResponse,
)

router = APIRouter(tags=["preview"])

AudienceParam = Literal["all", "demo", "registered"]


@router.post("/api/preview/events")
def ingest_preview_event(
    body: PreviewEventCreateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    username, is_preview = actor_for_user(user)
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
        is_preview=is_preview,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Could not record activity.")
    return {"ok": True}


@router.get("/api/preview/activity", response_model=PreviewEventListResponse)
def preview_activity(
    _admin: AdminUser,
    username: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> PreviewEventListResponse:
    events = list_preview_events(username=username, limit=limit, audience="demo")
    return PreviewEventListResponse(events=events, count=len(events))


@router.get("/api/usage/activity", response_model=PreviewEventListResponse)
def usage_activity(
    _admin: AdminUser,
    username: str | None = Query(default=None),
    audience: AudienceParam = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
) -> PreviewEventListResponse:
    events = list_preview_events(username=username, limit=limit, audience=audience)
    return PreviewEventListResponse(events=events, count=len(events))


@router.get("/api/usage/summary", response_model=UsageSummaryResponse)
def usage_summary(
    _admin: AdminUser,
    days: int = Query(default=90, ge=1, le=365),
    audience: AudienceParam = Query(default="all"),
) -> UsageSummaryResponse:
    payload = summarize_usage(days=days, audience=audience)
    return UsageSummaryResponse(**payload)


@router.get("/api/preview/accounts", response_model=PreviewAccountListResponse)
def preview_accounts(_admin: AdminUser) -> PreviewAccountListResponse:
    accounts = list_preview_accounts()
    return PreviewAccountListResponse(accounts=accounts, count=len(accounts))


@router.post("/api/preview/accounts", response_model=PreviewAccountListResponse)
def create_preview_account(
    body: PreviewAccountCreateRequest,
    admin: AdminUser,
) -> PreviewAccountListResponse:
    try:
        add_preview_username(
            body.username,
            created_by=str(admin.get("email") or admin.get("id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    accounts = list_preview_accounts()
    return PreviewAccountListResponse(accounts=accounts, count=len(accounts))


@router.delete("/api/preview/accounts/{username}", response_model=PreviewAccountListResponse)
def delete_preview_account(
    username: str,
    admin: AdminUser,
) -> PreviewAccountListResponse:
    try:
        remove_preview_username(
            username,
            created_by=str(admin.get("email") or admin.get("id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    accounts = list_preview_accounts()
    return PreviewAccountListResponse(accounts=accounts, count=len(accounts))


@router.delete(
    "/api/preview/accounts/{username}/permanent",
    response_model=PreviewAccountListResponse,
)
def purge_preview_account(
    username: str,
    _admin: AdminUser,
    confirm_username: str = Query(..., min_length=2, max_length=32),
) -> PreviewAccountListResponse:
    if confirm_username.strip().lower() != username.strip().lower():
        raise HTTPException(
            status_code=400,
            detail="Typed username does not match the account to delete.",
        )
    try:
        permanently_delete_preview_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    accounts = list_preview_accounts()
    return PreviewAccountListResponse(accounts=accounts, count=len(accounts))


@router.get("/api/legal/acceptance", response_model=LegalAcceptanceStatusResponse)
def read_legal_acceptance(user: CurrentUser) -> LegalAcceptanceStatusResponse:
    status = get_legal_acceptance_status(str(user["id"]))
    return LegalAcceptanceStatusResponse(**status)


@router.post("/api/legal/acceptance", response_model=LegalAcceptanceStatusResponse)
def accept_current_legal(
    body: LegalAcceptanceRequest,
    user: CurrentUser,
) -> LegalAcceptanceStatusResponse:
    if not body.accepted:
        raise HTTPException(status_code=400, detail="You must accept the updated legal documents.")
    try:
        status = save_legal_acceptance(str(user["id"]))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LegalAcceptanceStatusResponse(**status)


@router.get("/api/legal/{slug}", response_model=LegalDocumentResponse)
def read_legal_document(slug: str) -> LegalDocumentResponse:
    try:
        document = get_legal_document(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LegalDocumentResponse(**document)


@router.put("/api/legal/{slug}", response_model=LegalDocumentResponse)
def update_legal_document(
    slug: str,
    body: LegalDocumentUpdateRequest,
    admin: AdminUser,
) -> LegalDocumentResponse:
    try:
        document = save_legal_document(
            slug,
            body=body.body,
            title=body.title,
            effective_date=body.effective_date,
            updated_by=str(admin.get("email") or admin.get("id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LegalDocumentResponse(**document)
