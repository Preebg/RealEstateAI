"""Shared HTML helpers for portal detail pages."""

from __future__ import annotations

import json
import re
from typing import Any

_STATUS_MAP = {
    "active": "For Sale",
    "for sale": "For Sale",
    "for_sale": "For Sale",
    "pending": "Pending",
    "contingent": "Contingent",
    "sold": "Sold",
    "off market": "Off Market",
    "coming soon": "Coming Soon",
}


def extract_next_data_json(html: str) -> dict[str, Any] | None:
    """Parse embedded Next.js payload from a portal detail page."""
    text = str(html or "")
    if not text.strip():
        return None

    match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(?P<body>.*?)</script>',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        payload = json.loads(match.group("body"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_listing_status(raw: str) -> str:
    """Map portal status strings to harvester listing_status values."""
    cleaned = str(raw or "").strip()
    if not cleaned:
        return "For Sale"
    mapped = _STATUS_MAP.get(cleaned.lower())
    return mapped or cleaned


def coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def coerce_float(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
