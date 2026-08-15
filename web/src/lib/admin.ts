import type { User } from '@supabase/supabase-js'

/** Only this account may see Model Validation, usage, legal, and the demo-account dashboard. */
export const ADMIN_EMAIL = 'preebg09@gmail.com'

export function isAdminEmail(email: string | null | undefined): boolean {
  return (email || '').trim().toLowerCase() === ADMIN_EMAIL
}

export function isAdminUser(user: User | null | undefined): boolean {
  if (isAdminEmail(user?.email)) return true
  const identities = user?.identities ?? []
  return identities.some((identity) => {
    const data = identity.identity_data
    const identityEmail =
      data && typeof data === 'object' && 'email' in data ? data.email : undefined
    return typeof identityEmail === 'string' && isAdminEmail(identityEmail)
  })
}
