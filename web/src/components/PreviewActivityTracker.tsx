import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuthStore } from '../lib/authStore'
import { isPreviewUser, trackPreviewEvent } from '../lib/previewActivity'

export function PreviewActivityTracker() {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)

  useEffect(() => {
    if (!isPreviewUser(user)) return
    const page =
      location.pathname === '/'
        ? 'Home'
        : location.pathname.replace(/^\//, '').replace(/\b\w/g, (c) => c.toUpperCase())
    trackPreviewEvent('page_view', {
      path: `${location.pathname}${location.search}`,
      label: page,
      payload: { search: location.search },
    })
  }, [location.pathname, location.search, user])

  return null
}
