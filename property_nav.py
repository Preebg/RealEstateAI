"""Property handoff helpers (portfolio map → Individual Search)."""

from __future__ import annotations

from typing import Any

from app_nav import (
    INDIVIDUAL_SEARCH_PAGE,
    MAP_OPEN_ADDRESS_KEY,
    NAV_TARGET_KEY,
    consume_map_property_selection,
    consume_nav_target,
    navigate_to_individual_search,
    queue_property_for_main_tab,
)

__all__ = [
    "INDIVIDUAL_SEARCH_PAGE",
    "MAP_OPEN_ADDRESS_KEY",
    "NAV_TARGET_KEY",
    "consume_map_property_selection",
    "consume_nav_target",
    "load_property_from_kb",
    "navigate_to_individual_search",
    "queue_property_for_main_tab",
]


def load_property_from_kb(address: str) -> dict[str, Any] | None:
    """Hydrate a KB property with forecast fields for the main analyzer UI."""
    from engine import get_final_analysis
    from knowledge_base import lookup_property

    cached = lookup_property(address)
    if not cached:
        return None
    return get_final_analysis(cached, address, None)
