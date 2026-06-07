"""Lightweight cross-page navigation (no engine / knowledge_base imports)."""

from __future__ import annotations

import streamlit as st

MAP_OPEN_ADDRESS_KEY = "map_open_address"
NAV_TARGET_KEY = "_nav_target_page"
INDIVIDUAL_SEARCH_PAGE = "individual-search"
INDIVIDUAL_SEARCH_SCRIPT = "pages/1_Individual_Search.py"


def queue_property_for_main_tab(address: str) -> None:
    """Stash an address for Individual Search to load on next render."""
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
    Open Individual Search immediately.

    st.Page(default=True) only applies on cold load; st.switch_page is required
    when the user is already on another registered page (e.g. Home / Compare).
    """
    if address and str(address).strip():
        queue_property_for_main_tab(address)
    st.session_state[NAV_TARGET_KEY] = INDIVIDUAL_SEARCH_PAGE
    st.switch_page(INDIVIDUAL_SEARCH_SCRIPT)


def consume_nav_target() -> str | None:
    """Return and clear a pending navigation target, if any."""
    target = st.session_state.pop(NAV_TARGET_KEY, None)
    if target and str(target).strip():
        return str(target).strip()
    return None
