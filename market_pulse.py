"""Streamlit UI for Rochester vs Syracuse market pulse."""

from __future__ import annotations

import streamlit as st

from knowledge_base import get_market_pulse


def render_market_pulse() -> None:
    """Display Rochester vs Syracuse hot-market stats in the sidebar."""
    st.subheader("📡 Hot Market Pulse")
    pulse = get_market_pulse()
    col_r, col_s = st.columns(2)

    for col, city in ((col_r, "Rochester"), (col_s, "Syracuse")):
        stats = pulse[city]
        with col:
            st.markdown(f"**{city}, NY**")
            st.metric("Properties Tracked", stats["count"])
            st.metric("Avg List Price", f"${stats['avg_price']:,.0f}")
            st.metric("Avg Quantum Score", f"{stats['avg_quantum']:.1f}%")
            st.caption(f"Top strategy: {stats['top_label']}")
