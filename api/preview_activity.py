"""Persist and summarize in-app usage events for every signed-in user."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from postgrest.exceptions import APIError

from api.preview_usernames import PREVIEW_EMAIL_DOMAIN, resolve_preview_username
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

Audience = Literal["all", "demo", "registered"]

ACTION_LABELS: dict[str, str] = {
    "login": "Signed in",
    "page_view": "Opened page",
    "analyze": "Analyzed property",
    "compare": "Ran compare",
    "pdf": "Downloaded PDF",
    "share": "Created share link",
    "bookmark": "Saved property",
    "assumption_change": "Moved assumption sliders",
    "sign_out": "Signed out",
}


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


def actor_for_user(user: dict[str, Any]) -> tuple[str, bool]:
    """Display label and whether the actor is a demo/preview login."""
    preview = preview_username_for_user(user)
    if preview:
        return preview, True
    email = str(user.get("email") or "").strip()
    if email:
        return email[:200], False
    return str(user.get("id") or "unknown")[:200], False


def _data_client() -> Any:
    return get_service_client() or get_db_client()


def record_preview_event(
    *,
    user_id: str,
    username: str,
    event_type: str,
    path: str | None = None,
    label: str | None = None,
    payload: dict[str, Any] | None = None,
    is_preview: bool | None = None,
) -> bool:
    """Insert one usage event. Returns False when storage is unavailable."""
    kind = event_type.strip().lower()
    if kind not in ALLOWED_EVENT_TYPES:
        return False
    client = _data_client()
    preview_flag = bool(is_preview) if is_preview is not None else False
    row: dict[str, Any] = {
        "user_id": user_id,
        "username": username,
        "event_type": kind,
        "path": (path or "")[:300] or None,
        "label": (label or "")[:400] or None,
        "payload": payload or {},
        "is_preview": preview_flag,
    }
    try:
        client.table("preview_events").insert(row).execute()
    except APIError as exc:
        if "is_preview" in row:
            fallback = dict(row)
            fallback.pop("is_preview", None)
            try:
                client.table("preview_events").insert(fallback).execute()
            except APIError as retry_exc:
                report_error(log, "preview_event_insert_failed", retry_exc, event_type=kind)
                return False
            return True
        report_error(log, "preview_event_insert_failed", exc, event_type=kind)
        return False
    return True


def _apply_audience_filter(query: Any, audience: Audience) -> Any:
    if audience == "demo":
        return query.eq("is_preview", True)
    if audience == "registered":
        return query.eq("is_preview", False)
    return query


def list_preview_events(
    *,
    username: str | None = None,
    limit: int = 200,
    audience: Audience = "demo",
) -> list[dict[str, Any]]:
    client = _data_client()
    capped = max(1, min(limit, 500))
    columns = "id,user_id,username,event_type,path,label,payload,created_at,is_preview"
    try:
        query = (
            client.table("preview_events")
            .select(columns)
            .order("created_at", desc=True)
            .limit(capped)
        )
        query = _apply_audience_filter(query, audience)
        if username:
            query = query.eq("username", username)
        response = query.execute()
    except APIError as exc:
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
        except APIError as retry_exc:
            report_error(log, "preview_event_list_failed", retry_exc)
            return []
        report_error(log, "preview_event_list_is_preview_unavailable", exc)
    return response.data or []


def summarize_usage(*, days: int = 90, audience: Audience = "all") -> dict[str, Any]:
    """Aggregate pages and actions so admin can see what people use most."""
    window_days = max(1, min(days, 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    client = _data_client()
    columns = "user_id,username,event_type,path,label,created_at,is_preview"
    events: list[dict[str, Any]] = []
    try:
        query = (
            client.table("preview_events")
            .select(columns)
            .gte("created_at", cutoff.isoformat())
            .order("created_at", desc=True)
            .limit(10000)
        )
        query = _apply_audience_filter(query, audience)
        response = query.execute()
        events = response.data or []
    except APIError as exc:
        try:
            query = (
                client.table("preview_events")
                .select("user_id,username,event_type,path,label,created_at")
                .gte("created_at", cutoff.isoformat())
                .order("created_at", desc=True)
                .limit(10000)
            )
            response = query.execute()
            events = response.data or []
        except APIError as retry_exc:
            report_error(log, "usage_summary_failed", retry_exc)
            events = []
        else:
            report_error(log, "usage_summary_is_preview_unavailable", exc)

    action_events: dict[str, int] = defaultdict(int)
    action_users: dict[str, set[str]] = defaultdict(set)
    page_events: dict[tuple[str, str], int] = defaultdict(int)
    page_users: dict[tuple[str, str], set[str]] = defaultdict(set)
    user_buckets: dict[str, dict[str, Any]] = {}
    unique_users: set[str] = set()

    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("event_type") or "").strip().lower()
        if kind not in ALLOWED_EVENT_TYPES:
            continue
        user_id = str(event.get("user_id") or event.get("username") or "")
        if not user_id:
            continue
        unique_users.add(user_id)
        action_events[kind] += 1
        action_users[kind].add(user_id)

        path = str(event.get("path") or "").strip() or "/"
        page_label = str(event.get("label") or "").strip()
        if kind == "page_view":
            page_key = (path, page_label)
            page_events[page_key] += 1
            page_users[page_key].add(user_id)

        display = str(event.get("username") or user_id)
        bucket_key = display.lower()
        bucket = user_buckets.get(bucket_key)
        if bucket is None:
            bucket = {
                "username": display,
                "is_preview": bool(event.get("is_preview")),
                "event_count": 0,
                "login_count": 0,
                "page_view_count": 0,
                "analyze_count": 0,
                "compare_count": 0,
                "pdf_count": 0,
                "share_count": 0,
                "bookmark_count": 0,
                "last_seen": event.get("created_at"),
            }
            user_buckets[bucket_key] = bucket
        bucket["event_count"] += 1
        count_key = f"{kind}_count"
        if count_key in bucket:
            bucket[count_key] = int(bucket[count_key]) + 1
        created = event.get("created_at")
        last = bucket.get("last_seen")
        if created and (not last or str(created) > str(last)):
            bucket["last_seen"] = created
        if event.get("is_preview") is True:
            bucket["is_preview"] = True

    actions = [
        {
            "event_type": kind,
            "label": ACTION_LABELS.get(kind, kind),
            "events": action_events[kind],
            "unique_users": len(action_users[kind]),
        }
        for kind in sorted(action_events, key=lambda item: action_events[item], reverse=True)
    ]
    pages = [
        {
            "path": path,
            "label": label or path,
            "events": page_events[(path, label)],
            "unique_users": len(page_users[(path, label)]),
        }
        for path, label in sorted(page_events, key=lambda item: page_events[item], reverse=True)
    ][:25]
    users = sorted(
        user_buckets.values(),
        key=lambda item: (-int(item["event_count"]), str(item["username"]).lower()),
    )[:100]

    return {
        "days": window_days,
        "audience": audience,
        "totals": {
            "events": len(events),
            "unique_users": len(unique_users),
            "logins": action_events.get("login", 0),
            "page_views": action_events.get("page_view", 0),
            "analyzes": action_events.get("analyze", 0),
            "compares": action_events.get("compare", 0),
            "pdfs": action_events.get("pdf", 0),
            "shares": action_events.get("share", 0),
            "bookmarks": action_events.get("bookmark", 0),
        },
        "actions": actions,
        "pages": pages,
        "users": users,
    }
