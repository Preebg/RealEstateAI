import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../lib/authStore'
import {
  IDLE_TIMEOUT_MS,
  markIdleLogoutNotice,
} from '../lib/idleSession'
import { trackPreviewEvent } from '../lib/previewActivity'

const ACTIVITY_EVENTS = [
  'mousedown',
  'mousemove',
  'keydown',
  'touchstart',
  'scroll',
  'click',
  'wheel',
] as const

const ACTIVITY_THROTTLE_MS = 1000

/**
 * Signs the user out after {@link IDLE_TIMEOUT_MS} with no pointer/keyboard activity.
 */
export function IdleSessionGuard() {
  const session = useAuthStore((s) => s.session)
  const signOut = useAuthStore((s) => s.signOut)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastActivityRef = useRef(0)

  useEffect(() => {
    if (!session) return

    const clearTimer = () => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }

    const scheduleLogout = () => {
      clearTimer()
      timerRef.current = setTimeout(() => {
        void (async () => {
          markIdleLogoutNotice()
          trackPreviewEvent('sign_out', {
            path: '/login',
            label: 'Idle timeout',
          })
          await signOut()
          queryClient.clear()
          navigate('/login', { replace: true })
        })()
      }, IDLE_TIMEOUT_MS)
    }

    const onActivity = () => {
      const now = Date.now()
      if (now - lastActivityRef.current < ACTIVITY_THROTTLE_MS) return
      lastActivityRef.current = now
      scheduleLogout()
    }

    scheduleLogout()
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true })
    }

    return () => {
      clearTimer()
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, onActivity)
      }
    }
  }, [session, signOut, navigate, queryClient])

  return null
}
