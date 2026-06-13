"""Streamlit entry point — keeps AIUnderwriterv2.py for Streamlit Cloud."""

from __future__ import annotations

import streamlit as st

import app_nav  # noqa: F401 — keep in sys.modules for Streamlit reruns
import components.property_analysis_display  # noqa: F401 — fragment/widget module registration
import property_nav  # noqa: F401

from authenticate import render_auth_page
from app_nav import INDIVIDUAL_SEARCH_PAGE, MAP_OPEN_ADDRESS_KEY, consume_nav_target
from legal import APP_NAME, render_legal_page, requested_legal_path
from ui_theme import inject_app_css, render_app_footer_glossary


def _render_model_validation_page() -> None:
    from validation.backtest import render_backtest_page

    render_backtest_page()

st.set_page_config(
    page_title=APP_NAME,
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_app_css()

legal_path = requested_legal_path()
if legal_path:
    render_legal_page(legal_path)
    render_app_footer_glossary()
    st.stop()

authenticated = render_auth_page()

if authenticated:
    from viewer_timezone import ensure_viewer_timezone

    ensure_viewer_timezone()

open_individual_search = consume_nav_target() == INDIVIDUAL_SEARCH_PAGE

if authenticated and not st.session_state.get("_guest_landing_routed"):
    from share_access import consume_guest_landing_address, is_guest_viewer

    if is_guest_viewer():
        landing = consume_guest_landing_address()
    else:
        landing = None
    if landing:
        st.session_state[MAP_OPEN_ADDRESS_KEY] = landing
        st.session_state["_guest_landing_routed"] = True
        open_individual_search = True

nav_pages = [
    st.Page(
        "pages/Home.py",
        title="Home",
        icon=":material/map:",
        url_path="home",
        default=not open_individual_search,
    ),
    st.Page(
        "pages/1_Individual_Search.py",
        title="Individual Search",
        icon=":material/search:",
        url_path="individual-search",
        default=open_individual_search,
    ),
    st.Page(
        "pages/2_Compare_Properties.py",
        title="Compare",
        icon=":material/compare:",
        url_path="compare",
    ),
    st.Page(
        _render_model_validation_page,
        title="Model Validation",
        icon=":material/analytics:",
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

if authenticated:
    from services.deferred_analysis import render_background_deferred_worker

    render_background_deferred_worker()

render_app_footer_glossary()
