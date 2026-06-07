"""Streamlit entry point — keeps AIUnderwriterv2.py for Streamlit Cloud."""

from __future__ import annotations

import streamlit as st

from authenticate import render_auth_page
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

pg = st.navigation(
    [
        st.Page("pages/Home.py", title="Home", icon="🗺️", url_path="home", default=True),
        st.Page(
            "pages/1_Individual_Search.py",
            title="Individual Search",
            icon="🔍",
            url_path="individual-search",
        ),
    ]
)
pg.run()
