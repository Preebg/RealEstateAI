"""Streamlit entry point — keeps AIUnderwriterv2.py for Streamlit Cloud."""

from __future__ import annotations

import streamlit as st

from authenticate import render_auth_page
from portfolio_map_page import render_portfolio_map_page
from ui_theme import inject_app_css

st.set_page_config(
    page_title="AI Property Scout",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not render_auth_page():
    st.stop()

inject_app_css()

pg = st.navigation(
    [
        st.Page(render_portfolio_map_page, title="Home", icon="🗺️", default=True),
        st.Page(
            "pages/1_Individual_Search.py",
            title="Individual Search",
            icon="🔍",
        ),
    ]
)
pg.run()
