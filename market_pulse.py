"""Streamlit UI for hot-market pulse across discovery metros."""

from __future__ import annotations

import streamlit as st

from knowledge_base import get_market_pulse

MARKET_DISPLAY_NAMES: dict[str, str] = {
    "Rochester": "Rochester, NY",
    "Syracuse": "Syracuse, NY",
    "Charlotte": "Charlotte, NC",
    "Raleigh": "Raleigh, NC",
    "Charleston": "Charleston, SC",
    "Ohio": "Ohio",
    "DFW": "Dallas–Fort Worth",
    "Austin": "Austin, TX",
}


def _render_market_card(name: str, stats: dict[str, float | int | str]) -> None:
    label = MARKET_DISPLAY_NAMES.get(name, name)
    count = int(stats["count"])
    st.markdown(f'<div class="pulse-market-title">{label}</div>', unsafe_allow_html=True)
    if count == 0:
        st.caption("No properties yet")
        return
    st.metric("Tracked", count)
    st.metric("Avg price", f"${stats['avg_price']:,.0f}")
    st.caption(f"Avg alignment {stats['avg_quantum']:.1f}% · {stats['top_label']}")


def render_market_pulse() -> None:
    """Display per-metro hot-market stats in the sidebar."""
    st.markdown("##### 📡 Hot Market Pulse")
    pulse = get_market_pulse()

    upstate = ("Rochester", "Syracuse")
    col_r, col_s = st.columns(2)
    for col, city in ((col_r, upstate[0]), (col_s, upstate[1])):
        with col:
            _render_market_card(city, pulse[city])

    st.markdown('<div class="pulse-market-sub">Other active markets</div>', unsafe_allow_html=True)
    other = [name for name in MARKET_DISPLAY_NAMES if name not in upstate]
    other_cols = st.columns(3)
    for idx, name in enumerate(other):
        with other_cols[idx % 3]:
            _render_market_card(name, pulse[name])
