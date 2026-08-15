import { apiFetch } from './api'
import { supabase } from './supabase'
import type { User } from '@supabase/supabase-js'

export type PreviewEventType =
  | 'login'
  | 'page_view'
  | 'analyze'
  | 'compare'
  | 'pdf'
  | 'share'
  | 'bookmark'
  | 'assumption_change'
  | 'sign_out'

function previewMeta(user: User | null): { preview?: boolean; username?: string } {
  const app = user?.app_metadata as { preview?: boolean; username?: string } | undefined
  return app || {}
}

export function isPreviewUser(user: User | null): boolean {
  if (!user) return false
  if (previewMeta(user).preview) return true
  return (user.email || '').toLowerCase().endsWith('@demo.capeigen.app')
}

export function trackPreviewEvent(
  eventType: PreviewEventType,
  details?: { path?: string; label?: string; payload?: Record<string, unknown> },
): void {
  void (async () => {
    const { data } = await supabase.auth.getSession()
    if (!data.session) return
    await apiFetch('/api/preview/events', {
      method: 'POST',
      body: JSON.stringify({
        event_type: eventType,
        path: details?.path ?? window.location.pathname,
        label: details?.label,
        payload: details?.payload ?? {},
      }),
    })
  })().catch(() => {
    // Tracking must never block the product UI.
  })
}

const debounceTimers = new Map<string, number>()

export function trackPreviewEventDebounced(
  key: string,
  eventType: PreviewEventType,
  details?: { path?: string; label?: string; payload?: Record<string, unknown> },
  waitMs = 1500,
): void {
  const previous = debounceTimers.get(key)
  if (previous) window.clearTimeout(previous)
  const timer = window.setTimeout(() => {
    debounceTimers.delete(key)
    trackPreviewEvent(eventType, details)
  }, waitMs)
  debounceTimers.set(key, timer)
}
