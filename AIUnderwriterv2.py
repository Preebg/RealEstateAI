"""Streamlit entry point — keeps AIUnderwriterv2.py for Streamlit Cloud."""

from __future__ import annotations

import streamlit as st

from authenticate import render_auth_page
from app_nav import INDIVIDUAL_SEARCH_PAGE, MAP_OPEN_ADDRESS_KEY, consume_nav_target
from share_access import consume_guest_landing_address, is_guest_viewer
import importlib
import ui_theme

if not hasattr(ui_theme, "render_app_footer_glossary"):
    importlib.reload(ui_theme)

from ui_theme import inject_app_css

if hasattr(ui_theme, "render_app_footer_glossary"):
    render_app_footer_glossary = ui_theme.render_app_footer_glossary
else:
    def render_app_footer_glossary() -> None:
        st.markdown(
            '<p class="app-footer-glossary">'
            "<strong>Quantum Alignment Score</strong> measures how well the QAOA optimizer "
            "matches your investment targets (0–100%); "
            "<strong>Hybrid Optimization Score</strong> compares classical and QAOA on the "
            "same objective. Neither is financial risk or a market prediction."
            "</p>",
            unsafe_allow_html=True,
        )

st.set_page_config(
    page_title="AI Property Scout",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_app_css()

authenticated = render_auth_page()

open_individual_search = consume_nav_target() == INDIVIDUAL_SEARCH_PAGE

if authenticated and is_guest_viewer() and not st.session_state.get("_guest_landing_routed"):
    landing = consume_guest_landing_address()
    if landing:
        st.session_state[MAP_OPEN_ADDRESS_KEY] = landing
        st.session_state["_guest_landing_routed"] = True
        open_individual_search = True

nav_pages = [
    st.Page(
        "pages/Home.py",
        title="Home",
        icon="🗺️",
        url_path="home",
        default=not open_individual_search,
    ),
    st.Page(
        "pages/1_Individual_Search.py",
        title="Individual Search",
        icon="🔍",
        url_path="individual-search",
        default=open_individual_search,
    ),
    st.Page(
        "pages/2_Compare_Properties.py",
        title="Compare",
        icon="⚖️",
        url_path="compare",
    ),
    st.Page(
        "pages/3_Model_Validation.py",
        title="Model Validation",
        icon="📊",
        url_path="model-validation",
    ),
]

if not authenticated:
    # Register v2 navigation (overrides default "AIUnderwriterv2" sidebar label)
    # without showing page links on the login screen.
    st.navigation(nav_pages, position="hidden")
    render_app_footer_glossary()
    st.stop()

pg = st.navigation(nav_pages)
pg.run()
render_app_footer_glossary()
