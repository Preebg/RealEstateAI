"""Terms of Service and Privacy Policy content for CapEigen."""

from __future__ import annotations

APP_NAME = "CapEigen"
APP_TAGLINE = "AI rental underwriting with QAOA portfolio alignment."
EFFECTIVE_DATE = "2026-08-15"

LEGAL_QUERY_PARAM = "legal"
TERMS_PATH = "terms-of-service"
PRIVACY_PATH = "privacy-policy"
LEGAL_PATHS = frozenset({TERMS_PATH, PRIVACY_PATH})
LEGAL_SLUGS = frozenset({"terms", "privacy"})


def get_terms_of_service_text() -> str:
    """Terms of Service copy for public legal pages and sign-up flows."""
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

#### 6) Accounts, availability, and usage logs
We may suspend or terminate access for abuse, security risk, or service changes. Features may change or be discontinued without notice.

We record in-app usage (pages visited and product actions such as analysis, compare, PDF export, bookmarks, and share links) so we can operate the service and understand which features people use. See the Privacy Policy for details.

#### 7) Disclaimers
The service is provided **"as is"** without warranties of any kind. We do not warrant accuracy, completeness, or fitness for a particular purpose.

#### 8) Limitation of liability
To the fullest extent permitted by law, the operator of this project is not liable for indirect, incidental, or consequential damages arising from use of the app or reliance on its outputs.

#### 9) Changes
We may update these terms. Continued use after changes constitutes acceptance of the revised terms. The effective date at the top of this page will be updated when the terms change.

#### 10) Contact
Questions about these terms may be directed to the operator of this portfolio project.
""".strip()


def get_privacy_policy_text() -> str:
    """Privacy Policy copy for public legal pages and sign-up flows."""
    return f"""
### Privacy Policy

**Effective date:** {EFFECTIVE_DATE}

#### 1) Overview
This Privacy Policy explains how {APP_NAME} collects, uses, and shares information when you create an account or use the app. It applies to **all accounts**, including registered users and demo/preview logins.

#### 2) Data we collect
When you create an account or use the app, we may collect:
- **Account data**: email address and Supabase user identifier (UID). Demo logins also have a preview username.
- **Usage analytics**: pages you open in the app, and product actions such as signing in or out, analyzing a property, comparing listings, downloading a PDF, saving a property, creating a share link, and changing underwriting assumptions. Each event may include the page path and a short label (for example a property address you analyzed).
- **Usage data**: properties you analyze and any values you save to your Knowledge Base.
- **Generated outputs**: AI summaries, forecasts, and simulated quantum alignment scores.

We do **not** sell personal information.

#### 3) How we use data
We use your data to:
- authenticate you and protect your Knowledge Base,
- generate analyses you request,
- store properties you save for later retrieval,
- understand which pages and features are most used so we can improve the product.

The site operator (admin) can review usage in aggregate (most popular pages and actions) and as an activity feed tied to an account identifier (email or demo username).

#### 4) Sharing
We may share data with:
- **Supabase** (database and authentication provider),
- **AI model providers** used for analysis (only the inputs needed to produce the requested output).

#### 5) Security and retention
We apply reasonable security practices; however, no system is perfectly secure. Your saved Knowledge Base entries are retained until you delete them or we retire the service. Usage analytics are retained to support product improvement unless you request deletion.

#### 6) Your choices
You can stop using the app at any time. If you want your data removed, contact the operator of this portfolio project.

#### 7) Children
The app is not directed to children under 13, and we do not knowingly collect their personal information.

#### 8) Changes
We may update this policy. Material changes will be reflected by updating the effective date above. The current policy is always available on this page.

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


def default_legal_document(slug: str) -> dict[str, str]:
    """Built-in Terms or Privacy copy used until an admin publishes an edit."""
    key = (slug or "").strip().lower()
    if key == "privacy":
        return {
            "slug": "privacy",
            "title": "Privacy Policy",
            "body": get_privacy_policy_text(),
            "effective_date": EFFECTIVE_DATE,
        }
    if key == "terms":
        return {
            "slug": "terms",
            "title": "Terms of Service",
            "body": get_terms_of_service_text(),
            "effective_date": EFFECTIVE_DATE,
        }
    msg = f"Unknown legal document slug: {slug}"
    raise ValueError(msg)
