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
    """Apply premium global styling: fonts, glassmorphism, animations, polish."""
    st.markdown(
        """
        <style>
        /* ═══════════════════════════════════════════════
           Typography — Google Fonts
           ═══════════════════════════════════════════════ */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        h1, h2, h3, .app-hero h1, [data-testid="stHeading"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            letter-spacing: -0.025em;
        }

        /* ═══════════════════════════════════════════════
           Animations
           ═══════════════════════════════════════════════ */
        @keyframes fadeSlideUp {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes subtleGlow {
            0%, 100% { box-shadow: 0 0 12px rgba(79, 70, 229, 0.08); }
            50%      { box-shadow: 0 0 20px rgba(79, 70, 229, 0.18); }
        }
        @keyframes gradientShift {
            0%   { background-position: 0% 50%; }
            50%  { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* ═══════════════════════════════════════════════
           Main container — fade in on load
           ═══════════════════════════════════════════════ */
        [data-testid="stMainBlockContainer"] {
            animation: fadeSlideUp 0.5s ease-out;
        }

        /* ═══════════════════════════════════════════════
           Metric Cards — glassmorphism + gradient accent
           ═══════════════════════════════════════════════ */
        [data-testid="stSidebar"] [data-testid="stMetric"],
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"] {
            background: linear-gradient(135deg,
                rgba(79, 70, 229, 0.04) 0%,
                rgba(129, 140, 248, 0.02) 100%);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(79, 70, 229, 0.12);
            border-left: 3px solid;
            border-image: linear-gradient(180deg, #4f46e5 0%, #818cf8 100%) 1;
            border-radius: 12px;
            padding: 0.6rem 0.75rem;
            box-shadow: 0 2px 8px rgba(79, 70, 229, 0.06);
            transition: transform 0.2s ease, box-shadow 0.25s ease;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMetric"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(79, 70, 229, 0.12);
        }
        [data-testid="stSidebar"] [data-testid="stMetric"] {
            padding: 0.4rem 0.55rem;
            border-radius: 10px;
        }
        /* Metric value text */
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 700;
        }

        /* ═══════════════════════════════════════════════
           Page Hero — gradient text
           ═══════════════════════════════════════════════ */
        .app-hero {
            margin-bottom: 0.35rem;
            animation: fadeSlideUp 0.6s ease-out;
        }
        .app-hero h1 {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            margin-bottom: 0.2rem;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #818cf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .app-hero p {
            color: var(--text-color);
            opacity: 0.65;
            margin-top: 0;
            font-size: 0.95rem;
            font-weight: 400;
        }

        /* ═══════════════════════════════════════════════
           Buttons — gradient primary + glow
           ═══════════════════════════════════════════════ */
        button[data-testid="baseButton-primary"] {
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%) !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
            box-shadow: 0 2px 10px rgba(79, 70, 229, 0.25) !important;
            transition: transform 0.15s ease, box-shadow 0.2s ease !important;
        }
        button[data-testid="baseButton-primary"]:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 18px rgba(79, 70, 229, 0.35) !important;
        }
        button[data-testid="baseButton-secondary"] {
            border-radius: 10px !important;
            transition: all 0.15s ease !important;
        }
        button[data-testid="baseButton-secondary"]:hover {
            border-color: var(--primary-color) !important;
        }
        /* Keep Google OAuth + legal link buttons on-brand */
        div:has(.google-signin-shell-marker) button[data-testid="baseButton-secondary"],
        div:has(> .auth-legal-links-marker) button[data-testid="baseButton-secondary"] {
            background: transparent !important;
            box-shadow: none !important;
        }

        /* ═══════════════════════════════════════════════
           Tabs — gradient active underline
           ═══════════════════════════════════════════════ */
        [data-testid="stTabs"] button[data-baseweb="tab"] {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.9rem;
            transition: color 0.2s ease;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            border-bottom: 3px solid transparent !important;
            border-image: linear-gradient(90deg, #4f46e5, #818cf8) 1 !important;
        }

        /* ═══════════════════════════════════════════════
           Sidebar — accent bar + polish
           ═══════════════════════════════════════════════ */
        [data-testid="stSidebar"]::before {
            content: "";
            display: block;
            height: 3px;
            background: linear-gradient(90deg, #4f46e5, #7c3aed, #818cf8);
            margin: -1rem -1rem 0.75rem -1rem;
            border-radius: 0 0 6px 6px;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            letter-spacing: -0.02em;
        }

        /* ═══════════════════════════════════════════════
           Expanders — rounded + smooth
           ═══════════════════════════════════════════════ */
        [data-testid="stExpander"] {
            border: 1px solid var(--border-color, rgba(128, 128, 128, 0.2));
            border-radius: 12px;
            overflow: hidden;
            transition: border-color 0.2s ease;
        }
        [data-testid="stExpander"]:hover {
            border-color: rgba(79, 70, 229, 0.25);
        }
        details summary {
            font-weight: 600;
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
        }

        /* ═══════════════════════════════════════════════
           Tables — alternating rows + rounded
           ═══════════════════════════════════════════════ */
        [data-testid="stTable"] {
            border-radius: 10px;
            overflow: hidden;
        }
        [data-testid="stTable"] tbody tr:nth-child(even) {
            background: rgba(79, 70, 229, 0.03);
        }
        [data-testid="stTable"] tbody tr:hover {
            background: rgba(79, 70, 229, 0.06);
        }
        [data-testid="stTable"] thead th {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* ═══════════════════════════════════════════════
           Market Pulse cards
           ═══════════════════════════════════════════════ */
        .pulse-market-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 0.15rem;
            color: var(--text-color);
        }
        .pulse-market-sub {
            color: var(--text-color);
            opacity: 0.6;
            font-size: 0.78rem;
            margin-top: 0.45rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* ═══════════════════════════════════════════════
           Auth agreement text
           ═══════════════════════════════════════════════ */
        .auth-agreement-text {
            margin: 0;
            padding-top: 0.42rem;
            line-height: 1.2;
            color: var(--text-color);
        }

        /* ═══════════════════════════════════════════════
           Confidence badges — enhanced
           ═══════════════════════════════════════════════ */
        .confidence-badge {
            display: inline-block;
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            padding: 0.14rem 0.5rem;
            border-radius: 999px;
            color: #fff;
            margin-left: 0.35rem;
            vertical-align: middle;
            white-space: nowrap;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
            text-transform: uppercase;
        }

        /* ═══════════════════════════════════════════════
           Metric with confidence
           ═══════════════════════════════════════════════ */
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
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            color: var(--text-color);
            line-height: 1.2;
        }

        /* ═══════════════════════════════════════════════
           Quantum scores container
           ═══════════════════════════════════════════════ */
        [data-testid="stVerticalBlock"]:has(.quantum-scores-marker) {
            background: linear-gradient(135deg,
                rgba(79, 70, 229, 0.05) 0%,
                rgba(124, 58, 237, 0.03) 100%);
            border: 1px solid rgba(79, 70, 229, 0.1);
            border-radius: 14px;
            padding: 0.85rem 0.75rem 0.5rem;
            margin-bottom: 0.65rem;
            animation: subtleGlow 4s ease-in-out infinite;
        }
        .quantum-scores-title {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 0.35rem;
            color: var(--text-color);
        }

        /* ═══════════════════════════════════════════════
           Login container styling
           ═══════════════════════════════════════════════ */
        [data-testid="column"]:has(.login-card-marker) {
            background: linear-gradient(135deg,
                rgba(79, 70, 229, 0.04) 0%,
                rgba(129, 140, 248, 0.02) 100%);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(79, 70, 229, 0.1);
            border-radius: 20px;
            padding: 1.5rem 1rem 1.25rem !important;
            animation: fadeSlideUp 0.6s ease-out;
        }
        .login-brand {
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .login-brand h2 {
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            font-weight: 700;
            font-size: 1.75rem;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #818cf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.25rem;
        }
        .login-brand p {
            opacity: 0.6;
            font-size: 0.88rem;
        }

        /* ═══════════════════════════════════════════════
           Footer — refined
           ═══════════════════════════════════════════════ */
        .app-footer-glossary {
            margin-top: 2.5rem;
            padding-top: 0.75rem;
            border-top: 2px solid transparent;
            border-image: linear-gradient(90deg,
                transparent 0%,
                rgba(79, 70, 229, 0.2) 50%,
                transparent 100%) 1;
            font-size: 0.78rem;
            line-height: 1.5;
            color: var(--text-color);
            opacity: 0.6;
        }
        .app-footer-legal {
            margin-top: 0.55rem;
            font-size: 0.78rem;
            line-height: 1.45;
            color: var(--text-color);
            opacity: 0.6;
            text-align: center;
        }
        .app-footer-legal a {
            color: var(--primary-color);
            text-decoration: none;
            font-weight: 500;
            transition: opacity 0.15s ease;
        }
        .app-footer-legal a:hover {
            text-decoration: underline;
            opacity: 0.85;
        }

        /* ═══════════════════════════════════════════════
           Dividers — subtle gradient
           ═══════════════════════════════════════════════ */
        [data-testid="stMainBlockContainer"] hr {
            border: none;
            height: 1px;
            background: linear-gradient(90deg,
                transparent 0%,
                rgba(79, 70, 229, 0.18) 30%,
                rgba(79, 70, 229, 0.18) 70%,
                transparent 100%);
            margin: 1.25rem 0;
        }

        /* ═══════════════════════════════════════════════
           Scrollbar polish (Webkit)
           ═══════════════════════════════════════════════ */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(79, 70, 229, 0.2);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(79, 70, 229, 0.35);
        }

        /* ═══════════════════════════════════════════════
           Inputs — refined borders
           ═══════════════════════════════════════════════ */
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stSelectbox"] > div,
        [data-testid="stMultiSelect"] > div {
            border-radius: 10px !important;
            transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stNumberInput"] input:focus {
            border-color: var(--primary-color) !important;
            box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.12) !important;
        }

        /* ═══════════════════════════════════════════════
           Alerts + dataframes
           ═══════════════════════════════════════════════ */
        [data-testid="stAlert"] {
            border-radius: 12px;
        }
        [data-testid="stDataFrame"] {
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid var(--border-color, rgba(128, 128, 128, 0.2));
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
