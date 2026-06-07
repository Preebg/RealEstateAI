"""Cross-page property selection (portfolio map → main analyzer)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from engine import get_final_analysis
from knowledge_base import lookup_property

MAP_OPEN_ADDRESS_KEY = "map_open_address"


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


def load_property_from_kb(address: str) -> dict[str, Any] | None:
    """Hydrate a KB property with forecast fields for the main analyzer UI."""
    cached = lookup_property(address)
    if not cached:
        return None
    return get_final_analysis(cached, address, None)
