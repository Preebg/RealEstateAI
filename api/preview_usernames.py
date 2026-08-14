"""Dashboard-managed preview/demo usernames (allowlist + usage)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from authenticate import get_db_client, get_service_client
from app_logging import configure_logging, report_error
from config_secrets import normalize_secret_value

log = configure_logging("preview_usernames")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,32}$")
PREVIEW_EMAIL_DOMAIN = "demo.capeigen.app"
_DEFAULT_USERNAMES = "salifT"


def preview_email_for(username_key: str) -> str:
    return f"{username_key}@{PREVIEW_EMAIL_DOMAIN}"


def normalize_username(username: str) -> str | None:
    cleaned = (username or "").strip()
    if not USERNAME_RE.fullmatch(cleaned):
        return None
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_client() -> Any | None:
    try:
        return get_service_client() or get_db_client()
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_usernames_client_failed", exc)
        return None


def env_username_map() -> dict[str, str]:
    """Lowercase username -> display form from DEMO_USERNAMES (comma-separated)."""
    raw = normalize_secret_value(os.getenv("DEMO_USERNAMES")) or _DEFAULT_USERNAMES
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        name = part.strip()
        if name and USERNAME_RE.fullmatch(name):
            mapping[name.lower()] = name
    return mapping


def _db_username_rows() -> list[dict[str, Any]]:
    client = _data_client()
    if client is None:
        return []
    try:
        response = (
            client.table("preview_usernames")
            .select("username_key,username,active,created_at,created_by,updated_at")
            .order("created_at")
            .execute()
        )
    except APIError as exc:
        report_error(log, "preview_usernames_list_failed", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_usernames_list_failed", exc)
        return []
    return response.data or []


def preview_username_map() -> dict[str, str]:
    """Active allowlist: dashboard rows override DEMO_USERNAMES, including removals."""
    mapping = dict(env_username_map())
    for row in _db_username_rows():
        key = str(row.get("username_key") or "").strip().lower()
        display = str(row.get("username") or "").strip()
        if not key or not display:
            continue
        if row.get("active") is False:
            mapping.pop(key, None)
        else:
            mapping[key] = display
    return mapping


def resolve_preview_username(username: str) -> str | None:
    cleaned = normalize_username(username)
    if cleaned is None:
        return None
    return preview_username_map().get(cleaned.lower())


def _event_stats() -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    client = _data_client()
    if client is None:
        return stats
    try:
        response = (
            client.table("preview_events")
            .select("username,event_type,created_at")
            .order("created_at", desc=True)
            .limit(2000)
            .execute()
        )
    except APIError as exc:
        report_error(log, "preview_username_stats_failed", exc)
        return stats
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_username_stats_failed", exc)
        return stats

    for event in response.data or []:
        display = str(event.get("username") or "").strip()
        if not display:
            continue
        key = display.lower()
        bucket = stats.get(key)
        if bucket is None:
            bucket = {
                "username": display,
                "event_count": 0,
                "login_count": 0,
                "analyze_count": 0,
                "compare_count": 0,
                "pdf_count": 0,
                "last_seen": event.get("created_at"),
            }
            stats[key] = bucket
        bucket["event_count"] += 1
        kind = str(event.get("event_type") or "")
        if kind == "login":
            bucket["login_count"] += 1
        elif kind == "analyze":
            bucket["analyze_count"] += 1
        elif kind == "compare":
            bucket["compare_count"] += 1
        elif kind == "pdf":
            bucket["pdf_count"] += 1
        created = event.get("created_at")
        last = bucket.get("last_seen")
        if created and (not last or str(created) > str(last)):
            bucket["last_seen"] = created
    return stats


def list_preview_accounts() -> list[dict[str, Any]]:
    """Union of dashboard rows, env allowlist, and usernames seen in activity."""
    db_rows = {str(row.get("username_key") or "").lower(): row for row in _db_username_rows()}
    env_map = env_username_map()
    stats = _event_stats()

    keys = set(db_rows) | set(env_map) | set(stats)
    accounts: list[dict[str, Any]] = []
    for key in keys:
        if not key:
            continue
        row = db_rows.get(key)
        env_display = env_map.get(key)
        usage = stats.get(key) or {}
        if row:
            display = str(row.get("username") or env_display or usage.get("username") or key)
            active = row.get("active") is not False
            source = "dashboard"
            created_at = row.get("created_at")
        elif env_display:
            display = env_display
            active = True
            source = "environment"
            created_at = None
        else:
            display = str(usage.get("username") or key)
            active = False
            source = "activity"
            created_at = None
        accounts.append(
            {
                "username": display,
                "active": active,
                "source": source,
                "created_at": created_at,
                "created_by": (row or {}).get("created_by"),
                "last_seen": usage.get("last_seen"),
                "event_count": int(usage.get("event_count") or 0),
                "login_count": int(usage.get("login_count") or 0),
                "analyze_count": int(usage.get("analyze_count") or 0),
                "compare_count": int(usage.get("compare_count") or 0),
                "pdf_count": int(usage.get("pdf_count") or 0),
            }
        )
    accounts.sort(key=lambda item: (not item["active"], str(item["username"]).lower()))
    return accounts


def upsert_preview_username(username: str, *, active: bool, created_by: str | None) -> str:
    display = normalize_username(username)
    if display is None:
        raise ValueError("Usernames must be 2–32 letters, numbers, or underscores.")
    client = _data_client()
    if client is None:
        raise RuntimeError("Preview username storage is not available.")
    key = display.lower()
    row = {
        "username_key": key,
        "username": display,
        "active": active,
        "updated_at": _now_iso(),
    }
    if created_by:
        row["created_by"] = created_by
    try:
        client.table("preview_usernames").upsert(row, on_conflict="username_key").execute()
    except APIError as exc:
        report_error(log, "preview_username_upsert_failed", exc, username=display)
        raise RuntimeError("Could not save preview username.") from exc
    return display


def add_preview_username(username: str, *, created_by: str | None) -> str:
    return upsert_preview_username(username, active=True, created_by=created_by)


def remove_preview_username(username: str, *, created_by: str | None) -> str:
    display = upsert_preview_username(username, active=False, created_by=created_by)
    _revoke_preview_auth_user(display)
    return display


def _revoke_preview_auth_user(display: str) -> None:
    """Best-effort: delete the hosted Auth user so an existing session dies sooner."""
    try:
        from api.deps import get_auth_service_client
    except Exception:  # noqa: BLE001
        return
    admin_client = get_auth_service_client()
    if admin_client is None:
        return
    email = preview_email_for(display.lower())
    try:
        admin = admin_client.auth.admin
        user_id = _find_auth_user_id(admin, email)
        if not user_id:
            return
        sign_out = getattr(admin, "sign_out", None)
        if callable(sign_out):
            try:
                sign_out(user_id, "global")
            except Exception:  # noqa: BLE001
                pass
        admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_username_revoke_failed", exc, email=email)


def _find_auth_user_id(admin: Any, email: str) -> str | None:
    getter = getattr(admin, "get_user_by_email", None)
    if callable(getter):
        try:
            payload = getter(email)
            user = getattr(payload, "user", None) or payload
            user_id = getattr(user, "id", None) if user is not None else None
            if user_id is None and isinstance(user, dict):
                user_id = user.get("id")
            if user_id:
                return str(user_id)
        except Exception:  # noqa: BLE001
            pass

    lister = getattr(admin, "list_users", None)
    if not callable(lister):
        return None
    try:
        payload = lister()
    except TypeError:
        try:
            payload = lister(page=1, per_page=200)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None

    users = getattr(payload, "users", None)
    if users is None and isinstance(payload, dict):
        users = payload.get("users")
    if users is None and isinstance(payload, list):
        users = payload
    for user in users or []:
        user_email = getattr(user, "email", None)
        if user_email is None and isinstance(user, dict):
            user_email = user.get("email")
        if str(user_email or "").strip().lower() == email:
            user_id = getattr(user, "id", None)
            if user_id is None and isinstance(user, dict):
                user_id = user.get("id")
            if user_id:
                return str(user_id)
    return None
