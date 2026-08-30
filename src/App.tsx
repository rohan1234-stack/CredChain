import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { Settings, User as UserIcon } from 'lucide-react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ProtectedRoute } from './components/auth/ProtectedRoute'
import { ToastProvider } from './components/ui/Toast'
import { Login } from './portals/auth/Login'
import { Landing } from './portals/auth/Landing'
import { SignUp } from './portals/auth/SignUp'
import { AppShell } from './components/layout/AppShell'
import { RoleSwitcher } from './components/layout/RoleSwitcher'
import { Stub } from './components/Stub'
import type { User as FrontendUser, AuthUser, Role } from './types'

// Student
import { StudentDashboard } from './portals/student/Dashboard'
import { CredentialsList } from './portals/student/CredentialsList'
import { CredentialDetail } from './portals/student/CredentialDetail'
import { Jobs as StudentJobs } from './portals/student/Jobs'
import { JobDetail } from './portals/student/JobDetail'
import { MyApplications } from './portals/student/MyApplications'
import { Companies } from './portals/student/Companies'
import { CompanyDetail } from './portals/student/CompanyDetail'
import { Institutions } from './portals/student/Institutions'
import { InstitutionDetail } from './portals/student/InstitutionDetail'
import { Requests } from './portals/student/Requests'
import { ShareFlow } from './portals/student/ShareFlow'
import { ShareConfirmation } from './portals/student/ShareConfirmation'
import { Shares } from './portals/student/Shares'
import { Activity as StudentActivity } from './portals/student/Activity'
import { CertificateRequests as StudentCertificateRequests } from './portals/student/CertificateRequests'
import { Documents as StudentDocuments } from './portals/student/Documents'

// Public (no auth required)
import { ShareAccess } from './portals/shared/ShareAccess'

// Shared across every authenticated portal
import { Notifications } from './portals/shared/Notifications'

// Institution
import { InstitutionDashboard } from './portals/institution/Dashboard'
import { Students } from './portals/institution/Students'
import { InstitutionCredentialsList } from './portals/institution/CredentialsList'
import { IssueCredential } from './portals/institution/IssueCredential'
import { CredentialIssued } from './portals/institution/CredentialIssued'
import { InstitutionRequests } from './portals/institution/Requests'
import { InstitutionActivity } from './portals/institution/Activity'
import { InstitutionCertificateRequests } from './portals/institution/CertificateRequests'
import { DocumentReview } from './portals/institution/DocumentReview'

// Verifier
import { VerifierDashboard } from './portals/verifier/Dashboard'
import { VerifierRequests } from './portals/verifier/Requests'
import { VerificationResult } from './portals/verifier/VerificationResult'
import { RequestCredentials } from './portals/verifier/RequestCredentials'
import { VerifierActivity } from './portals/verifier/Activity'
import { Profile as CompanyProfile } from './portals/verifier/Profile'
import { Jobs as CompanyJobs } from './portals/verifier/Jobs'
import { Applications as CompanyApplications } from './portals/verifier/Applications'

// Admin
import { AdminDashboard } from './portals/admin/Dashboard'

const ROLE_HOME: Record<Role, string> = {
  student: '/student',
  institution: '/institution',
  verifier: '/verifier',
  admin: '/admin',
}

/** Maps the backend's AuthUser (types.ts) onto the frontend's display User shape (types.ts) that AppShell/Sidebar/TopBar already expect. */
function toDisplayUser(authUser: AuthUser): FrontendUser {
  const initials =
    authUser.full_name
      .split(' ')
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase() || '?'

  return {
    id: authUser.id,
    name: authUser.full_name,
    initials,
    role: authUser.role,
    orgName: authUser.org_name ?? undefined,
  }
}

function StudentLayout() {
  const { user } = useAuth()
  return (
    <AppShell user={toDisplayUser(user!)}>
      <Outlet />
    </AppShell>
  )
}
function InstitutionLayout() {
  const { user } = useAuth()
  return (
    <AppShell user={toDisplayUser(user!)}>
      <Outlet />
    </AppShell>
  )
}
function VerifierLayout() {
  const { user } = useAuth()
  return (
    <AppShell user={toDisplayUser(user!)}>
      <Outlet />
    </AppShell>
  )
}
function AdminLayout() {
  const { user } = useAuth()
  return (
    <AppShell user={toDisplayUser(user!)}>
      <Outlet />
    </AppShell>
  )
}

/** Root ("/"): an authenticated user goes straight to their own dashboard; everyone else sees the public landing page. */
function RootRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (user) return <Navigate to={ROLE_HOME[user.role]} replace />
  return <Landing />
}

/** Unknown paths: send an authenticated user to their own dashboard, everyone else to sign-in. */
function RootRedirect() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? ROLE_HOME[user.role] : '/sign-in'} replace />
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RootRoute />} />
      <Route path="/sign-in" element={<Login />} />
      <Route path="/login" element={<Login />} />
      <Route path="/sign-up" element={<SignUp />} />
      <Route path="/share/verify/:token" element={<ShareAccess />} />

      <Route element={<ProtectedRoute role="student" />}>
        <Route path="/student" element={<StudentLayout />}>
          <Route index element={<StudentDashboard />} />
          <Route path="credentials" element={<CredentialsList />} />
          <Route path="credentials/:id" element={<CredentialDetail />} />
          <Route path="jobs" element={<StudentJobs />} />
          <Route path="jobs/:id" element={<JobDetail />} />
          <Route path="my-applications" element={<MyApplications />} />
          <Route path="institutions" element={<Institutions />} />
          <Route path="institutions/:id" element={<InstitutionDetail />} />
          <Route path="companies" element={<Companies />} />
          <Route path="companies/:id" element={<CompanyDetail />} />
          <Route path="requests" element={<Requests />} />
          <Route path="certificate-requests" element={<StudentCertificateRequests />} />
          <Route path="documents" element={<StudentDocuments />} />
          <Route path="share" element={<ShareFlow />} />
          <Route path="share/confirmation" element={<ShareConfirmation />} />
          <Route path="shares" element={<Shares />} />
          <Route path="activity" element={<StudentActivity />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="settings" element={<Stub icon={Settings} title="Settings" description="Account and notification settings are not part of this prototype." />} />
          <Route path="profile" element={<Stub icon={UserIcon} title="Profile" description="Profile management is not part of this prototype." />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute role="institution" />}>
        <Route path="/institution" element={<InstitutionLayout />}>
          <Route index element={<InstitutionDashboard />} />
          <Route path="students" element={<Students />} />
          <Route path="credentials" element={<InstitutionCredentialsList />} />
          <Route path="credentials/issue" element={<IssueCredential />} />
          <Route path="credentials/issued" element={<CredentialIssued />} />
          <Route path="requests" element={<InstitutionRequests />} />
          <Route path="certificate-requests" element={<InstitutionCertificateRequests />} />
          <Route path="documents" element={<DocumentReview />} />
          <Route path="activity" element={<InstitutionActivity />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="settings" element={<Stub icon={Settings} title="Settings" description="Institution account settings are not part of this prototype." />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute role="verifier" />}>
        <Route path="/verifier" element={<VerifierLayout />}>
          <Route index element={<VerifierDashboard />} />
          <Route path="profile" element={<CompanyProfile />} />
          <Route path="jobs" element={<CompanyJobs />} />
          <Route path="applications" element={<CompanyApplications />} />
          <Route path="requests" element={<VerifierRequests />} />
          <Route path="requests/new" element={<RequestCredentials />} />
          <Route path="verify/:credentialId" element={<VerificationResult />} />
          <Route path="activity" element={<VerifierActivity />} />
          <Route path="notifications" element={<Notifications />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute role="admin" />}>
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminDashboard />} />
          <Route path="notifications" element={<Notifications />} />
        </Route>
      </Route>

      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <AppRoutes />
          {/* Dev-only route-jump shortcut — never grants a session. See RoleSwitcher.tsx. */}
          {import.meta.env.DEV && <RoleSwitcher />}
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
