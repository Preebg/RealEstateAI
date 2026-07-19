import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuthStore } from './lib/authStore'
import { AppLayout } from './components/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { HomePage } from './pages/HomePage'
import { SearchPage } from './pages/SearchPage'
import { ComparePage } from './pages/ComparePage'
import { ValidationPage } from './pages/ValidationPage'
import { LegalPage } from './pages/LegalPage'
import { GuestSharePage } from './pages/GuestSharePage'

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

export default function App() {
  const init = useAuthStore((s) => s.init)

  useEffect(() => {
    void init()
  }, [init])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/legal/:doc" element={<LegalPage />} />
      <Route path="/share/:token" element={<GuestSharePage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="validation" element={<ValidationPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
