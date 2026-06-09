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
        .confidence-badge {
            display: inline-block;
            font-size: 0.68rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            padding: 0.12rem 0.42rem;
            border-radius: 999px;
            color: #fff;
            margin-left: 0.35rem;
            vertical-align: middle;
            white-space: nowrap;
        }
        .metric-with-confidence {
            margin-bottom: 0.35rem;
        }
        .metric-with-confidence .metric-label {
            font-size: 0.82rem;
            color: var(--text-color);
            opacity: 0.72;
        }
        .metric-with-confidence .metric-value {
            font-size: 1.45rem;
            font-weight: 600;
            color: var(--text-color);
            line-height: 1.2;
        }
        .app-footer-glossary {
            margin-top: 2.5rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-color, rgba(128, 128, 128, 0.28));
            font-size: 0.78rem;
            line-height: 1.45;
            color: var(--text-color);
            opacity: 0.68;
        }
        .app-footer-legal {
            margin-top: 0.55rem;
            font-size: 0.78rem;
            line-height: 1.45;
            color: var(--text-color);
            opacity: 0.68;
            text-align: center;
        }
        .app-footer-legal a {
            color: var(--primary-color);
            text-decoration: none;
        }
        .app-footer-legal a:hover {
            text-decoration: underline;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_app_footer_glossary() -> None:
    """Footer glossary plus Terms of Service and Privacy Policy links."""
    from legal import render_legal_footer_links

    st.markdown(
        '<p class="app-footer-glossary">'
        "<strong>Quantum Alignment Score</strong> measures how well the QAOA optimizer "
        "matches your investment targets (0–100%). It is not financial risk or a market prediction."
        "</p>",
        unsafe_allow_html=True,
    )
    render_legal_footer_links()


def render_confidence_badge(score: float, *, show_pct: bool = True) -> str:
    """Return HTML for a small data-quality confidence badge (0–1)."""
    from data_provenance import confidence_badge_color

    pct = f"{score * 100:.0f}%" if show_pct else ""
    color = confidence_badge_color(score)
    return (
        f'<span class="confidence-badge" style="background:{color};" '
        f'title="How confident we are in this scraped/inferred value—not whether the amount is high or low.">'
        f'Data {pct}</span>'
    )


def render_metric_with_confidence(
    label: str,
    value: str,
    confidence: float | None,
    *,
    help_text: str | None = None,
) -> None:
    """Render a metric row with an optional confidence badge."""
    badge_html = render_confidence_badge(confidence) if confidence is not None else ""
    help_attr = f' title="{help_text}"' if help_text else ""
    st.markdown(
        f'<div class="metric-with-confidence"{help_attr}>'
        f'<div class="metric-label">{label}{badge_html}</div>'
        f'<div class="metric-value">{value}</div>'
        f"</div>",
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
