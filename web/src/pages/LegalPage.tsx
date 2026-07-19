import { Link, useParams } from 'react-router-dom'

const TERMS = `### Terms of Service

**Effective date:** 2025-06-09

#### 1) Agreement
By creating an account or using CapEigen, you agree to these Terms of Service. If you do not agree, do not use the app.

#### 2) What this app is
CapEigen is an AI-assisted, educational real-estate analysis tool. It may generate estimates, summaries, and QAOA quantum alignment scores based on user inputs and third-party information. It is **not** a broker, lender, appraiser, tax advisor, or financial advisor.

#### 3) Educational use only
Outputs are for learning and research. They are **not** investment, legal, tax, or lending advice. You are responsible for your own due diligence before any real-estate decision.

#### 4) AI and quantum simulation disclosure
The app may display **quantum-probabilistic scores** or similar risk-style outputs. These are **simulations** derived from mathematical transforms of user inputs and/or model outputs. They are **not guarantees** and must not be interpreted as predictions of future performance.`

const PRIVACY = `### Privacy Policy

**Effective date:** 2025-06-09

#### 1) What we collect
Account information (email), authentication tokens via Supabase, property analyses you run, and assumption overrides you save.

#### 2) How we use data
To provide underwriting analysis, improve the product, and secure your account.

#### 3) Sharing
We use Supabase for auth/database and Google Gemini for property research. We do not sell personal data.

#### 4) Contact
Use in-app support channels for privacy questions.`

export function LegalPage() {
  const { doc } = useParams()
  const isPrivacy = doc === 'privacy'
  const body = isPrivacy ? PRIVACY : TERMS
  const title = isPrivacy ? 'Privacy Policy' : 'Terms of Service'

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <Link to="/login" className="text-sm text-primary hover:underline">
        ← Back to login
      </Link>
      <h1 className="mt-4 font-display text-3xl font-semibold">{title}</h1>
      <article className="prose prose-sm mt-6 whitespace-pre-wrap text-text/90">{body}</article>
    </div>
  )
}
