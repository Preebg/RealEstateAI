"""Terms of Service and Privacy Policy content for AI Property Scout."""

from __future__ import annotations

import streamlit as st

APP_NAME = "AI Property Scout"
EFFECTIVE_DATE = "2025-06-09"

LEGAL_QUERY_PARAM = "legal"
TERMS_PATH = "terms-of-service"
PRIVACY_PATH = "privacy-policy"
LEGAL_PATHS = frozenset({TERMS_PATH, PRIVACY_PATH})


def get_terms_of_service_text() -> str:
    """Terms of Service copy shown on the public legal page and sign-up dialog."""
    return f"""
### Terms of Service

**Effective date:** {EFFECTIVE_DATE}

#### 1) Agreement
By creating an account or using {APP_NAME}, you agree to these Terms of Service. If you do not agree, do not use the app.

#### 2) What this app is
{APP_NAME} is an AI-assisted, educational real-estate analysis tool. It may generate estimates, summaries, and QAOA quantum alignment scores based on user inputs and third-party information. It is **not** a broker, lender, appraiser, tax advisor, or financial advisor.

#### 3) Educational use only
Outputs are for learning and research. They are **not** investment, legal, tax, or lending advice. You are responsible for your own due diligence before any real-estate decision.

#### 4) AI and quantum simulation disclosure
The app may display **quantum-probabilistic scores** or similar risk-style outputs. These are **simulations** derived from mathematical transforms of user inputs and/or model outputs. They are **not guarantees** and must not be interpreted as predictions of future performance.

If you are located in **New York (NY)**, **Texas (TX)**, or **California (CA)**, you acknowledge:
- the tool is **educational** and may produce erroneous or biased results,
- AI outputs may be incomplete, outdated, or incorrect,
- any "quantum" outputs are a simulation and **not** a financial promise.

#### 5) Your responsibilities
You agree to:
- provide accurate account information,
- keep your credentials secure,
- use the app only for lawful purposes,
- not attempt to disrupt, scrape, or reverse-engineer the service.

#### 6) Accounts and availability
We may suspend or terminate access for abuse, security risk, or service changes. Features may change or be discontinued without notice.

#### 7) Disclaimers
The service is provided **"as is"** without warranties of any kind. We do not warrant accuracy, completeness, or fitness for a particular purpose.

#### 8) Limitation of liability
To the fullest extent permitted by law, the operator of this project is not liable for indirect, incidental, or consequential damages arising from use of the app or reliance on its outputs.

#### 9) Changes
We may update these terms. Continued use after changes constitutes acceptance of the revised terms.

#### 10) Contact
Questions about these terms may be directed to the operator of this portfolio project.
""".strip()


def get_privacy_policy_text() -> str:
    """Privacy Policy copy shown on the public legal page and sign-up dialog."""
    return f"""
### Privacy Policy

**Effective date:** {EFFECTIVE_DATE}

#### 1) Overview
This Privacy Policy explains how {APP_NAME} collects, uses, and shares information when you create an account or use the app.

#### 2) Data we collect
When you create an account or use the app, we may collect:
- **Account data**: email address and Supabase user identifier (UID)
- **Usage data**: properties you analyze and any values you save to your Knowledge Base
- **Generated outputs**: AI summaries, forecasts, and simulated quantum alignment scores

We do **not** sell personal information.

#### 3) How we use data
We use your data to:
- authenticate you and protect your Knowledge Base,
- generate analyses you request,
- store properties you save for later retrieval.

#### 4) Sharing
We may share data with:
- **Supabase** (database and authentication provider),
- **AI model providers** used for analysis (only the inputs needed to produce the requested output).

#### 5) Security and retention
We apply reasonable security practices; however, no system is perfectly secure. Your saved Knowledge Base entries are retained until you delete them or we retire the service.

#### 6) Your choices
You can stop using the app at any time. If you want your data removed, contact the operator of this portfolio project.

#### 7) Children
The app is not directed to children under 13, and we do not knowingly collect their personal information.

#### 8) Changes
We may update this policy. Material changes will be reflected by updating the effective date above.

#### 9) Contact
Privacy questions may be directed to the operator of this portfolio project.
""".strip()


def get_signup_policy_text() -> str:
    """Combined policy text kept for backward compatibility."""
    return f"{get_terms_of_service_text()}\n\n---\n\n{get_privacy_policy_text()}"


def legal_page_url(path: str) -> str:
    """Build a query-string URL for a public legal page."""
    if path not in LEGAL_PATHS:
        msg = f"Unknown legal page path: {path}"
        raise ValueError(msg)
    return f"?{LEGAL_QUERY_PARAM}={path}"


def requested_legal_path() -> str | None:
    """Return the legal page path from the current query string, if any."""
    value = st.query_params.get(LEGAL_QUERY_PARAM)
    if not value:
        return None
    cleaned = str(value).strip()
    if cleaned in LEGAL_PATHS:
        return cleaned
    return None


def render_legal_page(path: str) -> None:
    """Render a standalone public legal page."""
    if path == TERMS_PATH:
        st.title("Terms of Service")
        st.markdown(get_terms_of_service_text())
    elif path == PRIVACY_PATH:
        st.title("Privacy Policy")
        st.markdown(get_privacy_policy_text())
    else:
        st.error("Unknown legal page.")
        return

    st.caption(f"Last updated {EFFECTIVE_DATE}.")
    st.page_link("AIUnderwriterv2.py", label="Back to sign in", icon="←")


def render_legal_footer_links(*, prefix: str = "") -> None:
    """Footer links to the public Terms of Service and Privacy Policy pages."""
    terms_href = legal_page_url(TERMS_PATH)
    privacy_href = legal_page_url(PRIVACY_PATH)
    st.markdown(
        f'<p class="app-footer-legal">{prefix}'
        f'<a href="{terms_href}">Terms of Service</a>'
        f' &middot; '
        f'<a href="{privacy_href}">Privacy Policy</a>'
        f"</p>",
        unsafe_allow_html=True,
    )
