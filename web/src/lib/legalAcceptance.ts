import { apiFetch } from './api'

export type LegalAcceptanceStatus = {
  needs_acceptance: boolean
  privacy_effective_date: string
  terms_effective_date: string
  accepted_privacy_effective_date?: string | null
  accepted_terms_effective_date?: string | null
  accepted_at?: string | null
  privacy_title?: string
  terms_title?: string
}

export async function fetchLegalAcceptanceStatus(): Promise<LegalAcceptanceStatus> {
  return apiFetch<LegalAcceptanceStatus>('/api/legal/acceptance')
}

export async function acceptCurrentLegalDocuments(): Promise<LegalAcceptanceStatus> {
  return apiFetch<LegalAcceptanceStatus>('/api/legal/acceptance', {
    method: 'POST',
    body: JSON.stringify({ accepted: true }),
  })
}

/** Best-effort record after signup/preview when the user already checked the box. */
export async function recordLegalAcceptanceQuietly(): Promise<void> {
  try {
    await acceptCurrentLegalDocuments()
  } catch {
    // Modal will prompt on next app load if this fails.
  }
}
