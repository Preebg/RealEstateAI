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


def _theme_palette() -> dict[str, str]:
    """Design tokens aligned with ``.streamlit/config.toml`` light/dark tables."""
    if _active_theme_base() == "dark":
        return {
            "primary": "#818cf8",
            "primary_hover": "#6366f1",
            "primary_rgb": "129, 140, 248",
            "text": "#e8eaf0",
            "muted": "rgba(232, 234, 240, 0.62)",
            "border": "#1e2640",
            "surface": "#131927",
            "bg": "#0b0f1a",
            "shadow": "rgba(0, 0, 0, 0.25)",
            "shadow_soft": "rgba(0, 0, 0, 0.15)",
        }
    return {
        "primary": "#4f46e5",
        "primary_hover": "#4338ca",
        "primary_rgb": "79, 70, 229",
        "text": "#1a1a2e",
        "muted": "rgba(26, 26, 46, 0.62)",
        "border": "#e0e4ef",
        "surface": "#f0f2f8",
        "bg": "#fafbfe",
        "shadow": "rgba(26, 26, 46, 0.04)",
        "shadow_soft": "rgba(26, 26, 46, 0.06)",
    }


def _apply_palette_to_css(css: str, palette: dict[str, str]) -> str:
    """Substitute ``__TOKEN__`` placeholders in the app stylesheet."""
    for token, value in palette.items():
        css = css.replace(f"__{token.upper()}__", value)
    return css


def inject_app_css() -> None:
    """Apply global styling: typography, cards, restrained accents."""
    css = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        h1, h2, h3, .app-hero h1, [data-testid="stHeading"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            letter-spacing: -0.025em;
            color: var(--text-color, __TEXT__);
        }
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stCaptionContainer"] {
            color: var(--text-color, __TEXT__);
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
            background: var(--secondary-background-color, __SURFACE__);
            border: 1px solid var(--border-color, __BORDER__);
            border-radius: 12px;
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
        }
        .muted-caption {
            color: var(--text-color, __TEXT__);
            opacity: 0.62;
            font-size: 0.84rem;
            line-height: 1.5;
            max-width: 70ch;
            margin: 0.25rem 0 0.75rem 0;
        }
        .callout-info {
            background: rgba(__PRIMARY_RGB__, 0.08);
            border: 1px solid rgba(__PRIMARY_RGB__, 0.22);
            border-left: 3px solid __PRIMARY__;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0.75rem 0 1rem 0;
            font-size: 0.9rem;
            line-height: 1.55;
            max-width: 70ch;
            color: var(--text-color, __TEXT__);
        }
        .callout-info strong {
            font-weight: 600;
        }
        .stat-grid-label {
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--text-color, __TEXT__);
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
            color: var(--text-color, __TEXT__);
            opacity: 0.55;
        }
        .flow-steps li.active {
            opacity: 1;
            font-weight: 600;
            color: __PRIMARY__;
        }
        .flow-steps li span {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.35rem;
            height: 1.35rem;
            border-radius: 999px;
            background: rgba(__PRIMARY_RGB__, 0.14);
            color: __PRIMARY__;
            font-size: 0.72rem;
            font-weight: 700;
            margin-right: 0.35rem;
        }
        .flow-steps li.active span {
            background: __PRIMARY__;
            color: #fff;
        }
        .map-legend {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            flex-wrap: wrap;
            font-size: 0.8rem;
            color: var(--text-color, __TEXT__);
            opacity: 0.72;
            margin: 0.35rem 0 0.75rem 0;
        }
        .map-legend-bar {
            width: 120px;
            height: 8px;
            border-radius: 4px;
            background: linear-gradient(90deg, #ff5050 0%, #f0c040 50%, #78dc8c 100%);
            border: 1px solid var(--border-color, __BORDER__);
        }
        .sidebar-section-label {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-color, __TEXT__);
            opacity: 0.5;
            margin: 0.5rem 0 0.35rem 0;
        }

        /* ── Bordered containers (address search, cards) ── */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--secondary-background-color, __SURFACE__) !important;
            border-color: var(--border-color, __BORDER__) !important;
        }

        /* ── Metrics ── */
        [data-testid="stSidebar"] [data-testid="stMetric"],
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"] {
            background: var(--secondary-background-color, __SURFACE__);
            border: 1px solid var(--border-color, __BORDER__);
            border-radius: 10px;
            padding: 0.55rem 0.7rem;
            box-shadow: 0 1px 3px __SHADOW__;
        }
        [data-testid="stMetric"] [data-testid="stMetricLabel"] {
            color: var(--text-color, __TEXT__) !important;
            opacity: 0.72;
        }
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--text-color, __TEXT__) !important;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 700;
        }
        [data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: var(--text-color, __TEXT__) !important;
            opacity: 0.85;
        }
        [data-testid="stSidebar"] [data-testid="stMetric"] {
            padding: 0.4rem 0.55rem;
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
            color: var(--text-color, __TEXT__);
        }
        .app-hero p {
            color: var(--text-color, __TEXT__);
            opacity: 0.62;
            margin-top: 0;
            font-size: 0.95rem;
            font-weight: 400;
            line-height: 1.55;
            max-width: 70ch;
        }

        /* ── Buttons ── */
        button[data-testid="baseButton-primary"] {
            background: __PRIMARY__ !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            box-shadow: 0 1px 4px rgba(__PRIMARY_RGB__, 0.25) !important;
            transition: background 0.15s ease, box-shadow 0.15s ease !important;
        }
        button[data-testid="baseButton-primary"]:hover {
            background: __PRIMARY_HOVER__ !important;
            box-shadow: 0 2px 8px rgba(__PRIMARY_RGB__, 0.35) !important;
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
            color: var(--text-color, __TEXT__) !important;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            border-bottom: 2px solid __PRIMARY__ !important;
            color: __PRIMARY__ !important;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"]::before {
            content: "";
            display: block;
            height: 2px;
            background: __PRIMARY__;
            margin: -1rem -1rem 0.75rem -1rem;
        }

        /* ── Expanders ── */
        [data-testid="stExpander"] {
            border: 1px solid var(--border-color, __BORDER__);
            border-radius: 10px;
            background: var(--secondary-background-color, __SURFACE__);
        }
        details summary {
            font-weight: 600;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            color: var(--text-color, __TEXT__);
        }

        /* ── Tables ── */
        [data-testid="stTable"] tbody tr:nth-child(even) {
            background: rgba(__PRIMARY_RGB__, 0.04);
        }
        [data-testid="stTable"] thead th {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--text-color, __TEXT__);
        }
        [data-testid="stTable"] tbody td {
            color: var(--text-color, __TEXT__);
        }

        /* ── Market Pulse ── */
        .pulse-market-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.88rem;
            margin-bottom: 0.1rem;
            color: var(--text-color, __TEXT__);
        }
        .pulse-market-sub {
            color: var(--text-color, __TEXT__);
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
            color: var(--text-color, __TEXT__);
            font-size: 0.84rem;
        }
        [data-testid="column"]:has(.login-card-marker) {
            background: var(--secondary-background-color, __SURFACE__);
            border: 1px solid var(--border-color, __BORDER__);
            border-radius: 16px;
            padding: 2rem 1.5rem 1.5rem !important;
            box-shadow: 0 4px 24px __SHADOW_SOFT__;
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
            color: __PRIMARY__;
            margin: 0 0 0.35rem 0;
        }
        .login-tagline {
            opacity: 0.65;
            font-size: 0.92rem;
            line-height: 1.5;
            max-width: 32ch;
            margin: 0 auto;
            color: var(--text-color, __TEXT__);
        }
        .auth-divider {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin: 1.1rem 0;
            color: var(--text-color, __TEXT__);
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
            background: var(--border-color, __BORDER__);
        }
        .auth-legal-secondary {
            text-align: center;
            margin-top: 1rem;
            font-size: 0.78rem;
            opacity: 0.55;
            color: var(--text-color, __TEXT__);
        }
        .auth-legal-secondary a {
            color: var(--text-color, __TEXT__);
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
            color: var(--text-color, __TEXT__);
            opacity: 0.6;
            margin-bottom: 0.75rem;
            max-width: 70ch;
            line-height: 1.45;
        }

        .metric-with-confidence .metric-label {
            font-size: 0.82rem;
            color: var(--text-color, __TEXT__);
            opacity: 0.72;
        }
        .metric-with-confidence .metric-value {
            font-size: 1.45rem;
            font-weight: 600;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            color: var(--text-color, __TEXT__);
            line-height: 1.2;
        }

        /* ── Quantum / advanced section ── */
        [data-testid="stVerticalBlock"]:has(.quantum-scores-marker) {
            background: var(--secondary-background-color, __SURFACE__);
            border: 1px solid var(--border-color, __BORDER__);
            border-radius: 10px;
            padding: 0.75rem 0.7rem 0.4rem;
            margin-bottom: 0.5rem;
        }
        .quantum-scores-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.9rem;
            margin-bottom: 0.35rem;
            color: var(--text-color, __TEXT__);
        }
        .analysis-section-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-size: 1.05rem;
            font-weight: 600;
            margin: 1.25rem 0 0.5rem 0;
            color: var(--text-color, __TEXT__);
        }

        /* ── Footer ── */
        .app-footer-glossary {
            margin-top: 2.5rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-color, __BORDER__);
            font-size: 0.76rem;
            line-height: 1.5;
            color: var(--text-color, __TEXT__);
            opacity: 0.55;
            max-width: 70ch;
        }
        .app-footer-research {
            margin-top: 0.35rem;
            font-size: 0.74rem;
            opacity: 0.45;
            color: var(--text-color, __TEXT__);
        }
        .app-footer-legal {
            margin-top: 0.55rem;
            font-size: 0.76rem;
            line-height: 1.45;
            color: var(--text-color, __TEXT__);
            opacity: 0.55;
            text-align: center;
        }
        .app-footer-legal a {
            color: var(--text-color, __TEXT__);
            text-decoration: underline;
            opacity: 0.75;
        }

        /* ── Dividers, inputs, alerts ── */
        [data-testid="stMainBlockContainer"] hr {
            border: none;
            height: 1px;
            background: var(--border-color, __BORDER__);
            margin: 1.25rem 0;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stMultiSelect"] div[data-baseweb="select"] {
            border-radius: 8px !important;
            background-color: var(--secondary-background-color, __SURFACE__) !important;
            color: var(--text-color, __TEXT__) !important;
            border-color: var(--border-color, __BORDER__) !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stNumberInput"] input:focus {
            border-color: __PRIMARY__ !important;
            box-shadow: 0 0 0 2px rgba(__PRIMARY_RGB__, 0.18) !important;
        }
        [data-testid="stAlert"] {
            border-radius: 10px;
        }
        [data-testid="stDataFrame"] {
            border-radius: 8px;
            border: 1px solid var(--border-color, __BORDER__);
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
    """
    st.markdown(_apply_palette_to_css(css, _theme_palette()), unsafe_allow_html=True)


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
