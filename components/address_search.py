"""Knowledge-base address autocomplete for Individual Search."""

from __future__ import annotations

import streamlit as st


def _coerce_address_input_state(key: str) -> None:
    """Multiselect stores a list; legacy map handoff may set a plain string."""
    raw = st.session_state.get(key)
    if isinstance(raw, str):
        value = raw.strip()
        st.session_state[key] = [value] if value else []


def _address_from_widget_state(key: str) -> str:
    raw = st.session_state.get(key)
    if isinstance(raw, list):
        return str(raw[0]).strip() if raw else ""
    if isinstance(raw, str):
        return raw.strip()
    return ""


def render_property_address_input(
    *,
    disabled: bool = False,
    key: str = "address_input",
) -> str:
    """Type-to-filter KB addresses; accept new addresses not yet in the database."""
    from knowledge_base import get_kb_address_options

    _coerce_address_input_state(key)

    st.multiselect(
        label="Property Address",
        options=get_kb_address_options(),
        max_selections=1,
        accept_new_options=True,
        placeholder="Start typing to search the database (e.g. 28 Grant Ave)…",
        key=key,
        disabled=disabled,
        help=(
            "Matches filter as you type against scanned properties. "
            "Pick a suggestion or enter any new address to analyze."
        ),
    )
    return _address_from_widget_state(key)
