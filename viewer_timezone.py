"""Browser timezone detection and local-time formatting for catalog timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Underscore prefix avoids Streamlit session-state collisions with module names.
VIEWER_TIMEZONE_SESSION_KEY = "_viewer_timezone"
VIEWER_TIMEZONE_QUERY_PARAM = "tz"
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
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_12h_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def format_added_at(
    utc_dt: datetime,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> str:
    """Format a catalog timestamp for display in the user's local timezone."""
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


def _clear_query_param(name: str) -> None:
    try:
        import streamlit as st
    except ImportError:
        return
    if name in st.query_params:
        del st.query_params[name]


def get_user_zoneinfo() -> ZoneInfo:
    """Return the user's timezone from Streamlit session state, or UTC."""
    try:
        import streamlit as st
    except ImportError:
        return ZoneInfo(DEFAULT_TIMEZONE)

    stored = st.session_state.get(VIEWER_TIMEZONE_SESSION_KEY)
    if stored:
        return ZoneInfo(validate_timezone_name(str(stored)))
    return ZoneInfo(DEFAULT_TIMEZONE)


def viewer_timezone_is_resolved() -> bool:
    """True once the browser timezone has been stored in session state."""
    try:
        import streamlit as st
    except ImportError:
        return False
    return bool(st.session_state.get(VIEWER_TIMEZONE_SESSION_KEY))


def ensure_viewer_timezone() -> ZoneInfo:
    """
    Resolve the viewer's IANA timezone once per session.

    On first load, injects a small script that sets a ``tz`` query param from
    ``Intl.DateTimeFormat``; the next rerun stores it in session state.
    """
    try:
        import streamlit as st
        import streamlit.components.v1 as components
    except ImportError:
        return ZoneInfo(DEFAULT_TIMEZONE)

    stored = st.session_state.get(VIEWER_TIMEZONE_SESSION_KEY)
    if stored:
        return ZoneInfo(validate_timezone_name(str(stored)))

    query_tz = st.query_params.get(VIEWER_TIMEZONE_QUERY_PARAM)
    if query_tz:
        tz_name = validate_timezone_name(query_tz)
        st.session_state[VIEWER_TIMEZONE_SESSION_KEY] = tz_name
        _clear_query_param(VIEWER_TIMEZONE_QUERY_PARAM)
        return ZoneInfo(tz_name)

    components.html(
        f"""
        <script>
        (function() {{
            const param = {VIEWER_TIMEZONE_QUERY_PARAM!r};
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const url = new URL(window.parent.location.href);
            if (url.searchParams.get(param) !== tz) {{
                url.searchParams.set(param, tz);
                window.parent.location.replace(url.toString());
            }}
        }})();
        </script>
        """,
        height=0,
    )
    return ZoneInfo(DEFAULT_TIMEZONE)
