"""Shared Streamlit styling for the web app."""

from __future__ import annotations

import streamlit as st


def inject_app_css() -> None:
    """Apply lightweight global polish (metrics, sidebar pulse, section headers)."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] [data-testid="stMetric"] {
            background: linear-gradient(145deg, #ffffff 0%, #f4f7fb 100%);
            border: 1px solid #e3e8ef;
            border-radius: 10px;
            padding: 0.35rem 0.5rem;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e8ecf1;
            border-radius: 10px;
            padding: 0.4rem 0.55rem;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        .app-hero {
            margin-bottom: 0.25rem;
        }
        .app-hero h1 {
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 0.15rem;
        }
        .app-hero p {
            color: #5f6b7a;
            margin-top: 0;
        }
        .pulse-market-title {
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 0.15rem;
            color: #1f2937;
        }
        .pulse-market-sub {
            color: #6b7280;
            font-size: 0.78rem;
            margin-top: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title: str, subtitle: str) -> None:
    """Consistent page header."""
    st.markdown(
        f'<div class="app-hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )
