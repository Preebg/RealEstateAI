"""Exchange Google OAuth authorization codes for ID tokens (CapEigen-owned redirect)."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["auth"])


class GoogleExchangeRequest(BaseModel):
    code: str = Field(min_length=1)
    code_verifier: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class GoogleExchangeResponse(BaseModel):
    id_token: str


def _google_web_credentials() -> tuple[str, str]:
    client_id = (
        os.getenv("GOOGLE_WEB_CLIENT_ID")
        or os.getenv("VITE_GOOGLE_CLIENT_ID")
        or ""
    ).strip()
    client_secret = (os.getenv("GOOGLE_WEB_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth is not configured on the API. Set GOOGLE_WEB_CLIENT_ID "
                "and GOOGLE_WEB_CLIENT_SECRET."
            ),
        )
    return client_id, client_secret


@router.post("/api/auth/google/exchange", response_model=GoogleExchangeResponse)
def exchange_google_code(body: GoogleExchangeRequest) -> GoogleExchangeResponse:
    """Trade a Google auth code (PKCE) for an OIDC id_token. No Supabase redirect involved."""
    client_id, client_secret = _google_web_credentials()
    data = {
        "code": body.code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": body.redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": body.code_verifier,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post("https://oauth2.googleapis.com/token", data=data)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Google token request failed: {exc}") from exc

    payload: dict[str, Any]
    try:
        payload = res.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid response from Google") from exc

    if res.status_code >= 400:
        detail = payload.get("error_description") or payload.get("error") or res.text
        raise HTTPException(status_code=400, detail=str(detail))

    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise HTTPException(status_code=502, detail="Google did not return an id_token")

    return GoogleExchangeResponse(id_token=id_token)
