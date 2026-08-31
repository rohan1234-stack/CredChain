import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate, Link } from 'react-router-dom'
import { ShieldCheck, Search, Mail, KeyRound, User, Check } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { ApiError } from '../../lib/apiClient'
import { getInstitutionsPage, getInstitution, getCompaniesPage, getRealCompany } from '../../lib/api'
import { Button, RoleBackground, CredentialCard3D } from '../../components/ui'
import type { Role, RegisterPayload, InstitutionSummary, Company } from '../../types'
import { cx } from '../../lib/utils'

/** Small, focused picker page size — a signup picker should show a short, relevant list, never
 * the ~100-row "give me the whole pick-list" page the direct-share company picker or the legacy
 * getInstitutions()/getRealCompanies() callers still intentionally use elsewhere. */
const ORG_PICKER_PAGE_SIZE = 8

const ROLE_HOME: Record<Role, string> = {
  student: '/student',
  institution: '/institution',
  verifier: '/verifier',
  admin: '/admin',
}

// No 'admin' tab here — there is no public admin sign-up path (see backend
// auth_service.register_user, which rejects role=admin regardless of what any client sends).
const ROLE_TABS: { role: Role; label: string }[] = [
  { role: 'student', label: 'Student' },
  { role: 'institution', label: 'Institution' },
  { role: 'verifier', label: 'Company' },
]

const WORLD_COPY: Record<Role, { headline: string; sub: string }> = {
  student: { headline: 'Your academic identity belongs to you.', sub: 'Every credential you receive lands directly in your own wallet — you decide what gets shared, with whom, and for how long.' },
  institution: { headline: 'Issue credentials people can trust.', sub: 'Sign transcripts, degrees, and certificates with your institution’s own key — every issuance is auditable and tamper-evident.' },
  verifier: { headline: 'Verify talent with confidence.', sub: 'Check a candidate’s real, signed academic record in seconds — no phone calls, no waiting on a registrar.' },
  // Unreachable — role is always one of ROLE_TABS above — but Record<Role, ...> requires every
  // key for type-safety. Never rendered.
  admin: { headline: '', sub: '' },
}

/**
 * Reproduces the actual Stitch "credchain_cinematic_auth_portal" screen: a
 * centered logo/tagline header, a pill-shaped "tactile switch" role selector,
 * and one glass-panel-3d "Access Portal" card with icon-prefixed recessed
 * inputs — all in a single view, not a two-step "pick a card, then see a
 * form" flow (see stitch1/credchain_cinematic_auth_portal/code.html). `role`
 * now defaults to 'student' instead of being nullable, matching Stitch's
 * always-a-role-selected interaction model; `register()` and its payload
 * construction are unchanged. The real per-role background/CredentialCard3D
 * "world" pairing built in an earlier phase is kept (genuine, working
 * functionality Stitch's own single auth screen doesn't need to express,
 * since Stitch's reference is mobile-only and has no room for it) — restyled
 * to sit behind the same centered composition rather than a desktop split.
 *
 * Institution/company "signup" is a CLAIM on an existing canonical directory
 * record, never free-text creation of a new one (see auth_service.register_user):
 * both roles get the exact same debounced server-side search selector the
 * student role already used for its (optional) institution link, just
 * required instead of optional, and backed by the company directory too.
 * This is the actual fix for CredChain's duplicate-organization bug — a
 * student and an institution account meaning the same real "Aalto University"
 * now always resolve to the same Institution.id, because there is no other
 * way for an institution/verifier account to come into existence.
 */
export function SignUp() {
  const { user, register } = useAuth()
  const navigate = useNavigate()

  const [role, setRole] = useState<Role>('student')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [studentIdentifier, setStudentIdentifier] = useState('')

  const [institutionId, setInstitutionId] = useState('')
  const [companyId, setCompanyId] = useState('')

  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to={ROLE_HOME[user.role]} replace />

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)

    // Some browsers/password managers can visually fill a controlled input without firing
    // React's onChange, leaving that field's state stale even though the screen shows it
    // filled in. FormData reads each input's real, current DOM value regardless of how it got
    // there, so this catches that mismatch right before submit — a submit-time safety net, not
    // a replacement for the controlled inputs above, which stay the source of truth otherwise.
    const formValues = new FormData(e.currentTarget)
    const effectiveFullName = fullName || ((formValues.get('fullName') as string) ?? '')
    const effectiveEmail = email || ((formValues.get('email') as string) ?? '')
    const effectivePassword = password || ((formValues.get('password') as string) ?? '')
    const effectiveStudentIdentifier = studentIdentifier || ((formValues.get('studentIdentifier') as string) ?? '')
    if (effectiveFullName !== fullName) setFullName(effectiveFullName)
    if (effectiveEmail !== email) setEmail(effectiveEmail)
    if (effectivePassword !== password) setPassword(effectivePassword)
    if (effectiveStudentIdentifier !== studentIdentifier) setStudentIdentifier(effectiveStudentIdentifier)

    if (role === 'institution' && !institutionId) {
      setError('Select your institution from the directory to continue.')
      return
    }
    if (role === 'verifier' && !companyId) {
      setError('Select your company from the directory to continue.')
      return
    }

    setSubmitting(true)

    const payload: RegisterPayload = { email: effectiveEmail, password: effectivePassword, full_name: effectiveFullName, role }
    if (role === 'student') {
      payload.student_identifier = effectiveStudentIdentifier
      if (institutionId) payload.institution_id = institutionId
    }
    if (role === 'institution') {
      payload.institution_id = institutionId
    }
    if (role === 'verifier') {
      payload.company_id = companyId
    }

    try {
      let registeredUser
      try {
        registeredUser = await register(payload)
      } catch (err) {
        // A status-0 ApiError means fetch() itself never got a response — a one-off network
        // blip, not a real backend failure. One retry avoids a false "Server unavailable" for
        // an account creation attempt that would otherwise have succeeded a moment later.
        if (err instanceof ApiError && err.status === 0) {
          registeredUser = await register(payload)
        } else {
          throw err
        }
      }
      navigate(ROLE_HOME[registeredUser.role], { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        // 409 covers both "email already registered" and "this institution/company already has a
        // registered account" — the backend's detail text is already specific and safe to show
        // as-is (see routes/auth.py), so no need (or ability) to guess which one happened here.
        if (err.status === 0) setError('Server unavailable. Please try again in a moment.')
        else if (err.status === 409) setError(err.message)
        else if (err.status === 404) setError(err.message)
        else if (err.status === 422) {
          // apiClient only ever surfaces err.message as a plain string when the backend sent one
          // (see handleErrorAndAuth in apiClient.ts) — a raw FastAPI validation error array falls
          // back to the generic "Request failed (422)" there, never a stack trace or internal
          // detail, so it's always safe to show directly rather than always overwriting it.
          const fallback = 'Please check that all required fields are filled in correctly.'
          setError(err.message && err.message !== `Request failed (${err.status})` ? err.message : fallback)
        }
        else setError('Something went wrong. Please try again.')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const copy = WORLD_COPY[role]

  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-canvas px-5 py-16">
      <RoleBackground key={role} role={role} className="motion-safe:animate-[fadeIn_600ms_ease-out]" />
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-grid-faint opacity-[0.05]" />

      <main className="relative z-10 flex w-full max-w-lg flex-col items-center">
        <div className="mb-8 flex flex-col items-center text-center">
          <h1 className="flex items-center justify-center gap-2 text-[32px] font-bold tracking-tight text-primary drop-shadow-[0_0_15px_rgba(79,70,229,0.4)] font-[family-name:var(--font-display)]">
            <ShieldCheck className="h-9 w-9" strokeWidth={2.25} />
            CredChain
          </h1>
          <p className="mt-2 text-base tracking-wide text-cyan opacity-80">Create your account</p>
        </div>

        {/* Pill role switcher — Stitch's "tactile switch" */}
        <div className="mb-6 flex w-full rounded-full border border-line bg-canvas p-1 shadow-[inset_0_2px_5px_rgba(0,0,0,0.6)]">
          {ROLE_TABS.map((tab) => (
            <button
              key={tab.role}
              type="button"
              onClick={() => setRole(tab.role)}
              className={cx(
                'flex-1 rounded-full px-4 py-2 text-[13px] font-semibold transition-all duration-300',
                role === tab.role
                  ? 'bg-gradient-to-b from-cyan-bg to-transparent text-cyan shadow-[0_0_20px_-4px_var(--color-cyan)] [text-shadow:0_0_10px_rgba(76,215,246,0.6)]'
                  : 'text-faint hover:text-ink'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Access Portal card */}
        <div className="glass-surface w-full rounded-2xl p-8">
          <div className="mb-9 grid grid-cols-1 items-start gap-y-6 sm:grid-cols-[auto_1fr] sm:gap-x-6">
            <CredentialCard3D issuer={role === 'institution' ? 'Your Institution' : role === 'verifier' ? 'Talent Network' : 'VITC'} title={ROLE_TABS.find((t) => t.role === role)!.label} subtitle="CredChain account" size="sm" className="hidden sm:block" />
            <div className="min-w-0 sm:-mt-2 sm:border-l sm:border-line sm:pl-6">
              <h2 className="text-xl font-semibold text-ink">Access Portal</h2>
              <p className="text-[13px] leading-relaxed text-muted">{copy.headline}</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <RecessedField label={role === 'institution' || role === 'verifier' ? 'Contact Name' : 'Name'} icon={User}>
              <input name="fullName" type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} required autoComplete="name" className="w-full bg-transparent text-sm text-ink outline-none" />
            </RecessedField>

            <RecessedField label={role === 'institution' ? 'Official Email' : role === 'verifier' ? 'Business Email' : 'Email'} icon={Mail}>
              <input name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" className="w-full bg-transparent text-sm text-ink outline-none" />
            </RecessedField>

            <RecessedField label="Password" icon={KeyRound}>
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                className="w-full bg-transparent text-sm tracking-[0.2em] text-ink outline-none"
              />
            </RecessedField>

            {role === 'student' && (
              <>
                <RecessedField label="Student Identifier" icon={User}>
                  <input name="studentIdentifier" type="text" value={studentIdentifier} onChange={(e) => setStudentIdentifier(e.target.value)} required className="w-full bg-transparent text-sm text-ink outline-none" />
                </RecessedField>

                <OrgPicker<InstitutionSummary>
                  label="Institution (optional — link later)"
                  placeholder="Search institutions"
                  selectedId={institutionId}
                  onSelect={setInstitutionId}
                  fetchPage={(search) => getInstitutionsPage({ search: search || undefined, pageSize: ORG_PICKER_PAGE_SIZE })}
                  fetchById={getInstitution}
                  initialHint="Search for a university"
                  noResultsLabel={(q) => `No universities found for "${q}" — you can still create your account and link one later.`}
                  errorLabel="Couldn't load universities. Try again — you can still create your account and link one later."
                />
              </>
            )}

            {role === 'institution' && (
              <OrgPicker<InstitutionSummary>
                label="Institution"
                placeholder="Search institutions"
                selectedId={institutionId}
                onSelect={setInstitutionId}
                fetchPage={(search) => getInstitutionsPage({ search: search || undefined, pageSize: ORG_PICKER_PAGE_SIZE })}
                fetchById={getInstitution}
                initialHint="Search for a university"
                noResultsLabel={(q) => `No universities found for "${q}". Can't find your university? Contact an administrator to have it added to the directory.`}
                errorLabel="Couldn't load universities. Try again."
              />
            )}

            {role === 'verifier' && (
              <OrgPicker<Company>
                label="Company"
                placeholder="Search companies"
                selectedId={companyId}
                onSelect={setCompanyId}
                fetchPage={(search) => getCompaniesPage({ search: search || undefined, pageSize: ORG_PICKER_PAGE_SIZE })}
                fetchById={getRealCompany}
                initialHint="Search for a company"
                noResultsLabel={(q) => `No companies found for "${q}". Can't find your company? Contact an administrator to have it added to the directory.`}
                errorLabel="Couldn't load companies. Try again."
              />
            )}

            {error && (
              <div role="alert" className="rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">
                {error}
              </div>
            )}

            <Button type="submit" variant="solid" className="mt-2 w-full rounded-xl py-3.5 text-base" loading={submitting}>
              Create Account
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-muted">
          Already have an account?{' '}
          <Link to="/sign-in" className="font-semibold text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </main>
    </div>
  )
}

function RecessedField({ label, icon: Icon, children }: { label: string; icon: typeof User; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="ml-1 text-[11px] font-medium uppercase tracking-[0.1em] text-faint">{label}</label>
      <div className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-4 py-3 shadow-[inset_0_4px_10px_rgba(0,0,0,0.5)] transition-colors focus-within:border-electric focus-within:shadow-[inset_0_4px_10px_rgba(0,0,0,0.5),0_0_20px_-6px_var(--color-electric)]">
        <Icon className="h-[18px] w-[18px] shrink-0 text-faint" strokeWidth={2} />
        {children}
      </div>
    </div>
  )
}

type PickableOrg = {
  id: string
  name: string
  location: string | null
  city: string | null
  country: string | null
  is_registered: boolean
}

/** "City, Country" when both are known, falling back to whichever single field is available. */
function orgPlace(org: PickableOrg): string | null {
  if (org.city && org.country) return `${org.city}, ${org.country}`
  return org.location ?? org.country ?? org.city ?? null
}

/**
 * Shared canonical-directory selector: debounced, server-side searched and server-side ranked
 * (never a client-side filter/sort over the full directory) — the backend already returns a
 * small, prefix-prioritized page (see company_service.list_companies / institution_service.
 * list_institutions), this component just renders it. A "latest request wins" sequence guard
 * means a slow, stale response can never overwrite a newer search's results.
 *
 * Used identically for the student's optional institution link, and for institution/verifier
 * signup's required claim — the only differences are copy and which directory is searched. The
 * selected value is always the exact backend row id (never derived from the row's name) — see
 * handleSelect below, which calls onSelect(result.id) and nothing else resolves a selection.
 */
function OrgPicker<T extends PickableOrg>({
  label,
  placeholder,
  selectedId,
  onSelect,
  fetchPage,
  fetchById,
  initialHint,
  noResultsLabel,
  errorLabel,
}: {
  label: string
  placeholder: string
  selectedId: string
  onSelect: (id: string) => void
  fetchPage: (search: string) => Promise<{ items: T[] }>
  fetchById: (id: string) => Promise<T>
  initialHint: string
  noResultsLabel: (query: string) => string
  errorLabel: string
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<T[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedResult, setSelectedResult] = useState<T | null>(null)

  const containerRef = useRef<HTMLDivElement>(null)
  const requestSeqRef = useRef(0)
  const resolvedIdRef = useRef<string | null>(null)

  // Debounced, server-searched + server-ranked fetch — only while the picker is actually open, so
  // an untouched optional/already-selected picker never fires a request at all. `loading` flips to
  // true synchronously (not inside the timeout) so the debounce window itself never has a chance to
  // render a misleading "no results" flash before the request has even started.
  useEffect(() => {
    if (!isOpen) return
    setLoading(true)
    setError(null)
    const seq = ++requestSeqRef.current
    const handle = setTimeout(() => {
      fetchPage(search.trim())
        .then((page) => {
          if (seq !== requestSeqRef.current) return // a newer search superseded this one
          setResults(page.items)
        })
        .catch((err) => {
          if (seq !== requestSeqRef.current) return
          setError(err instanceof ApiError ? err.message : errorLabel)
        })
        .finally(() => {
          if (seq === requestSeqRef.current) setLoading(false)
        })
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, search])

  // Hydrates the rich "selected organization" display when selectedId is already set but this
  // particular mounted instance never itself received the click (e.g. switching between the
  // student/institution role tabs, which share the same institutionId but are separate OrgPicker
  // instances) — never re-derives the id from the name, only ever fetches the exact row by id.
  useEffect(() => {
    if (!selectedId) {
      setSelectedResult(null)
      resolvedIdRef.current = null
      return
    }
    if (resolvedIdRef.current === selectedId) return
    let cancelled = false
    fetchById(selectedId).then((org) => {
      if (!cancelled) {
        setSelectedResult(org)
        resolvedIdRef.current = selectedId
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  useEffect(() => {
    if (!isOpen) return
    function handlePointerDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setIsOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [isOpen])

  function handleSelect(result: T) {
    setSelectedResult(result)
    resolvedIdRef.current = result.id
    setIsOpen(false)
    setSearch('')
    onSelect(result.id)
  }

  const trimmed = search.trim()
  const showSelectedCard = Boolean(selectedId) && !isOpen

  return (
    <div ref={containerRef} className="flex flex-col gap-1.5" onKeyDown={(e) => e.key === 'Escape' && setIsOpen(false)}>
      <label className="ml-1 text-[11px] font-medium uppercase tracking-[0.1em] text-faint">{label}</label>

      {showSelectedCard ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-canvas px-4 py-3 shadow-[inset_0_4px_10px_rgba(0,0,0,0.5)]">
          {selectedResult ? (
            <div className="flex min-w-0 items-start gap-2.5">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-good" strokeWidth={2.5} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{selectedResult.name}</p>
                {orgPlace(selectedResult) && <p className="truncate text-[12px] text-muted">{orgPlace(selectedResult)}</p>}
                <p className="text-[11px] text-faint">{selectedResult.is_registered ? 'Registered' : 'Directory only'}</p>
              </div>
            </div>
          ) : (
            <p className="text-[13px] text-faint">Loading selected organization…</p>
          )}
          <button
            type="button"
            onClick={() => setIsOpen(true)}
            className="shrink-0 text-[12px] font-semibold text-primary hover:underline"
          >
            Change
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-4 py-3 shadow-[inset_0_4px_10px_rgba(0,0,0,0.5)] focus-within:border-electric">
            <Search className="h-[18px] w-[18px] shrink-0 text-faint" strokeWidth={2} />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setIsOpen(true)
              }}
              onFocus={() => setIsOpen(true)}
              placeholder={placeholder}
              aria-label={label}
              className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint"
            />
          </div>

          {!isOpen && <p className="ml-1 text-[12px] text-faint">{initialHint}</p>}

          {isOpen && (
            <div role="listbox" aria-label={label} className="max-h-56 overflow-y-auto rounded-xl border border-line bg-canvas-2 p-1">
              {loading && <p className="px-3 py-2 text-[12px] text-faint">Searching…</p>}
              {!loading && error && <p className="px-3 py-2 text-[12px] text-bad">{error}</p>}
              {!loading && !error && results.length === 0 && (
                <p className="px-3 py-2 text-[12px] text-faint">{noResultsLabel(trimmed)}</p>
              )}
              {!loading &&
                !error &&
                results.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    role="option"
                    aria-selected={r.id === selectedId}
                    onClick={() => handleSelect(r)}
                    className="flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left hover:bg-canvas focus:bg-canvas focus:outline-none"
                  >
                    <span className="text-sm font-medium text-ink">{r.name}</span>
                    {orgPlace(r) && <span className="text-[12px] text-muted">{orgPlace(r)}</span>}
                    <span className="text-[11px] text-faint">{r.is_registered ? 'Registered' : 'Directory only'}</span>
                  </button>
                ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
