/** Auto sign-out after this much continuous inactivity. */
export const IDLE_TIMEOUT_MS = 10 * 60 * 1000

/** sessionStorage flag so LoginPage can show a one-shot notice after idle logout. */
export const IDLE_LOGOUT_NOTICE_KEY = 'capeigen_idle_logout'

export const IDLE_LOGOUT_MESSAGE =
  "You've been logged out. Please sign in again to continue using the app."

export function markIdleLogoutNotice(): void {
  try {
    sessionStorage.setItem(IDLE_LOGOUT_NOTICE_KEY, '1')
  } catch {
    // Private mode / blocked storage — notice is best-effort.
  }
}

export function consumeIdleLogoutNotice(): boolean {
  try {
    if (sessionStorage.getItem(IDLE_LOGOUT_NOTICE_KEY) !== '1') return false
    sessionStorage.removeItem(IDLE_LOGOUT_NOTICE_KEY)
    return true
  } catch {
    return false
  }
}
