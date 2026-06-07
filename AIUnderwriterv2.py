"""Streamlit entry point — keeps AIUnderwriterv2.py for Streamlit Cloud."""

from __future__ import annotations

import streamlit as st

from authenticate import render_auth_page
from share_access import consume_guest_landing_address, is_guest_viewer
from ui_theme import inject_app_css

st.set_page_config(
    page_title="AI Property Scout",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_app_css()

if not render_auth_page():
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

if is_guest_viewer():
    if not st.session_state.get("_guest_landing_routed"):
        landing = consume_guest_landing_address()
        if landing:
            st.session_state["map_open_address"] = landing
            st.session_state["_guest_landing_routed"] = True
            st.switch_page("pages/1_Individual_Search.py")

nav_pages = [
    st.Page("pages/Home.py", title="Home", icon="🗺️", url_path="home", default=True),
    st.Page(
        "pages/1_Individual_Search.py",
        title="Individual Search",
        icon="🔍",
        url_path="individual-search",
    ),
]

pg = st.navigation(nav_pages)
pg.run()
