"""Allowlisted preview usernames that issue a real Supabase session (no signup)."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.deps import get_anon_key, get_auth_anon_client, get_auth_service_client
from api.preview_usernames import (
    preview_email_for,
    resolve_preview_username,
)
from api.schemas import PreviewLoginRequest, PreviewLoginResponse
from app_logging import configure_logging, report_error

router = APIRouter(tags=["auth"])
log = configure_logging("auth_demo")

_hits: dict[str, list[float]] = {}


def _rate_limit(ip: str) -> None:
    flag = (os.getenv("DEMO_LOGIN_RATE_LIMIT") or "1").strip().lower()
    if flag in {"0", "false", "off"}:
        return
    window = 15 * 60
    max_hits = 12
    now = time.time()
    stamps = [t for t in _hits.get(ip, []) if now - t < window]
    if len(stamps) >= max_hits:
        raise HTTPException(
            status_code=429,
            detail="Too many preview login attempts. Try again later.",
        )
    stamps.append(now)
    _hits[ip] = stamps


def _attr_or_key(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _hashed_token(payload: Any) -> str | None:
    props = _attr_or_key(payload, "properties") or payload
    token = _attr_or_key(props, "hashed_token")
    return str(token) if token else None


def _session_tokens(payload: Any) -> tuple[str, str]:
    session = _attr_or_key(payload, "session") or payload
    access = _attr_or_key(session, "access_token")
    refresh = _attr_or_key(session, "refresh_token")
    if not access or not refresh:
        raise HTTPException(
            status_code=502,
            detail="Preview login did not return a session.",
        )
    return str(access), str(refresh)


def _ensure_preview_user(admin: Any, email: str, display: str) -> None:
    try:
        admin.create_user(
            {
                "email": email,
                "email_confirm": True,
                "user_metadata": {"username": display, "full_name": display},
                "app_metadata": {"preview": True, "username": display},
            }
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "already" in message or "registered" in message or "exists" in message:
            return
        raise HTTPException(
            status_code=502,
            detail="Could not create preview user.",
        ) from exc


def issue_preview_session(display_username: str) -> tuple[str, str]:
    admin_client = get_auth_service_client()
    if admin_client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Preview login is not configured. Set SUPABASE_SERVICE_ROLE_KEY "
                "on the API host."
            ),
        )

    email = preview_email_for(display_username.lower())
    admin = admin_client.auth.admin
    _ensure_preview_user(admin, email, display_username)

    try:
        link = admin.generate_link({"type": "magiclink", "email": email})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail="Could not start preview login.",
        ) from exc

    hashed = _hashed_token(link)
    if not hashed:
        raise HTTPException(
            status_code=502,
            detail="Preview login did not return a verification token.",
        )

    try:
        verified = get_auth_anon_client().auth.verify_otp(
            {"type": "magiclink", "token_hash": hashed}
        )
    except Exception:
        try:
            verified = get_auth_anon_client().auth.verify_otp(
                {"type": "email", "token_hash": hashed}
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not complete preview login.",
            ) from exc

    return _session_tokens(verified)


@router.post("/api/auth/demo", response_model=PreviewLoginResponse)
def preview_login(body: PreviewLoginRequest, request: Request) -> PreviewLoginResponse:
    ip = request.client.host if request.client else "unknown"
    _rate_limit(ip)

    display = resolve_preview_username(body.username)
    if display is None:
        raise HTTPException(
            status_code=403,
            detail="Unknown preview username.",
        )

    # Anon key must exist so verify_otp can mint a browser session.
    get_anon_key()
    access, refresh = issue_preview_session(display)
    try:
        from api.deps import user_from_token
        from api.preview_activity import record_preview_event

        preview_user = user_from_token(access)
        record_preview_event(
            user_id=str(preview_user["id"]),
            username=display,
            event_type="login",
            path="/login",
            label="Preview login",
            payload={"username": display},
            is_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_login_track_failed", exc)
    return PreviewLoginResponse(
        access_token=access,
        refresh_token=refresh,
        username=display,
    )
