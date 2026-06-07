"""Shared Streamlit styling for the web app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    import matplotlib.axes
    import matplotlib.figure


def _active_theme_base() -> str:
    """Return ``light`` or ``dark`` for the viewer's active Streamlit theme."""
    theme = getattr(st.context, "theme", None)
    if theme is not None:
        base = theme.get("base") or theme.get("type")
        if base in {"light", "dark"}:
            return base
    return "light"


def inject_app_css() -> None:
    """Apply lightweight global polish (metrics, sidebar pulse, section headers)."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] [data-testid="stMetric"],
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"] {
            background: var(--secondary-background-color);
            border: 1px solid var(--border-color, rgba(128, 128, 128, 0.28));
            border-radius: 10px;
            padding: 0.4rem 0.55rem;
            box-shadow: none;
        }
        [data-testid="stSidebar"] [data-testid="stMetric"] {
            padding: 0.35rem 0.5rem;
        }
        .app-hero {
            margin-bottom: 0.25rem;
        }
        .app-hero h1 {
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 0.15rem;
            color: var(--text-color);
        }
        .app-hero p {
            color: var(--text-color);
            opacity: 0.72;
            margin-top: 0;
        }
        .pulse-market-title {
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 0.15rem;
            color: var(--text-color);
        }
        .pulse-market-sub {
            color: var(--text-color);
            opacity: 0.68;
            font-size: 0.78rem;
            margin-top: 0.35rem;
        }
        .auth-agreement-text {
            margin: 0;
            padding-top: 0.42rem;
            line-height: 1.2;
            color: var(--text-color);
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


def style_matplotlib_chart(
    fig: matplotlib.figure.Figure,
    ax: matplotlib.axes.Axes,
) -> None:
    """Match matplotlib output to the active Streamlit light/dark theme."""
    if _active_theme_base() == "dark":
        bg = "#0e1117"
        fg = "#fafafa"
        grid = "#3a3f4b"
    else:
        bg = "#ffffff"
        fg = "#262730"
        grid = "#d5d8dc"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=fg)
    ax.xaxis.label.set_color(fg)
    ax.yaxis.label.set_color(fg)
    ax.title.set_color(fg)
    for spine in ax.spines.values():
        spine.set_color(grid)
    ax.grid(True, linestyle="--", alpha=0.55, color=grid)
