"""Persist preview-user interaction events (salifT and other allowlisted usernames)."""

from __future__ import annotations

from typing import Any

from postgrest.exceptions import APIError

from api.routes.auth_demo import PREVIEW_EMAIL_DOMAIN, resolve_preview_username
from authenticate import get_db_client, get_service_client
from app_logging import configure_logging, report_error

log = configure_logging("preview_activity")

ALLOWED_EVENT_TYPES = frozenset(
    {
        "login",
        "page_view",
        "analyze",
        "compare",
        "pdf",
        "share",
        "bookmark",
        "assumption_change",
        "sign_out",
    }
)


def preview_username_for_user(user: dict[str, Any]) -> str | None:
    """Return the allowlisted preview username when this account is a demo login."""
    app_meta = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
    if app_meta.get("preview") is True or str(app_meta.get("preview")).lower() == "true":
        raw = str(app_meta.get("username") or "").strip()
        resolved = resolve_preview_username(raw) if raw else None
        if resolved:
            return resolved
    email = str(user.get("email") or "").strip().lower()
    suffix = f"@{PREVIEW_EMAIL_DOMAIN}"
    if email.endswith(suffix):
        local = email[: -len(suffix)]
        return resolve_preview_username(local)
    return None


def record_preview_event(
    *,
    user_id: str,
    username: str,
    event_type: str,
    path: str | None = None,
    label: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Insert one preview event. Returns False when storage is unavailable."""
    kind = event_type.strip().lower()
    if kind not in ALLOWED_EVENT_TYPES:
        return False
    client = get_service_client() or get_db_client()
    row = {
        "user_id": user_id,
        "username": username,
        "event_type": kind,
        "path": (path or "")[:300] or None,
        "label": (label or "")[:400] or None,
        "payload": payload or {},
    }
    try:
        client.table("preview_events").insert(row).execute()
    except APIError as exc:
        report_error(log, "preview_event_insert_failed", exc, event_type=kind)
        return False
    return True


def list_preview_events(*, username: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    client = get_service_client() or get_db_client()
    capped = max(1, min(limit, 500))
    try:
        query = (
            client.table("preview_events")
            .select("id,user_id,username,event_type,path,label,payload,created_at")
            .order("created_at", desc=True)
            .limit(capped)
        )
        if username:
            query = query.eq("username", username)
        response = query.execute()
    except APIError as exc:
        report_error(log, "preview_event_list_failed", exc)
        return []
    return response.data or []
