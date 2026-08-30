import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Inbox, FileText, Clock, Building2 } from 'lucide-react'
import { getStudentRequests, declineCredentialRequest } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { BackendCredentialRequest } from '../../types'
import { PageHeader, Button, EmptyState, GlassPanel } from '../../components/ui'

/**
 * Reproduces Stitch's "incoming_requests_refined" screen: a 2-column grid of
 * glass request cards, each with a corner status ribbon, an org avatar +
 * name + relative-time row, a bordered "Requested Credential" list, and a
 * Reject/Approve gradient action row. Real data throughout — no fabricated
 * org names or timestamps.
 */
export function Requests() {
  const [requests, setRequests] = useState<BackendCredentialRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [decliningId, setDecliningId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    getStudentRequests()
      .then(setRequests)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load your requests. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  const pending = requests.filter((r) => r.status === 'pending')

  async function handleDecline(id: string) {
    setDecliningId(id)
    setError(null)
    try {
      const updated = await declineCredentialRequest(id)
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not decline this request.')
    } finally {
      setDecliningId(null)
    }
  }

  if (loading) return <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><div className="h-56 animate-pulse rounded-xl bg-surface" /><div className="h-56 animate-pulse rounded-xl bg-surface" /></div>

  return (
    <div>
      <PageHeader title="Incoming Requests" eyebrow="Access Requests" icon={Inbox} description="Companies and universities requesting access to your credentials." />

      {error && <div className="mb-5 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {pending.length === 0 ? (
        !error && <EmptyState icon={Inbox} title="No pending requests" description="When a company or university requests your credentials, they'll show up here for you to review." />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {pending.map((req) => {
            const initials = req.company_name
              .split(' ')
              .map((w) => w[0])
              .join('')
              .slice(0, 2)
            return (
              <GlassPanel key={req.id} className="relative flex flex-col gap-4 overflow-hidden p-5">
                <span className="absolute right-0 top-0 flex items-center gap-1 rounded-bl-lg bg-warn-bg px-3 py-1 font-[family-name:var(--font-mono)] text-[11px] font-semibold uppercase tracking-wider text-warn shadow-[0_0_15px_-4px_var(--color-warn)]">
                  <Clock className="h-3 w-3" strokeWidth={2.5} /> Pending
                </span>

                <div className="mt-2 flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-canvas-2 text-muted">
                    <Building2 className="h-4.5 w-4.5" strokeWidth={2} />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-ink">{req.company_name}</h3>
                    <p className="text-[12px] text-muted">{req.purpose}</p>
                  </div>
                  <span className="ml-auto hidden text-[10px] font-semibold text-faint sm:block">{initials}</span>
                </div>

                <div className="rounded-lg border border-line bg-canvas-2/50 p-3">
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-faint">Requested Credential{req.requested_credentials.length > 1 ? 's' : ''}</p>
                  <div className="flex flex-col gap-2">
                    {req.requested_credentials.map((label) => (
                      <div key={label} className="flex items-center gap-2 text-[13px] text-ink">
                        <FileText className="h-4 w-4 text-cyan" strokeWidth={2} />
                        {label}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-auto flex gap-3 pt-1">
                  <Button variant="outline" className="flex-1" loading={decliningId === req.id} onClick={() => handleDecline(req.id)}>
                    Reject
                  </Button>
                  <Button variant="solid" className="flex-1" onClick={() => navigate(`/student/share?requestId=${req.id}`)}>
                    Approve
                  </Button>
                </div>
              </GlassPanel>
            )
          })}
        </div>
      )}
    </div>
  )
}
