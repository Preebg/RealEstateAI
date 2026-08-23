"""Dashboard-managed preview/demo usernames (allowlist + usage)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from authenticate import get_data_base_url, using_local_database
from app_logging import configure_logging, report_error
from config_secrets import normalize_secret_value

log = configure_logging("preview_usernames")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,32}$")
PREVIEW_EMAIL_DOMAIN = "demo.capeigen.app"
_DEFAULT_USERNAMES = "salifT"
_CONFIG_KEY = "preview_usernames"
_PURGED_CONFIG_KEY = "preview_usernames_purged"


def preview_email_for(username_key: str) -> str:
    return f"{username_key}@{PREVIEW_EMAIL_DOMAIN}"


def normalize_username(username: str) -> str | None:
    cleaned = (username or "").strip()
    if not USERNAME_RE.fullmatch(cleaned):
        return None
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rest_key() -> str:
    return (
        normalize_secret_value(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        or normalize_secret_value(os.getenv("SUPABASE_KEY"))
        or "local-service-key"
    )


def _rest_headers(*, prefer: str) -> dict[str, str]:
    key = _rest_key()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apikey": key,
        "Prefer": prefer,
    }
    # Local PostgREST has no JWT secret. Authorization → PGRST300.
    if not using_local_database():
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rest_url(path: str) -> str:
    return f"{get_data_base_url().rstrip('/')}/rest/v1/{path.lstrip('/')}"


def _table_missing(response: httpx.Response) -> bool:
    text = (response.text or "").lower()
    return response.status_code in {404, 406} or "pgrst205" in text or "could not find the table" in text


def _rest_error_message(response: httpx.Response, action: str) -> str:
    raw = (response.text or "").strip()
    payload: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        payload = {}
    detail = str(
        payload.get("message")
        or payload.get("hint")
        or payload.get("details")
        or raw
        or response.reason_phrase
    )
    if _table_missing(response):
        return (
            "The harvest API cannot write preview usernames because Docker Postgres "
            "is missing preview_usernames (or PostgREST has not reloaded it). "
            "Start postgres, postgrest, rest-gateway, and api, then retry."
        )
    if "pgrst300" in detail.lower() or "jwt secret" in detail.lower():
        return (
            "Local Postgres rejected a JWT. The harvest API must call PostgREST "
            "without an Authorization header."
        )
    return f"Could not {action} (HTTP {response.status_code}): {detail[:280]}"


def _rest_get(path: str, params: dict[str, str]) -> httpx.Response:
    with httpx.Client(timeout=20.0) as client:
        return client.get(
            _rest_url(path),
            params=params,
            headers=_rest_headers(prefer="count=none"),
        )


def _rest_upsert(path: str, row: dict[str, Any]) -> httpx.Response:
    with httpx.Client(timeout=20.0) as client:
        return client.post(
            _rest_url(path),
            json=row,
            headers=_rest_headers(prefer="resolution=merge-duplicates,return=minimal"),
        )


def _rest_delete(path: str, params: dict[str, str]) -> httpx.Response:
    with httpx.Client(timeout=20.0) as client:
        return client.delete(
            _rest_url(path),
            params=params,
            headers=_rest_headers(prefer="return=minimal"),
        )


def is_demo_username_display(value: str) -> bool:
    """True for allowlisted-style demo names; false for emails and regular users."""
    cleaned = (value or "").strip()
    if not cleaned or "@" in cleaned:
        return False
    return USERNAME_RE.fullmatch(cleaned) is not None


def _fetch_table_rows() -> list[dict[str, Any]] | None:
    """Rows from preview_usernames, or None if the table is unavailable."""
    try:
        response = _rest_get(
            "preview_usernames",
            {
                "select": "username_key,username,active,created_at,created_by,updated_at",
                "order": "created_at.asc",
            },
        )
        if response.status_code >= 400:
            report_error(
                log, "preview_usernames_list_failed", RuntimeError(response.text[:300])
            )
            return None
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        # Missing SUPABASE_URL (CI), connection errors, or non-JSON bodies.
        report_error(log, "preview_usernames_list_failed", exc)
        return None
    return data if isinstance(data, list) else []


def _fetch_config_rows() -> list[dict[str, Any]]:
    try:
        response = _rest_get(
            "app_runtime_config",
            {"select": "value", "key": f"eq.{_CONFIG_KEY}"},
        )
        if response.status_code >= 400:
            return []
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_usernames_config_list_failed", exc)
        return []
    if not isinstance(data, list) or not data:
        return []
    raw = data[0].get("value") if isinstance(data[0], dict) else "[]"
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _save_config_rows(rows: list[dict[str, Any]]) -> None:
    response = _rest_upsert(
        "app_runtime_config?on_conflict=key",
        {"key": _CONFIG_KEY, "value": json.dumps(rows)},
    )
    if response.status_code >= 400:
        raise RuntimeError(_rest_error_message(response, "save preview username"))


def _purged_username_keys() -> set[str]:
    try:
        response = _rest_get(
            "app_runtime_config",
            {"select": "value", "key": f"eq.{_PURGED_CONFIG_KEY}"},
        )
        if response.status_code >= 400:
            return set()
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_usernames_purged_list_failed", exc)
        return set()
    if not isinstance(data, list) or not data:
        return set()
    raw = data[0].get("value") if isinstance(data[0], dict) else "[]"
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, list):
        return set()
    keys: set[str] = set()
    for item in parsed:
        key = str(item or "").strip().lower()
        if key:
            keys.add(key)
    return keys


def _save_purged_username_keys(keys: set[str]) -> None:
    response = _rest_upsert(
        "app_runtime_config?on_conflict=key",
        {"key": _PURGED_CONFIG_KEY, "value": json.dumps(sorted(keys))},
    )
    if response.status_code >= 400:
        raise RuntimeError(_rest_error_message(response, "save purged demo usernames"))


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
    table_rows = _fetch_table_rows()
    if table_rows is not None:
        return table_rows
    return _fetch_config_rows()


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


def aggregate_demo_event_stats(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Roll up per-username counts for the demo-accounts dashboard table."""
    stats: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        # Explicit registered-user rows never count toward demo accounts.
        if event.get("is_preview") is False:
            continue
        display = str(event.get("username") or "").strip()
        if not is_demo_username_display(display):
            continue
        # Missing is_preview (older rows / column fallback) still counts when the
        # username is a demo-style login — do not require is_preview is True.
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


def _load_demo_events_for_stats(*, limit: int = 2000) -> list[dict[str, Any]]:
    """
    Load demo usage rows via the same Supabase/PostgREST client as activity feeds.

    Raw REST aggregation previously dropped every row when the is_preview column
    was absent from the select (fallback path), which zeroed dashboard counts
    while Recent activity / Site usage still worked.
    """
    try:
        from postgrest.exceptions import APIError

        from authenticate import get_db_client, get_service_client
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_username_stats_failed", exc)
        return []

    client = get_service_client() or get_db_client()
    capped = max(1, min(limit, 5000))
    try:
        response = (
            client.table("preview_events")
            .select("username,event_type,created_at,is_preview")
            .eq("is_preview", True)
            .order("created_at", desc=True)
            .limit(capped)
            .execute()
        )
        return list(response.data or [])
    except APIError:
        try:
            response = (
                client.table("preview_events")
                .select("username,event_type,created_at")
                .order("created_at", desc=True)
                .limit(capped)
                .execute()
            )
            rows = response.data or []
            return [
                row
                for row in rows
                if isinstance(row, dict)
                and is_demo_username_display(str(row.get("username") or ""))
            ]
        except APIError as retry_exc:
            report_error(log, "preview_username_stats_failed", retry_exc)
            return []
    except Exception as exc:  # noqa: BLE001
        report_error(log, "preview_username_stats_failed", exc)
        return []


def _event_stats() -> dict[str, dict[str, Any]]:
    return aggregate_demo_event_stats(_load_demo_events_for_stats())


def list_preview_accounts() -> list[dict[str, Any]]:
    """Dashboard + env demo usernames only (never regular signed-in users)."""
    db_rows = {str(row.get("username_key") or "").lower(): row for row in _db_username_rows()}
    env_map = env_username_map()
    stats = _event_stats()
    purged = _purged_username_keys()

    keys: set[str] = set()
    for key in set(db_rows) | set(env_map):
        if key and key not in purged:
            keys.add(key)
    for key, usage in stats.items():
        if not key or key in purged:
            continue
        display = str(usage.get("username") or key)
        if is_demo_username_display(display):
            keys.add(key)
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
            if not is_demo_username_display(display):
                continue
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
    key = display.lower()
    now = _now_iso()
    row = {
        "username_key": key,
        "username": display,
        "active": active,
        "updated_at": now,
    }
    if created_by:
        row["created_by"] = created_by

    table_rows = _fetch_table_rows()
    if table_rows is not None:
        try:
            response = _rest_upsert("preview_usernames?on_conflict=username_key", row)
        except httpx.HTTPError as exc:
            report_error(log, "preview_username_upsert_failed", exc, username=display)
            raise RuntimeError(
                "Harvest API cannot reach local Postgres. Start Docker (postgres/postgrest/api)."
            ) from exc
        if response.status_code < 400:
            return display
        if not _table_missing(response):
            raise RuntimeError(_rest_error_message(response, "save preview username"))

    rows = [item for item in _fetch_config_rows() if isinstance(item, dict)]
    found = False
    for existing in rows:
        if str(existing.get("username_key") or "").lower() == key:
            existing.update(row)
            if "created_at" not in existing:
                existing["created_at"] = now
            found = True
            break
    if not found:
        rows.append({**row, "created_at": now})
    try:
        _save_config_rows(rows)
    except httpx.HTTPError as exc:
        report_error(log, "preview_username_upsert_failed", exc, username=display)
        raise RuntimeError(
            "Harvest API cannot reach local Postgres. Start Docker (postgres/postgrest/api)."
        ) from exc
    return display


def add_preview_username(username: str, *, created_by: str | None) -> str:
    display = upsert_preview_username(username, active=True, created_by=created_by)
    purged = _purged_username_keys()
    key = display.lower()
    if key in purged:
        purged.discard(key)
        _save_purged_username_keys(purged)
    return display


def remove_preview_username(username: str, *, created_by: str | None) -> str:
    display = upsert_preview_username(username, active=False, created_by=created_by)
    _revoke_preview_auth_user(display)
    return display


def _delete_preview_events_for_username(display: str) -> None:
    key = display.lower()
    values = {display, key, preview_email_for(key)}
    for value in values:
        try:
            response = _rest_delete("preview_events", {"username": f"eq.{value}"})
        except Exception as exc:  # noqa: BLE001
            report_error(log, "preview_events_delete_failed", exc, username=value)
            continue
        if response.status_code >= 400 and not _table_missing(response):
            report_error(
                log,
                "preview_events_delete_failed",
                RuntimeError(response.text[:300]),
                username=value,
            )


def permanently_delete_preview_username(username: str) -> str:
    """Remove a demo username, its activity, and Auth user so it no longer appears."""
    display = normalize_username(username)
    if display is None:
        raise ValueError("Usernames must be 2–32 letters, numbers, or underscores.")
    key = display.lower()

    table_rows = _fetch_table_rows()
    if table_rows is not None:
        try:
            response = _rest_delete("preview_usernames", {"username_key": f"eq.{key}"})
        except httpx.HTTPError as exc:
            report_error(log, "preview_username_purge_failed", exc, username=display)
            raise RuntimeError(
                "Harvest API cannot reach local Postgres. Start Docker (postgres/postgrest/api)."
            ) from exc
        if response.status_code >= 400 and not _table_missing(response):
            raise RuntimeError(_rest_error_message(response, "permanently delete demo username"))

    rows = [
        item
        for item in _fetch_config_rows()
        if isinstance(item, dict) and str(item.get("username_key") or "").lower() != key
    ]
    try:
        _save_config_rows(rows)
    except httpx.HTTPError as exc:
        report_error(log, "preview_username_purge_failed", exc, username=display)
        raise RuntimeError(
            "Harvest API cannot reach local Postgres. Start Docker (postgres/postgrest/api)."
        ) from exc

    purged = _purged_username_keys()
    purged.add(key)
    _save_purged_username_keys(purged)
    _delete_preview_events_for_username(display)
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
