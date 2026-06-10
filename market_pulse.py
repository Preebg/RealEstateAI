"""Streamlit UI for hot-market pulse across discovery metros."""

from __future__ import annotations

import streamlit as st

from knowledge_base import get_market_pulse

MARKET_DISPLAY_NAMES: dict[str, str] = {
    "Rochester": "Rochester, NY",
    "Syracuse": "Syracuse, NY",
    "Buffalo": "Buffalo, NY",
    "Albany": "Albany, NY",
    "Philadelphia": "Philadelphia, PA",
    "Pittsburgh": "Pittsburgh, PA",
    "Orlando": "Orlando, FL",
    "Tampa": "Tampa, FL",
    "Miami": "Miami–Fort Lauderdale",
    "Charlotte": "Charlotte, NC",
    "Raleigh": "Raleigh, NC",
    "Charleston": "Charleston, SC",
}


def _render_market_card(name: str, stats: dict[str, float | int | str]) -> None:
    label = MARKET_DISPLAY_NAMES.get(name, name)
    count = int(stats["count"])
    st.markdown(f'<div class="pulse-market-title">{label}</div>', unsafe_allow_html=True)
    if count == 0:
        st.caption("No properties yet")
        return
    st.metric("Tracked", count)
    st.caption(
        f"Avg ${stats['avg_price']:,.0f} · "
        f"alignment {stats['avg_quantum']:.0f}% · {stats['top_label']}"
    )


def render_market_pulse() -> None:
    """Display per-metro hot-market stats in a collapsed sidebar expander."""
    with st.expander("📡 Market pulse", expanded=False):
        pulse = get_market_pulse()

        upstate = ("Rochester", "Syracuse", "Buffalo", "Albany")
        upstate_cols = st.columns(2)
        for idx, city in enumerate(upstate):
            with upstate_cols[idx % 2]:
                _render_market_card(city, pulse[city])

        st.markdown('<div class="pulse-market-sub">Other markets</div>', unsafe_allow_html=True)
        other = [name for name in MARKET_DISPLAY_NAMES if name not in upstate]
        other_cols = st.columns(3)
        for idx, name in enumerate(other):
            with other_cols[idx % 3]:
                _render_market_card(name, pulse[name])
