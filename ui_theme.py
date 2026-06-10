"""Shared Streamlit styling for the web app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    import matplotlib.axes
    import matplotlib.figure

# Design tokens (mirror .streamlit/config.toml)
COLOR_PRIMARY = "#4f46e5"
COLOR_TEXT = "#1a1a2e"
COLOR_MUTED = "rgba(26, 26, 46, 0.62)"
COLOR_BORDER = "#e0e4ef"
COLOR_SURFACE = "#ffffff"


def _active_theme_base() -> str:
    """Return ``light`` or ``dark`` for the viewer's active Streamlit theme."""
    theme = getattr(st.context, "theme", None)
    if theme is not None:
        base = theme.get("base") or theme.get("type")
        if base in {"light", "dark"}:
            return base
    return "light"


def inject_app_css() -> None:
    """Apply global styling: typography, cards, restrained accents."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        h1, h2, h3, .app-hero h1, [data-testid="stHeading"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            letter-spacing: -0.025em;
        }

        @keyframes fadeSlideUp {
            from { opacity: 0; transform: translateY(8px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        [data-testid="stMainBlockContainer"] {
            animation: fadeSlideUp 0.4s ease-out;
            max-width: 70rem;
        }

        /* ── Utility classes ── */
        .section-card {
            background: var(--secondary-background-color, #f8f9fc);
            border: 1px solid var(--border-color, #e0e4ef);
            border-radius: 12px;
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
        }
        .muted-caption {
            color: var(--text-color);
            opacity: 0.62;
            font-size: 0.84rem;
            line-height: 1.5;
            max-width: 70ch;
            margin: 0.25rem 0 0.75rem 0;
        }
        .callout-info {
            background: rgba(79, 70, 229, 0.05);
            border: 1px solid rgba(79, 70, 229, 0.14);
            border-left: 3px solid #4f46e5;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0.75rem 0 1rem 0;
            font-size: 0.9rem;
            line-height: 1.55;
            max-width: 70ch;
            color: var(--text-color);
        }
        .callout-info strong {
            font-weight: 600;
        }
        .stat-grid-label {
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--text-color);
            opacity: 0.65;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            margin-bottom: 0.35rem;
        }
        .flow-steps {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem 1.25rem;
            margin: 0.5rem 0 1.25rem 0;
            padding: 0;
            list-style: none;
        }
        .flow-steps li {
            font-size: 0.84rem;
            color: var(--text-color);
            opacity: 0.55;
        }
        .flow-steps li.active {
            opacity: 1;
            font-weight: 600;
            color: #4f46e5;
        }
        .flow-steps li span {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.35rem;
            height: 1.35rem;
            border-radius: 999px;
            background: rgba(79, 70, 229, 0.1);
            color: #4f46e5;
            font-size: 0.72rem;
            font-weight: 700;
            margin-right: 0.35rem;
        }
        .flow-steps li.active span {
            background: #4f46e5;
            color: #fff;
        }
        .map-legend {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            flex-wrap: wrap;
            font-size: 0.8rem;
            color: var(--text-color);
            opacity: 0.72;
            margin: 0.35rem 0 0.75rem 0;
        }
        .map-legend-bar {
            width: 120px;
            height: 8px;
            border-radius: 4px;
            background: linear-gradient(90deg, #ff5050 0%, #f0c040 50%, #78dc8c 100%);
            border: 1px solid var(--border-color, #e0e4ef);
        }
        .sidebar-section-label {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-color);
            opacity: 0.5;
            margin: 0.5rem 0 0.35rem 0;
        }

        /* ── Metrics ── */
        [data-testid="stSidebar"] [data-testid="stMetric"],
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"] {
            background: var(--secondary-background-color, #f8f9fc);
            border: 1px solid var(--border-color, #e0e4ef);
            border-radius: 10px;
            padding: 0.55rem 0.7rem;
            box-shadow: 0 1px 3px rgba(26, 26, 46, 0.04);
        }
        [data-testid="stSidebar"] [data-testid="stMetric"] {
            padding: 0.4rem 0.55rem;
        }
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 700;
        }

        /* ── Page hero ── */
        .app-hero {
            margin-bottom: 1rem;
            animation: fadeSlideUp 0.5s ease-out;
        }
        .app-hero h1 {
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            margin-bottom: 0.35rem;
            color: var(--text-color);
        }
        .app-hero p {
            color: var(--text-color);
            opacity: 0.62;
            margin-top: 0;
            font-size: 0.95rem;
            font-weight: 400;
            line-height: 1.55;
            max-width: 70ch;
        }

        /* ── Buttons ── */
        button[data-testid="baseButton-primary"] {
            background: #4f46e5 !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            box-shadow: 0 1px 4px rgba(79, 70, 229, 0.2) !important;
            transition: background 0.15s ease, box-shadow 0.15s ease !important;
        }
        button[data-testid="baseButton-primary"]:hover {
            background: #4338ca !important;
            box-shadow: 0 2px 8px rgba(79, 70, 229, 0.28) !important;
        }
        button[data-testid="baseButton-secondary"] {
            border-radius: 8px !important;
        }
        div:has(.google-signin-shell-marker) button[data-testid="baseButton-secondary"],
        div:has(> .auth-legal-links-marker) button[data-testid="baseButton-secondary"] {
            background: transparent !important;
            box-shadow: none !important;
        }

        /* ── Tabs ── */
        [data-testid="stTabs"] button[data-baseweb="tab"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.88rem;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            border-bottom: 2px solid #4f46e5 !important;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"]::before {
            content: "";
            display: block;
            height: 2px;
            background: #4f46e5;
            margin: -1rem -1rem 0.75rem -1rem;
        }

        /* ── Expanders ── */
        [data-testid="stExpander"] {
            border: 1px solid var(--border-color, #e0e4ef);
            border-radius: 10px;
        }
        details summary {
            font-weight: 600;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
        }

        /* ── Tables ── */
        [data-testid="stTable"] tbody tr:nth-child(even) {
            background: rgba(79, 70, 229, 0.02);
        }
        [data-testid="stTable"] thead th {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* ── Market Pulse ── */
        .pulse-market-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.88rem;
            margin-bottom: 0.1rem;
            color: var(--text-color);
        }
        .pulse-market-sub {
            color: var(--text-color);
            opacity: 0.55;
            font-size: 0.72rem;
            margin-top: 0.35rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .pulse-card-compact [data-testid="stMetric"] {
            padding: 0.3rem 0.45rem !important;
            border-radius: 8px !important;
        }
        .pulse-card-compact [data-testid="stMetricValue"] {
            font-size: 0.95rem !important;
        }
        .pulse-card-compact [data-testid="stMetricLabel"] {
            font-size: 0.72rem !important;
        }

        /* ── Auth ── */
        .auth-agreement-text {
            margin: 0;
            padding-top: 0.42rem;
            line-height: 1.2;
            color: var(--text-color);
            font-size: 0.84rem;
        }
        [data-testid="column"]:has(.login-card-marker) {
            background: var(--secondary-background-color, #f8f9fc);
            border: 1px solid var(--border-color, #e0e4ef);
            border-radius: 16px;
            padding: 2rem 1.5rem 1.5rem !important;
            box-shadow: 0 4px 24px rgba(26, 26, 46, 0.06);
            animation: fadeSlideUp 0.5s ease-out;
        }
        .login-brand {
            text-align: center;
            margin-bottom: 0.75rem;
        }
        .login-wordmark {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 700;
            font-size: 1.85rem;
            letter-spacing: -0.04em;
            color: #4f46e5;
            margin: 0 0 0.35rem 0;
        }
        .login-tagline {
            opacity: 0.65;
            font-size: 0.92rem;
            line-height: 1.5;
            max-width: 32ch;
            margin: 0 auto;
            color: var(--text-color);
        }
        .auth-divider {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin: 1.1rem 0;
            color: var(--text-color);
            opacity: 0.45;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .auth-divider::before,
        .auth-divider::after {
            content: "";
            flex: 1;
            height: 1px;
            background: var(--border-color, #e0e4ef);
        }
        .auth-legal-secondary {
            text-align: center;
            margin-top: 1rem;
            font-size: 0.78rem;
            opacity: 0.55;
            color: var(--text-color);
        }
        .auth-legal-secondary a {
            color: var(--text-color);
            text-decoration: underline;
            opacity: 0.85;
        }

        /* ── Confidence badges ── */
        .confidence-badge {
            display: inline-block;
            font-size: 0.62rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            padding: 0.1rem 0.4rem;
            border-radius: 999px;
            color: #fff;
            margin-left: 0.3rem;
            vertical-align: middle;
            white-space: nowrap;
            text-transform: uppercase;
        }
        .confidence-explainer {
            font-size: 0.8rem;
            color: var(--text-color);
            opacity: 0.6;
            margin-bottom: 0.75rem;
            max-width: 70ch;
            line-height: 1.45;
        }

        .metric-with-confidence .metric-label {
            font-size: 0.82rem;
            color: var(--text-color);
            opacity: 0.72;
        }
        .metric-with-confidence .metric-value {
            font-size: 1.45rem;
            font-weight: 600;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            color: var(--text-color);
            line-height: 1.2;
        }

        /* ── Quantum / advanced section ── */
        [data-testid="stVerticalBlock"]:has(.quantum-scores-marker) {
            background: var(--secondary-background-color, #f8f9fc);
            border: 1px solid var(--border-color, #e0e4ef);
            border-radius: 10px;
            padding: 0.75rem 0.7rem 0.4rem;
            margin-bottom: 0.5rem;
        }
        .quantum-scores-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.9rem;
            margin-bottom: 0.35rem;
            color: var(--text-color);
        }
        .analysis-section-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-size: 1.05rem;
            font-weight: 600;
            margin: 1.25rem 0 0.5rem 0;
            color: var(--text-color);
        }

        /* ── Footer ── */
        .app-footer-glossary {
            margin-top: 2.5rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-color, #e0e4ef);
            font-size: 0.76rem;
            line-height: 1.5;
            color: var(--text-color);
            opacity: 0.55;
            max-width: 70ch;
        }
        .app-footer-research {
            margin-top: 0.35rem;
            font-size: 0.74rem;
            opacity: 0.45;
            color: var(--text-color);
        }
        .app-footer-legal {
            margin-top: 0.55rem;
            font-size: 0.76rem;
            line-height: 1.45;
            color: var(--text-color);
            opacity: 0.55;
            text-align: center;
        }
        .app-footer-legal a {
            color: var(--text-color);
            text-decoration: underline;
            opacity: 0.75;
        }

        /* ── Dividers, inputs, alerts ── */
        [data-testid="stMainBlockContainer"] hr {
            border: none;
            height: 1px;
            background: var(--border-color, #e0e4ef);
            margin: 1.25rem 0;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input {
            border-radius: 8px !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stNumberInput"] input:focus {
            border-color: #4f46e5 !important;
            box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.1) !important;
        }
        [data-testid="stAlert"] {
            border-radius: 10px;
        }
        [data-testid="stDataFrame"] {
            border-radius: 8px;
            border: 1px solid var(--border-color, #e0e4ef);
        }

        /* ── Address search prominence ── */
        [data-testid="stMainBlockContainer"] .address-search-marker + div [data-testid="stMultiSelect"] {
            border-radius: 10px;
        }

        /* ── Mobile ── */
        @media (max-width: 640px) {
            .app-hero h1 { font-size: 1.5rem; }
            [data-testid="stMainBlockContainer"] { padding-left: 0.75rem; padding-right: 0.75rem; }
            [data-testid="column"]:has(.login-card-marker) {
                padding: 1.25rem 1rem !important;
            }
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
        "<strong>Alignment Score</strong> shows how well a property matches typical "
        "cash-flow and appreciation targets (0–100%). It is a research simulation, "
        "not a market forecast or financial advice."
        "</p>"
        '<p class="app-footer-research">Built with QAOA portfolio-alignment research.</p>',
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
        f'title="Data quality for this field—not whether the amount is high or low.">'
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
    from security_utils import escape_html

    safe_title = escape_html(title)
    safe_subtitle = escape_html(subtitle)
    st.markdown(
        f'<div class="app-hero"><h1>{safe_title}</h1><p>{safe_subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def render_muted_caption(text: str) -> None:
    """Secondary explanatory copy with consistent styling."""
    st.markdown(f'<p class="muted-caption">{text}</p>', unsafe_allow_html=True)


def render_callout_info(html: str) -> None:
    """Highlighted informational callout box."""
    st.markdown(f'<div class="callout-info">{html}</div>', unsafe_allow_html=True)


def render_flow_steps(steps: list[str], *, active_index: int = 0) -> None:
    """Horizontal numbered step indicator for multi-step workflows."""
    items = []
    for idx, label in enumerate(steps):
        active_class = "active" if idx == active_index else ""
        items.append(
            f'<li class="{active_class}"><span>{idx + 1}</span>{label}</li>'
        )
    st.markdown(
        f'<ul class="flow-steps">{"".join(items)}</ul>',
        unsafe_allow_html=True,
    )


def render_map_roi_legend() -> None:
    """Color scale legend for portfolio map marker encoding."""
    st.markdown(
        '<div class="map-legend">'
        '<span>1-yr ROI:</span>'
        '<div class="map-legend-bar" aria-hidden="true"></div>'
        '<span>lower</span><span>→</span><span>higher</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_sidebar_section_label(label: str) -> None:
    """Uppercase sidebar group heading."""
    st.markdown(f'<p class="sidebar-section-label">{label}</p>', unsafe_allow_html=True)


def style_matplotlib_chart(
    fig: matplotlib.figure.Figure,
    ax: matplotlib.axes.Axes,
) -> None:
    """Match matplotlib output to the active Streamlit light/dark theme."""
    if _active_theme_base() == "dark":
        bg = "#0b0f1a"
        fg = "#e8eaf0"
        grid = "#1e2640"
    else:
        bg = "#fafbfe"
        fg = "#1a1a2e"
        grid = "#e0e4ef"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=fg)
    ax.xaxis.label.set_color(fg)
    ax.yaxis.label.set_color(fg)
    ax.title.set_color(fg)
    for spine in ax.spines.values():
        spine.set_color(grid)
    ax.grid(True, linestyle="--", alpha=0.55, color=grid)
