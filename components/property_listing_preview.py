"""Listing preview image and metadata chips for property detail views."""

from __future__ import annotations

from typing import Any

import streamlit as st

from security_utils import escape_html


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_listing_metadata_chips(
    *,
    listing_status: str | None = None,
    days_on_market: int | None = None,
    view_count: int | None = None,
) -> list[str]:
    """Return human-readable chip labels for listing metadata."""
    chips: list[str] = []
    status = str(listing_status or "").strip()
    if status:
        chips.append(status)

    days = _coerce_optional_int(days_on_market)
    if days is not None:
        label = "day" if days == 1 else "days"
        chips.append(f"{days} {label} on market")

    views = _coerce_optional_int(view_count)
    if views is not None:
        label = "view" if views == 1 else "views"
        chips.append(f"{views} {label}")

    return chips


def render_listing_metadata_chips_html(
    *,
    listing_status: str | None = None,
    days_on_market: int | None = None,
    view_count: int | None = None,
) -> str:
    """Return escaped HTML for listing metadata chips (e.g. folium popups)."""
    chips = build_listing_metadata_chips(
        listing_status=listing_status,
        days_on_market=days_on_market,
        view_count=view_count,
    )
    if not chips:
        return ""

    chip_spans = "".join(
        f'<span class="listing-chip">{escape_html(chip)}</span>'
        for chip in chips
    )
    return f'<div class="listing-chip-row">{chip_spans}</div>'


def render_property_listing_preview(
    *,
    address: str,
    primary_image_url: str | None = None,
    listing_status: str | None = None,
    days_on_market: int | None = None,
    view_count: int | None = None,
) -> None:
    """
    Render a CDN listing image and metadata chips.

    Uses CDN URLs directly — no server-side image download (Streamlit Cloud safe).
    """
    hero_image = str(primary_image_url or "").strip()
    if hero_image:
        st.image(hero_image, caption=address, use_container_width=True)

    chips = build_listing_metadata_chips(
        listing_status=listing_status,
        days_on_market=days_on_market,
        view_count=view_count,
    )
    if chips:
        st.pills(
            "Listing details",
            chips,
            disabled=True,
            label_visibility="collapsed",
        )
