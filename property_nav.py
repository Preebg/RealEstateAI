"""Cross-page property selection (portfolio map → main analyzer)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from engine import get_final_analysis
from knowledge_base import lookup_property

MAP_OPEN_ADDRESS_KEY = "map_open_address"
NAV_TARGET_KEY = "_nav_target_page"
INDIVIDUAL_SEARCH_PAGE = "individual-search"


def queue_property_for_main_tab(address: str) -> None:
    """Stash an address for the main analyzer page to load on next render."""
    cleaned = str(address or "").strip()
    if cleaned:
        st.session_state[MAP_OPEN_ADDRESS_KEY] = cleaned


def consume_map_property_selection() -> str | None:
    """Return and clear a map-queued address, if any."""
    address = st.session_state.pop(MAP_OPEN_ADDRESS_KEY, None)
    if address and str(address).strip():
        return str(address).strip()
    return None


def navigate_to_individual_search(address: str | None = None) -> None:
    """
    Open Individual Search on the next app rerun.

    Uses st.navigation default-page selection instead of st.switch_page, which
    is unreliable when pages are registered only via st.Page().
    """
    if address and str(address).strip():
        queue_property_for_main_tab(address)
    st.session_state[NAV_TARGET_KEY] = INDIVIDUAL_SEARCH_PAGE
    st.rerun()


def consume_nav_target() -> str | None:
    """Return and clear a pending navigation target, if any."""
    target = st.session_state.pop(NAV_TARGET_KEY, None)
    if target and str(target).strip():
        return str(target).strip()
    return None


def load_property_from_kb(address: str) -> dict[str, Any] | None:
    """Hydrate a KB property with forecast fields for the main analyzer UI."""
    cached = lookup_property(address)
    if not cached:
        return None
    return get_final_analysis(cached, address, None)
