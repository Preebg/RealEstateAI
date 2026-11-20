/**
 * Bundled Terms / Privacy copy so /legal/* works when FastAPI is offline.
 * Keep in sync with legal.py defaults when the built-in text changes.
 */

export const LEGAL_DEFAULT_EFFECTIVE_DATE = '2026-08-24'

export type BundledLegalDocument = {
  title: string
  body: string
  effective_date: string
}

const TERMS_BODY = `### Terms of Service

**Effective date:** ${LEGAL_DEFAULT_EFFECTIVE_DATE}

#### 1) Agreement
By creating an account or using CapEigen, you agree to these Terms of Service. If you do not agree, do not use the app.

#### 2) What this app is
CapEigen is an AI-assisted, educational real-estate analysis tool. It may generate estimates, summaries, and QAOA quantum alignment scores based on user inputs and third-party information. It is **not** a broker, lender, appraiser, tax advisor, or financial advisor.

#### 3) Educational use only
Outputs are for learning and research. They are **not** investment, legal, tax, or lending advice. You are responsible for your own due diligence before any real-estate decision. **Property of the Day** and popularity (view) counts are educational highlights based on stored underwriting estimates and in-app activity. They are not recommendations to buy, sell, or hold any property.

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

You may delete your account at any time from **Account settings** in the app. Deletion permanently removes your account and associated app data as described in the Privacy Policy. You do not need to contact the operator to delete your account.

We record in-app usage (pages visited and product actions such as analysis, compare, PDF export, bookmarks, and share links) so we can operate the service and understand which features people use. We also count unique signed-in views of each listing so you can see which properties are more popular, and we may show a once-per-day **Property of the Day** highlight when you first use the app that day. See the Privacy Policy for details.

#### 7) Disclaimers
The service is provided **"as is"** without warranties of any kind. We do not warrant accuracy, completeness, or fitness for a particular purpose.

#### 8) Limitation of liability
To the fullest extent permitted by law, the operator of this project is not liable for indirect, incidental, or consequential damages arising from use of the app or reliance on its outputs.

#### 9) Changes
We may update these terms. When we do, the effective date at the top of this page will change, and signed-in users will be asked to review and accept the updated Terms and Privacy Policy before continuing to use the app.

#### 10) Contact
Questions about these terms may be directed to the operator of this portfolio project.`

const PRIVACY_BODY = `### Privacy Policy

**Effective date:** ${LEGAL_DEFAULT_EFFECTIVE_DATE}

#### 1) Overview
This Privacy Policy explains how CapEigen collects, uses, and shares information when you create an account or use the app. It applies to **all accounts**, including registered users and demo/preview logins.

#### 2) Data we collect
When you create an account or use the app, we may collect:
- **Account data**: email address and Supabase user identifier (UID). Demo logins also have a preview username.
- **Usage analytics**: pages you open in the app, and product actions such as signing in or out, analyzing a property, comparing listings, downloading a PDF, saving a property, creating a share link, and changing underwriting assumptions. Each event may include the page path and a short label (for example a property address you analyzed).
- **Property viewership**: when you open a catalog listing while signed in, we record that your account viewed that property (user identifier + property identifier, with first and last viewed times). We use this to compute an aggregate **view count** shown to other users so they can see which listings are more popular. We do **not** show other users who viewed a listing.
- **Property of the Day**: on the first time you use the app on a given calendar day in your timezone, we may show a one-time highlight. We store that an impression was shown (user identifier, local date, and the featured property id) so the popup does not repeat that day.
- **Usage data**: properties you analyze and any values you save to your Knowledge Base.
- **Generated outputs**: AI summaries, forecasts, and simulated quantum alignment scores.

We do **not** sell personal information.

#### 3) How we use data
We use your data to:
- authenticate you and protect your Knowledge Base,
- generate analyses you request,
- store properties you save for later retrieval,
- understand which pages and features are most used so we can improve the product,
- count unique listing views so we can show popularity to signed-in users,
- choose and display a daily Property of the Day highlight (positive cash flow, lower simulated risk, and a stronger neighborhood score when available).

The site operator (admin) can review usage in aggregate (most popular pages and actions) and as an activity feed tied to an account identifier (email or demo username).

#### 4) Sharing
We may share data with:
- **Supabase** (database and authentication provider),
- **AI model providers** used for analysis (only the inputs needed to produce the requested output).

#### 5) Security and retention
We apply reasonable security practices; however, no system is perfectly secure. Your saved Knowledge Base entries are retained until you delete them (or delete your account) or we retire the service. Usage analytics, listing viewership records, and Property of the Day impressions are retained to support product improvement until you delete your account or we retire the service.

#### 6) Your choices
You can stop using the app at any time. To remove your account and associated app data, use **Account settings → Delete account** in the app. Deletion is self-service; you do not need to contact the operator. Google-only accounts may need to set a password in Account settings before deletion can complete.

#### 7) Children
The app is not directed to children under 13, and we do not knowingly collect their personal information.

#### 8) Changes
We may update this policy. Material changes are reflected by updating the effective date above. When the Privacy Policy or Terms of Service change, signed-in users who previously accepted an older version will see an in-app notice and must agree to the updated documents before continuing to use the rest of the app. The current policy is always available on this page.

#### 9) Contact
Privacy questions may be directed to the operator of this portfolio project.`

export function bundledLegalDocument(slug: 'terms' | 'privacy'): BundledLegalDocument {
  if (slug === 'privacy') {
    return {
      title: 'Privacy Policy',
      body: PRIVACY_BODY,
      effective_date: LEGAL_DEFAULT_EFFECTIVE_DATE,
    }
  }
  return {
    title: 'Terms of Service',
    body: TERMS_BODY,
    effective_date: LEGAL_DEFAULT_EFFECTIVE_DATE,
  }
}
