import { Navigate, Outlet, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { useEffect } from 'react'
import { isAdminUser } from './lib/admin'
import { useAuthStore } from './lib/authStore'
import { AppLayout } from './components/AppLayout'
import { PreviewActivityTracker } from './components/PreviewActivityTracker'
import { LoginPage } from './pages/LoginPage'
import { GoogleCallbackPage } from './pages/GoogleCallbackPage'
import { HomePage } from './pages/HomePage'
import { SearchPage } from './pages/SearchPage'
import { ComparePage } from './pages/ComparePage'
import { ValidationPage } from './pages/ValidationPage'
import { LegalPage } from './pages/LegalPage'
import { GuestSharePage } from './pages/GuestSharePage'
import { ActivityPage } from './pages/ActivityPage'
import { UsagePage } from './pages/UsagePage'
import { LegalAdminPage } from './pages/LegalAdminPage'

function RequireAuth() {
  const { session, loading } = useAuthStore()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted">
        Loading CapEigen…
      </div>
    )
  }
  if (!session) return <Navigate to="/login" replace />
  return <Outlet />
}

function RequireAdmin() {
  const { user, loading } = useAuthStore()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted">
        Loading CapEigen…
      </div>
    )
  }
  if (!isAdminUser(user)) return <Navigate to="/" replace />
  return <Outlet />
}

/** Legacy outreach URLs used `?share=token`; send those guests to the share page. */
function ShareQueryRedirect() {
  const [params] = useSearchParams()
  const location = useLocation()
  const token = params.get('share')?.trim()
  if (token && !location.pathname.startsWith('/share/')) {
    return <Navigate to={`/share/${encodeURIComponent(token)}`} replace />
  }
  return null
}

export default function App() {
  const init = useAuthStore((s) => s.init)

  useEffect(() => {
    void init()
  }, [init])

  return (
    <>
      <ShareQueryRedirect />
      <PreviewActivityTracker />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/google/callback" element={<GoogleCallbackPage />} />
        <Route path="/legal/:doc" element={<LegalPage />} />
        <Route path="/share/:token" element={<GuestSharePage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route index element={<HomePage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route element={<RequireAdmin />}>
              <Route path="validation" element={<ValidationPage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="usage" element={<UsagePage />} />
              <Route path="legal-admin" element={<LegalAdminPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
