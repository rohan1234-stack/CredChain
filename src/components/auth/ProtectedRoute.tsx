// ---------------------------------------------------------------------------
// Frontend route guard. This is UX only — it prevents an unauthenticated or
// wrong-role user from ever rendering a portal's pages, but it is NOT the
// real security boundary. The backend enforces the actual authorization
// (require_student/require_institution/require_verifier on every protected
// endpoint) independently of anything this component does; a user who
// bypassed this guard entirely (e.g. by editing frontend state) would still
// get 401/403 from every real API call.
// ---------------------------------------------------------------------------

import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import type { Role } from '../../types'

const ROLE_HOME: Record<Role, string> = {
  student: '/student',
  institution: '/institution',
  verifier: '/verifier',
  admin: '/admin',
}

export function ProtectedRoute({ role }: { role: Role }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return null

  if (!user) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }

  if (user.role !== role) {
    // Authenticated, but wrong portal for this account — send them to the
    // dashboard their own role actually has, not to a login loop.
    return <Navigate to={ROLE_HOME[user.role]} replace />
  }

  return <Outlet />
}
