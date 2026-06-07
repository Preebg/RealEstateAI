"""Streamlit UI for hot-market pulse across discovery metros."""

from __future__ import annotations

import streamlit as st

from engine import HOT_MARKETS
from knowledge_base import get_market_pulse

_MARKET_LABELS = {name: scope.split("(")[0].strip() for name, scope, _ in HOT_MARKETS}


def render_market_pulse() -> None:
    """Display per-metro hot-market stats."""
    st.subheader("📡 Hot Market Pulse")
    pulse = get_market_pulse()
    priority, expansion = HOT_MARKETS[:2], HOT_MARKETS[2:]

    st.caption("Priority: Upstate NY • Expansion: Southeast, Ohio, Texas")
    cols = st.columns(2)
    for col, (name, _, _) in zip(cols, priority):
        stats = pulse[name]
        with col:
            st.markdown(f"**{_MARKET_LABELS.get(name, name)}**")
            st.metric("Properties Tracked", stats["count"])
            st.metric("Avg List Price", f"${stats['avg_price']:,.0f}")
            st.metric("Avg Quantum Score", f"{stats['avg_quantum']:.1f}%")
            st.caption(f"Top strategy: {stats['top_label']}")

    with st.expander("Expansion markets"):
        exp_cols = st.columns(3)
        for idx, (name, _, _) in enumerate(expansion):
            stats = pulse[name]
            with exp_cols[idx % 3]:
                st.markdown(f"**{_MARKET_LABELS.get(name, name)}**")
                st.metric("Tracked", stats["count"])
                st.metric("Avg Price", f"${stats['avg_price']:,.0f}")
                st.caption(f"Quantum: {stats['avg_quantum']:.1f}%")
