"""Viewer timezone detection and UTC catalog timestamp formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    Build a fixed offset from browser ``timezone_offset`` minutes.

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
    """Resolve viewer tz from browser context, optional cookie, then UTC."""
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
    """Return UTC when no browser context is available (headless / API)."""
    return ZoneInfo(DEFAULT_TIMEZONE)


def viewer_timezone_is_local() -> bool:
    """True when the browser provided a non-UTC timezone (always False headless)."""
    return False


def ensure_viewer_timezone() -> tzinfo:
    """Return the active viewer timezone (UTC in headless mode)."""
    return get_viewer_timezone()
