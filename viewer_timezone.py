"""Viewer timezone detection and UTC catalog timestamp formatting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Essential cookie — stores IANA timezone for session continuity (no tracking).
VIEWER_TIMEZONE_COOKIE_NAME = "q_scout_essential_tz"
VIEWER_TIMEZONE_COOKIE_SYNCED_KEY = "_viewer_tz_cookie_synced"
DEFAULT_TIMEZONE = "UTC"


def validate_timezone_name(name: str | None) -> str:
    """Return a valid IANA timezone name, falling back to UTC."""
    candidate = str(name or "").strip()
    if not candidate:
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE
    return candidate


def parse_property_timestamp(value: Any) -> datetime | None:
    """Parse a Supabase ``properties.timestamp`` value into UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def timezone_from_offset_minutes(offset_minutes: int) -> tzinfo:
    """
    Build a fixed offset from Streamlit/JS ``timezone_offset`` minutes.

    Positive values mean the local zone is behind UTC (US Eastern ≈ 240).
    """
    return timezone(-timedelta(minutes=int(offset_minutes)))


def _format_12h_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def format_added_at(
    utc_dt: datetime,
    tz: tzinfo,
    *,
    now: datetime | None = None,
) -> str:
    """Format a catalog timestamp for display in the viewer's local timezone."""
    if hasattr(utc_dt, "to_pydatetime"):
        utc_dt = utc_dt.to_pydatetime()
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    local = utc_dt.astimezone(tz)
    reference = now.astimezone(tz) if now is not None else datetime.now(tz)
    time_str = _format_12h_time(local)

    if local.date() == reference.date():
        return time_str
    if local.date() == (reference - timedelta(days=1)).date():
        return f"Yesterday, {time_str}"
    if local.year == reference.year:
        return f"{local.strftime('%b')} {local.day}, {time_str}"
    return f"{local.strftime('%b')} {local.day}, {local.year}, {time_str}"


def resolve_viewer_timezone(
    *,
    context_tz: str | None = None,
    context_offset: int | None = None,
    cookie_tz: str | None = None,
) -> tzinfo:
    """Resolve viewer tz from browser context, essential cookie, then UTC."""
    if context_tz:
        return ZoneInfo(validate_timezone_name(context_tz))

    if cookie_tz:
        return ZoneInfo(validate_timezone_name(cookie_tz))

    if context_offset is not None:
        try:
            return timezone_from_offset_minutes(int(context_offset))
        except (TypeError, ValueError):
            pass

    return ZoneInfo(DEFAULT_TIMEZONE)


def get_viewer_timezone() -> tzinfo:
    """
    Return the viewer's timezone.

    Uses Streamlit 1.36+ ``st.context.timezone`` (sent by the browser each run),
    then the essential timezone cookie, then ``st.context.timezone_offset``.
    """
    try:
        import streamlit as st
    except ImportError:
        return ZoneInfo(DEFAULT_TIMEZONE)

    cookie_tz: str | None = None
    try:
        cookies = st.context.cookies
        if VIEWER_TIMEZONE_COOKIE_NAME in cookies:
            cookie_tz = str(cookies[VIEWER_TIMEZONE_COOKIE_NAME])
    except (AttributeError, KeyError, TypeError, ValueError):
        cookie_tz = None

    context_tz = getattr(st.context, "timezone", None)
    context_offset = getattr(st.context, "timezone_offset", None)

    return resolve_viewer_timezone(
        context_tz=str(context_tz) if context_tz else None,
        context_offset=context_offset,
        cookie_tz=cookie_tz,
    )


def viewer_timezone_is_local() -> bool:
    """True when the browser provided a non-UTC timezone."""
    try:
        import streamlit as st
    except ImportError:
        return False

    context_tz = getattr(st.context, "timezone", None)
    if context_tz and validate_timezone_name(str(context_tz)) != DEFAULT_TIMEZONE:
        return True

    try:
        cookies = st.context.cookies
        if VIEWER_TIMEZONE_COOKIE_NAME in cookies:
            return validate_timezone_name(cookies[VIEWER_TIMEZONE_COOKIE_NAME]) != DEFAULT_TIMEZONE
    except (AttributeError, KeyError, TypeError, ValueError):
        pass

    return getattr(st.context, "timezone_offset", None) is not None


def sync_essential_timezone_cookie() -> None:
    """
    Persist the browser IANA timezone in an essential cookie (one script per session).

    The cookie lets later requests recover timezone if context is briefly unavailable.
    """
    try:
        import streamlit as st
        import streamlit.components.v1 as components
    except ImportError:
        return

    if st.session_state.get(VIEWER_TIMEZONE_COOKIE_SYNCED_KEY):
        return

    context_tz = getattr(st.context, "timezone", None)
    cookie_name = VIEWER_TIMEZONE_COOKIE_NAME
    components.html(
        f"""
        <script>
        (function() {{
            const cookieName = {json.dumps(cookie_name)};
            const contextTz = {json.dumps(str(context_tz) if context_tz else "")};
            const tz = contextTz || Intl.DateTimeFormat().resolvedOptions().timeZone;
            if (!tz) {{
                return;
            }}
            const targetDoc = window.parent?.document || document;
            const secure = (window.parent?.location?.protocol || location.protocol) === "https:"
                ? "; Secure" : "";
            targetDoc.cookie = `${{cookieName}}=${{encodeURIComponent(tz)}}`
                + "; path=/; max-age=31536000; SameSite=Lax" + secure;
        }})();
        </script>
        """,
        height=0,
    )
    st.session_state[VIEWER_TIMEZONE_COOKIE_SYNCED_KEY] = True


def ensure_viewer_timezone() -> tzinfo:
    """Load viewer timezone and sync the essential cookie."""
    sync_essential_timezone_cookie()
    return get_viewer_timezone()
