import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Inbox, AlertTriangle, GraduationCap } from 'lucide-react'
import { getCompanyRequests } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { BackendCredentialRequest, BackendRequestStatus, CredentialType } from '../../types'
import { PageHeader, GlassPanel, Badge, Button, EmptyState, ErrorState } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { CredentialInbox } from './components/CredentialInbox'

const REQUEST_STATUS_TONE: Record<BackendRequestStatus, 'good' | 'warn' | 'bad' | 'neutral'> = {
  pending: 'warn',
  approved: 'good',
  declined: 'bad',
  expired: 'neutral',
}

const LABEL_TO_TYPE: Record<string, CredentialType> = {
  degree: 'degree',
  transcript: 'transcript',
  'migration certificate': 'migration',
  migration: 'migration',
  'internship certificate': 'internship',
  internship: 'internship',
  certification: 'certification',
  'course completion': 'course',
  course: 'course',
}

/** Client-side preview only — the real, authoritative mismatch check runs server-side at Verify time (see backend verification_service.check_type_mismatch). This just avoids surprising the user with a bare "Verify" button when the types obviously don't line up. */
function looksLikeMismatch(requestedLabels: string[], credentialType: CredentialType): boolean {
  const requestedTypes = requestedLabels.map((l) => LABEL_TO_TYPE[l.trim().toLowerCase()]).filter(Boolean)
  if (requestedTypes.length === 0) return false // unmapped/custom label — let the backend be the judge
  return !requestedTypes.includes(credentialType)
}

export function VerifierRequests() {
  const [requests, setRequests] = useState<BackendCredentialRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCompanyRequests()
      .then(setRequests)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load requests.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <PageHeader title="Requests" eyebrow="Credential Requests" icon={Inbox} description="Credential requests you've sent, and credentials shared with you." />

      <div className="mb-8">
        <CredentialInbox />
      </div>

      {loading ? (
        <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>
      ) : (
        <>
          {error && (
            <div className="mb-5 max-w-2xl">
              <ErrorState description={error} onRetry={() => window.location.reload()} />
            </div>
          )}

          <h2 className="mb-3 text-[15px] font-bold text-ink">Sent Requests</h2>
      {requests.length === 0 ? (
        <EmptyState icon={Inbox} title="No requests yet" description="No requests yet." />
      ) : (
        <div className="max-w-2xl space-y-3">
          {requests.map((r) => (
            <GlassPanel key={r.id} className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3.5">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted">
                    <GraduationCap className="h-5 w-5" strokeWidth={2} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-ink">{r.student_name}</p>
                    <p className="truncate text-xs text-muted">{r.purpose}</p>
                  </div>
                </div>
                <Badge tone={REQUEST_STATUS_TONE[r.status]} size="sm">
                  {r.status.toUpperCase()}
                </Badge>
              </div>

              <div className="mt-3 rounded-lg border border-line bg-canvas-2/50 px-3.5 py-2.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Requested Credential{r.requested_credentials.length > 1 ? 's' : ''}</p>
                <p className="mt-0.5 text-[13px] font-medium text-ink">{r.requested_credentials.join(', ')}</p>
              </div>

              {r.shared_credentials.length > 0 && (
                <div className="mt-3 space-y-2">
                  {r.shared_credentials.map((c) => {
                    const mismatch = looksLikeMismatch(r.requested_credentials, c.credential_type)
                    return (
                      <div
                        key={c.id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-line bg-canvas-2/40 px-3.5 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-medium text-ink">Received: {c.title}</p>
                          {mismatch && (
                            <p className="mt-0.5 flex items-center gap-1 text-[11px] font-semibold text-bad">
                              <AlertTriangle className="h-3 w-3" strokeWidth={2.5} />
                              Credential type mismatch — not yet verified
                            </p>
                          )}
                        </div>
                        <Link to={`/verifier/verify/${c.id}`}>
                          <Button variant="outline" size="sm">
                            Verify
                          </Button>
                        </Link>
                      </div>
                    )
                  })}
                </div>
              )}
            </GlassPanel>
          ))}
        </div>
      )}
        </>
      )}
    </div>
  )
}
