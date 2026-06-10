# Q-Scout UI Design System

Design tokens and patterns for the Streamlit app. Implementation lives in `ui_theme.py` and `.streamlit/config.toml`.

## Color tokens

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| Primary | `#4f46e5` | `#818cf8` | Buttons, accents, wordmark |
| Background | `#fafbfe` | `#0b0f1a` | Page canvas |
| Surface | `#f0f2f8` | `#131927` | Cards, metrics |
| Text | `#1a1a2e` | `#e8eaf0` | Body copy |
| Border | `#e0e4ef` | `#1e2640` | Cards, dividers |

## Typography

- **Body:** Inter (400–600)
- **Headings:** Space Grotesk (600–700)
- **H1 (hero):** 1.85rem, −0.03em tracking
- **Section titles:** 1.05rem Space Grotesk
- **Captions:** 0.84rem, 62% opacity, max ~70ch line length

## Component patterns

| Class / helper | Purpose |
|----------------|---------|
| `render_page_hero()` | Consistent page title + benefit-led subtitle |
| `render_callout_info()` | Blue-left-border info box |
| `render_muted_caption()` | Secondary explanatory text |
| `render_flow_steps()` | Numbered workflow indicator |
| `render_map_roi_legend()` | Map marker color scale |
| `render_sidebar_section_label()` | Uppercase sidebar group labels |
| `.section-card` | Bordered content panel |
| `st.container(border=True)` | Streamlit-native bordered sections |

## Tone

- Benefit-led copy for general users; technical terms in expanders/tooltips
- Quantum/QAOA framed as **research simulation**, not hype
- Legal disclaimers unchanged in `legal.py`

## Charts & maps

- Matplotlib: `style_matplotlib_chart()` matches active theme
- Folium: CartoDB Voyager tiles (`portfolio_map_page.py`)
