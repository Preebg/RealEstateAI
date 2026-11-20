import { useCallback, useState } from 'react'
import { isBackendOnline } from '../lib/serverAvailability'

/**
 * Gate sign-in / sign-up behind a live FastAPI health check.
 * Marketing pages stay reachable; login attempts open the contact-owner modal when offline.
 */
export function useBackendLoginGate(): {
  unavailableOpen: boolean
  dismissUnavailable: () => void
  ensureOnline: () => Promise<boolean>
} {
  const [unavailableOpen, setUnavailableOpen] = useState(false)

  const dismissUnavailable = useCallback(() => {
    setUnavailableOpen(false)
  }, [])

  const ensureOnline = useCallback(async (): Promise<boolean> => {
    if (await isBackendOnline()) return true
    setUnavailableOpen(true)
    return false
  }, [])

  return { unavailableOpen, dismissUnavailable, ensureOnline }
}
