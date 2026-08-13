import { getGoogleClientId, generateGoogleNonce } from './googleGis'

const NONCE_KEY = 'capeigen_google_oauth_nonce'
const STATE_KEY = 'capeigen_google_oauth_state'

export function googleOAuthRedirectUri(): string {
  return `${window.location.origin}/auth/google/callback`
}

/** Start Google OIDC on *our* domain so the account chooser shows CapEigen, not supabase.co. */
export async function startGoogleOAuthRedirect(): Promise<void> {
  const clientId = getGoogleClientId()
  if (!clientId) {
    throw new Error('Set VITE_GOOGLE_CLIENT_ID to your Google Web client ID.')
  }

  const { nonce } = await generateGoogleNonce()
  const state = crypto.randomUUID()
  sessionStorage.setItem(NONCE_KEY, nonce)
  sessionStorage.setItem(STATE_KEY, state)

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: googleOAuthRedirectUri(),
    response_type: 'id_token',
    response_mode: 'fragment',
    scope: 'openid email profile',
    nonce,
    state,
    prompt: 'select_account',
  })

  window.location.assign(`https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`)
}

export function readGoogleOAuthCallback(): {
  idToken: string
  nonce: string
} {
  const hash = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash
  const params = new URLSearchParams(hash)
  const error = params.get('error')
  if (error) {
    throw new Error(params.get('error_description') || error)
  }

  const idToken = params.get('id_token')
  if (!idToken) {
    throw new Error('Google did not return an ID token. Check Authorized redirect URIs.')
  }

  const state = params.get('state')
  const expectedState = sessionStorage.getItem(STATE_KEY)
  if (!expectedState || state !== expectedState) {
    throw new Error('Invalid OAuth state. Try signing in again.')
  }

  const nonce = sessionStorage.getItem(NONCE_KEY)
  if (!nonce) {
    throw new Error('Missing sign-in nonce. Try signing in again.')
  }

  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(NONCE_KEY)
  return { idToken, nonce }
}
