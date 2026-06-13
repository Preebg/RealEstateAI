"""Browser timezone detection and local-time formatting for catalog timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Underscore prefix avoids Streamlit session-state collisions with module names.
VIEWER_TIMEZONE_SESSION_KEY = "_viewer_timezone"
VIEWER_TIMEZONE_OFFSET_KEY = "_viewer_tz_offset_min"
VIEWER_TIMEZONE_QUERY_PARAM = "tz"
VIEWER_TIMEZONE_OFFSET_QUERY_PARAM = "tz_offset"
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
    Build a fixed offset tzinfo from JavaScript ``getTimezoneOffset()`` minutes.

    JS returns (UTC - local) in minutes, so Eastern (UTC-4) is 240.
    """
    return timezone(timedelta(minutes=-int(offset_minutes)))


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


def _clear_query_param(name: str) -> None:
    try:
        import streamlit as st
    except ImportError:
        return
    if name in st.query_params:
        del st.query_params[name]


def _query_param_value(name: str) -> str | None:
    try:
        import streamlit as st
    except ImportError:
        return None
    value = st.query_params.get(name)
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)


def _store_viewer_timezone_from_query() -> tzinfo | None:
    try:
        import streamlit as st
    except ImportError:
        return None

    query_tz = _query_param_value(VIEWER_TIMEZONE_QUERY_PARAM)
    if query_tz:
        tz_name = validate_timezone_name(query_tz)
        st.session_state[VIEWER_TIMEZONE_SESSION_KEY] = tz_name
        _clear_query_param(VIEWER_TIMEZONE_QUERY_PARAM)
        return ZoneInfo(tz_name)

    offset_raw = _query_param_value(VIEWER_TIMEZONE_OFFSET_QUERY_PARAM)
    if offset_raw:
        try:
            offset_minutes = int(offset_raw)
        except ValueError:
            offset_minutes = None
        if offset_minutes is not None:
            st.session_state[VIEWER_TIMEZONE_OFFSET_KEY] = offset_minutes
            _clear_query_param(VIEWER_TIMEZONE_OFFSET_QUERY_PARAM)
            return timezone_from_offset_minutes(offset_minutes)
    return None


def get_viewer_timezone() -> tzinfo:
    """Return the viewer timezone from session state, or UTC."""
    try:
        import streamlit as st
    except ImportError:
        return ZoneInfo(DEFAULT_TIMEZONE)

    stored = st.session_state.get(VIEWER_TIMEZONE_SESSION_KEY)
    if stored:
        return ZoneInfo(validate_timezone_name(str(stored)))

    offset_minutes = st.session_state.get(VIEWER_TIMEZONE_OFFSET_KEY)
    if offset_minutes is not None:
        try:
            return timezone_from_offset_minutes(int(offset_minutes))
        except (TypeError, ValueError):
            pass
    return ZoneInfo(DEFAULT_TIMEZONE)


def viewer_timezone_is_local() -> bool:
    """True when a browser-provided timezone is stored (not the UTC fallback)."""
    try:
        import streamlit as st
    except ImportError:
        return False
    return bool(
        st.session_state.get(VIEWER_TIMEZONE_SESSION_KEY)
        or st.session_state.get(VIEWER_TIMEZONE_OFFSET_KEY) is not None
    )


def ensure_viewer_timezone() -> tzinfo:
    """
    Resolve the viewer's timezone once per session.

    On first load, injects a small script that sets ``tz`` / ``tz_offset`` query
    params from the browser; the next rerun stores them in session state.
    """
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return ZoneInfo(DEFAULT_TIMEZONE)

    stored_tz = get_viewer_timezone()
    if viewer_timezone_is_local():
        return stored_tz

    detected = _store_viewer_timezone_from_query()
    if detected is not None:
        return detected

    components.html(
        f"""
        <script>
        (function() {{
            const tzParam = {VIEWER_TIMEZONE_QUERY_PARAM!r};
            const offsetParam = {VIEWER_TIMEZONE_OFFSET_QUERY_PARAM!r};
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const offset = String(new Date().getTimezoneOffset());
            const targets = [window.top, window.parent, window];
            let targetWindow = window;
            for (const candidate of targets) {{
                try {{
                    if (candidate && candidate.location) {{
                        targetWindow = candidate;
                        break;
                    }}
                }} catch (err) {{
                    /* cross-origin frame */
                }}
            }}
            const url = new URL(targetWindow.location.href);
            let changed = false;
            if (url.searchParams.get(tzParam) !== tz) {{
                url.searchParams.set(tzParam, tz);
                changed = true;
            }}
            if (url.searchParams.get(offsetParam) !== offset) {{
                url.searchParams.set(offsetParam, offset);
                changed = true;
            }}
            if (changed) {{
                targetWindow.location.replace(url.toString());
            }}
        }})();
        </script>
        """,
        height=0,
    )
    return ZoneInfo(DEFAULT_TIMEZONE)
