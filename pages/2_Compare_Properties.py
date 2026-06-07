"""Compare up to four user-saved properties side by side."""

from knowledge_base import render_auth_page
from property_compare_page import render_property_compare_page

if not render_auth_page():
    import streamlit as st

    st.stop()

render_property_compare_page()
