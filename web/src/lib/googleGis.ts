/** Google Identity Services (GIS) helpers — ID token sign-in on our domain. */

const GIS_SRC = 'https://accounts.google.com/gsi/client'

export type GoogleCredentialResponse = {
  credential: string
  select_by?: string
}

type GoogleAccountsId = {
  initialize: (config: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
    nonce?: string
    context?: string
    ux_mode?: 'popup' | 'redirect'
    use_fedcm_for_prompt?: boolean
  }) => void
  renderButton: (
    parent: HTMLElement,
    config: {
      type?: string
      theme?: string
      size?: string
      text?: string
      shape?: string
      width?: number
      logo_alignment?: string
    },
  ) => void
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } }
  }
}

export function getGoogleClientId(): string | undefined {
  const id = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined
  return id?.trim() || undefined
}

export function loadGoogleIdentityScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()

  const existing = document.querySelector<HTMLScriptElement>(`script[src="${GIS_SRC}"]`)
  if (existing) {
    return new Promise((resolve, reject) => {
      if (window.google?.accounts?.id) {
        resolve()
        return
      }
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener(
        'error',
        () => reject(new Error('Failed to load Google Identity Services')),
        { once: true },
      )
    })
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = GIS_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Google Identity Services'))
    document.head.appendChild(script)
  })
}

export async function generateGoogleNonce(): Promise<{ nonce: string; hashedNonce: string }> {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  const nonce = btoa(String.fromCharCode(...bytes))
  const hashBuffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(nonce))
  const hashedNonce = Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
  return { nonce, hashedNonce }
}
