import { Navigate, Outlet, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import { isAdminUser } from './lib/admin'
import { useAuthStore } from './lib/authStore'
import { AppLayout } from './components/AppLayout'
import { IdleSessionGuard } from './components/IdleSessionGuard'
import { PreviewActivityTracker } from './components/PreviewActivityTracker'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { GoogleCallbackPage } from './pages/GoogleCallbackPage'
import { SearchPage } from './pages/SearchPage'
import { ComparePage } from './pages/ComparePage'
import { ValidationPage } from './pages/ValidationPage'
import { LegalPage } from './pages/LegalPage'
import { GuestSharePage } from './pages/GuestSharePage'
import { ActivityPage } from './pages/ActivityPage'
import { UsagePage } from './pages/UsagePage'
import { LegalAdminPage } from './pages/LegalAdminPage'

const HomePage = lazy(() =>
  import('./pages/HomePage').then((m) => ({ default: m.HomePage })),
)

function HomeFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-muted">
      Loading portfolio…
    </div>
  )
}

function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center text-muted">
      Loading CapEigen…
    </div>
  )
}

/**
 * Guests on `/` see the marketing landing.
 * Other app routes require a session (redirect to login).
 * Signed-in users continue into the app shell.
 */
function GuestOrApp() {
  const { session, loading } = useAuthStore()
  const location = useLocation()
  if (loading) return <AuthLoading />
  if (!session) {
    if (location.pathname === '/') return <LandingPage />
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

function RequireAdmin() {
  const { user, loading } = useAuthStore()
  if (loading) return <AuthLoading />
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
      <IdleSessionGuard />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/google/callback" element={<GoogleCallbackPage />} />
        <Route path="/legal/:doc" element={<LegalPage />} />
        <Route path="/share/:token" element={<GuestSharePage />} />
        <Route element={<GuestOrApp />}>
          <Route element={<AppLayout />}>
            <Route
              index
              element={
                <Suspense fallback={<HomeFallback />}>
                  <HomePage />
                </Suspense>
              }
            />
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
