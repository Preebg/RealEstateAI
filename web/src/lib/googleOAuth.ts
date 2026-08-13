import { getGoogleClientId, generateGoogleNonce } from './googleGis'

const NONCE_KEY = 'capeigen_google_oauth_nonce'
const STATE_KEY = 'capeigen_google_oauth_state'
const VERIFIER_KEY = 'capeigen_google_oauth_verifier'

export function googleOAuthRedirectUri(): string {
  return `${window.location.origin}/auth/google/callback`
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]!)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function generateCodeVerifier(): string {
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)).buffer)
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64UrlEncode(digest)
}

/** Start Google OAuth on CapEigen (authorization code + PKCE). No Supabase redirect URI. */
export async function startGoogleOAuthRedirect(): Promise<void> {
  const clientId = getGoogleClientId()
  if (!clientId) {
    throw new Error('Set VITE_GOOGLE_CLIENT_ID to your Google Web client ID.')
  }

  const { nonce } = await generateGoogleNonce()
  const state = crypto.randomUUID()
  const verifier = generateCodeVerifier()
  const challenge = await generateCodeChallenge(verifier)

  sessionStorage.setItem(NONCE_KEY, nonce)
  sessionStorage.setItem(STATE_KEY, state)
  sessionStorage.setItem(VERIFIER_KEY, verifier)

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: googleOAuthRedirectUri(),
    response_type: 'code',
    scope: 'openid email profile',
    state,
    nonce,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    prompt: 'select_account',
    access_type: 'online',
  })

  window.location.assign(`https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`)
}

export type GoogleOAuthCallbackParts = {
  code: string
  codeVerifier: string
  nonce: string
  redirectUri: string
}

/** Read `?code=` from the CapEigen callback and pair it with the stored PKCE verifier. */
export function readGoogleOAuthCallback(): GoogleOAuthCallbackParts {
  const params = new URLSearchParams(window.location.search)
  const error = params.get('error')
  if (error) {
    throw new Error(params.get('error_description') || error)
  }

  const code = params.get('code')
  if (!code) {
    throw new Error(
      'Google did not return an authorization code. Add this exact redirect URI in Google Cloud: ' +
        googleOAuthRedirectUri(),
    )
  }

  const state = params.get('state')
  const expectedState = sessionStorage.getItem(STATE_KEY)
  if (!expectedState || state !== expectedState) {
    throw new Error('Invalid OAuth state. Try signing in again.')
  }

  const nonce = sessionStorage.getItem(NONCE_KEY)
  const codeVerifier = sessionStorage.getItem(VERIFIER_KEY)
  if (!nonce || !codeVerifier) {
    throw new Error('Missing sign-in session data. Try signing in again.')
  }

  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(NONCE_KEY)
  sessionStorage.removeItem(VERIFIER_KEY)

  return {
    code,
    codeVerifier,
    nonce,
    redirectUri: googleOAuthRedirectUri(),
  }
}

/** CapEigen token exchange — Netlify rewrites this to the google-token function in prod. */
function googleExchangeEndpoint(): string {
  return '/api/auth/google/exchange'
}

/** Exchange the auth code via CapEigen backend (FastAPI locally / Netlify function in prod). */
export async function exchangeGoogleAuthCode(parts: GoogleOAuthCallbackParts): Promise<string> {
  const res = await fetch(googleExchangeEndpoint(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code: parts.code,
      code_verifier: parts.codeVerifier,
      redirect_uri: parts.redirectUri,
    }),
  })

  const raw = await res.text()
  let payload: { id_token?: string; detail?: unknown } = {}
  try {
    payload = raw ? (JSON.parse(raw) as { id_token?: string; detail?: unknown }) : {}
  } catch {
    throw new Error(
      `Google token exchange failed (HTTP ${res.status}). ` +
        'Redeploy Netlify with the google-token function and set GOOGLE_WEB_CLIENT_SECRET.',
    )
  }

  if (!res.ok) {
    const detail =
      typeof payload.detail === 'string'
        ? payload.detail
        : `Google token exchange failed (HTTP ${res.status}).`
    throw new Error(detail)
  }

  if (!payload.id_token) {
    throw new Error('Token exchange did not return an id_token')
  }

  return payload.id_token
}
