import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate, Link } from 'react-router-dom'
import { ShieldCheck, Mail, KeyRound } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { ApiError } from '../../lib/apiClient'
import { Button } from '../../components/ui'
import type { Role } from '../../types'

const ROLE_HOME: Record<Role, string> = {
  student: '/student',
  institution: '/institution',
  verifier: '/verifier',
  admin: '/admin',
}

/**
 * Reproduces the actual Stitch "credchain_cinematic_auth_portal" screen: a
 * single centered column (not a split-screen) over an ambient pulsing glow,
 * with a centered logo/tagline header above a glass-panel-3d card holding
 * "recessed" icon-prefixed inputs and a gradient 3D button — see
 * stitch1/credchain_cinematic_auth_portal/code.html. Stitch's own reference
 * screen has a role switcher here because it doubles as the sign-up/role
 * picker; this page only ever signs in an existing account of any role
 * (real behavior, unchanged), so there's no role switcher to reproduce —
 * Stitch's "Wallet Address / Email" + "Cryptographic Key" fields map onto
 * the real email/password fields, and "Connect Web3 Wallet" is dropped
 * entirely since CredChain has no wallet-auth capability to back it.
 */
export function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Already signed in (e.g. navigated back to /login manually) — bounce to
  // wherever they were headed, or their own dashboard.
  if (user) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? ROLE_HOME[user.role]} replace />
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const loggedInUser = await login(email, password)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? ROLE_HOME[loggedInUser.role], { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 0) setError('Server unavailable. Please try again in a moment.')
        else if (err.status === 403) setError('Your account is inactive. Contact your administrator.')
        else setError('Invalid email or password.')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-canvas px-5">
      {/* Stitch: a centered ambient glow pulse behind the whole panel */}
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="h-[500px] w-[500px] rounded-full bg-cyan/25 blur-[100px] motion-safe:animate-[glowPulse_4s_ease-in-out_infinite]" />
      </div>
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-grid-faint opacity-[0.05]" />

      <main className="relative z-10 flex w-full max-w-md flex-col items-center py-16">
        <div className="mb-10 flex flex-col items-center text-center">
          <h1 className="flex items-center justify-center gap-2 text-[32px] font-bold tracking-tight text-primary drop-shadow-[0_0_15px_rgba(79,70,229,0.4)] font-[family-name:var(--font-display)]">
            <ShieldCheck className="h-9 w-9" strokeWidth={2.25} />
            CredChain
          </h1>
          <p className="mt-2 text-base tracking-wide text-cyan opacity-80">Secure Academic Verification</p>
        </div>

        <div className="glass-surface w-full rounded-2xl p-6">
          <h2 className="mb-4 text-xl font-semibold text-ink">Sign In</h2>
          <p className="-mt-3 mb-5 text-[13px] text-muted">Student, institution, and verifier accounts all sign in here.</p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="email" className="ml-1 text-[11px] font-medium uppercase tracking-[0.1em] text-faint">
                Email
              </label>
              <div className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-4 py-3 shadow-[inset_0_4px_10px_rgba(0,0,0,0.5)] transition-colors focus-within:border-electric focus-within:shadow-[inset_0_4px_10px_rgba(0,0,0,0.5),0_0_20px_-6px_var(--color-electric)]">
                <Mail className="h-[20px] w-[20px] shrink-0 text-faint" strokeWidth={2} />
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint"
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="ml-1 text-[11px] font-medium uppercase tracking-[0.1em] text-faint">
                Password
              </label>
              <div className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-4 py-3 shadow-[inset_0_4px_10px_rgba(0,0,0,0.5)] transition-colors focus-within:border-electric focus-within:shadow-[inset_0_4px_10px_rgba(0,0,0,0.5),0_0_20px_-6px_var(--color-electric)]">
                <KeyRound className="h-[20px] w-[20px] shrink-0 text-faint" strokeWidth={2} />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  className="w-full bg-transparent text-sm tracking-[0.2em] text-ink outline-none placeholder:text-faint"
                />
              </div>
            </div>

            {error && (
              <div role="alert" className="rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">
                {error}
              </div>
            )}

            <Button type="submit" variant="solid" className="mt-2 w-full rounded-xl py-3.5 text-base" loading={submitting}>
              Sign In
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-muted">
          Don&rsquo;t have an account?{' '}
          <Link to="/sign-up" className="font-semibold text-primary hover:underline">
            Create one
          </Link>
        </p>
      </main>
    </div>
  )
}
