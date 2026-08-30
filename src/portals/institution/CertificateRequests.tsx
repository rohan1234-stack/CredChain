import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClipboardList, CalendarDays } from 'lucide-react'
import { approveCertificateRequest, getInstitutionCertificateRequests, rejectCertificateRequest } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { InstitutionCertificateRequest, InstitutionRequestStatus } from '../../types'
import { PageHeader, Card, Button, Badge, EmptyState, CheckRow, WorkflowTimeline, buildCertificateRequestSteps } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

const TYPE_LABELS: Record<string, string> = {
  degree: 'Degree Certificate',
  transcript: 'Transcript',
  migration: 'Migration Certificate',
  internship: 'Internship Certificate',
  certification: 'Certification',
  course: 'Course Completion',
}

const STATUS_TONE: Record<InstitutionRequestStatus, 'good' | 'warn' | 'bad' | 'neutral'> = {
  pending: 'warn',
  approved: 'good',
  rejected: 'bad',
  fulfilled: 'good',
}

/** Per-document workflow checklist state — fulfilled/approved reads as done, pending as
 * in-progress, rejected as failed. Purely presentational mapping of the same status. */
const STATUS_CHECK_STATE: Record<InstitutionRequestStatus, 'pass' | 'fail' | 'gap'> = {
  pending: 'gap',
  approved: 'pass',
  rejected: 'fail',
  fulfilled: 'pass',
}

interface RequestGroup {
  key: string
  studentName: string
  studentIdentifier: string
  reason: string | null
  items: InstitutionCertificateRequest[]
}

/** Same URL/query-param shape the existing APPROVED -> "Issue Credential" button already builds. */
function issueUrl(r: InstitutionCertificateRequest): string {
  return `/institution/credentials/issue?studentId=${r.student_id}&credentialType=${r.credential_type}&fulfillsRequestId=${r.id}`
}

function groupRequests(requests: InstitutionCertificateRequest[]): RequestGroup[] {
  const groups = new Map<string, RequestGroup>()
  for (const r of requests) {
    const key = r.batch_id ?? r.id
    const existing = groups.get(key)
    if (existing) {
      existing.items.push(r)
    } else {
      groups.set(key, { key, studentName: r.student_name, studentIdentifier: r.student_identifier, reason: r.reason, items: [r] })
    }
  }
  return Array.from(groups.values()).sort(
    (a, b) => new Date(b.items[0].created_at).getTime() - new Date(a.items[0].created_at).getTime()
  )
}

export function InstitutionCertificateRequests() {
  const navigate = useNavigate()
  const [requests, setRequests] = useState<InstitutionCertificateRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [issuingId, setIssuingId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    getInstitutionCertificateRequests()
      .then(setRequests)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load certificate requests. Please try again.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const groups = useMemo(() => groupRequests(requests), [requests])

  function typeLabel(r: InstitutionCertificateRequest) {
    return r.credential_type === 'other' ? r.custom_credential_name : TYPE_LABELS[r.credential_type]
  }

  async function handleApprove(id: string) {
    setBusyId(id)
    setError(null)
    try {
      const updated = await approveCertificateRequest(id)
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not approve this request.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleApproveAndIssue(r: InstitutionCertificateRequest) {
    setIssuingId(r.id)
    setError(null)
    try {
      const updated = await approveCertificateRequest(r.id)
      setRequests((prev) => prev.map((x) => (x.id === r.id ? updated : x)))
      navigate(issueUrl(updated))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not approve this request.')
    } finally {
      setIssuingId(null)
    }
  }

  // Reject-reason state is scoped to whichever request is currently being
  // rejected — always reset on open/cancel so a reason typed for one
  // student's request can never reappear when rejecting a different one.
  function handleStartReject(id: string) {
    setRejectingId(id)
    setRejectReason('')
  }

  function handleCancelReject() {
    setRejectingId(null)
    setRejectReason('')
  }

  async function handleReject(id: string) {
    if (!rejectReason.trim()) return
    setBusyId(id)
    setError(null)
    try {
      const updated = await rejectCertificateRequest(id, rejectReason)
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)))
      setRejectingId(null)
      setRejectReason('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject this request.')
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  return (
    <div>
      <PageHeader title="Certificate Requests" eyebrow="Student Requests" icon={ClipboardList} description="Students requesting certificates from your institution." />

      {error && <div className="mb-5 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {groups.length === 0 ? (
        !error && <EmptyState icon={ClipboardList} title="No certificate requests" description="When a student requests a certificate, it will show up here." />
      ) : (
        <div className="space-y-3">
          {groups.map((g) => (
            <Card key={g.key} className="max-w-2xl p-5">
              <div className="mb-4 flex items-start justify-between gap-3 border-b border-line pb-4">
                <div>
                  <p className="text-lg font-bold text-ink">{g.studentName}</p>
                  <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-wider text-faint">
                    {g.studentIdentifier}
                    {g.items.length > 1 ? ` · ${g.items.length} documents requested` : ''}
                  </p>
                  {g.reason && <p className="mt-1 text-xs text-muted">{g.reason}</p>}
                </div>
                <div className="flex shrink-0 items-center gap-1 rounded border border-line bg-surface-2 px-2 py-1">
                  <CalendarDays className="h-3.5 w-3.5 text-faint" strokeWidth={2} />
                  <span className="font-[family-name:var(--font-mono)] text-[12px] text-muted">
                    {new Date(g.items[0].created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>

              {/* Connected timeline of requested documents — Stitch's glow-line + status node per item */}
              <div className="relative space-y-3 pl-4">
                <div aria-hidden className="absolute bottom-2 left-[3px] top-2 w-px bg-line-strong" />
                {g.items.map((r) => (
                  <div key={r.id} className="relative">
                    <span
                      aria-hidden
                      className={
                        r.status === 'pending'
                          ? 'absolute -left-4 top-3 h-1.5 w-1.5 rounded-full bg-warn shadow-glow-warn'
                          : r.status === 'rejected'
                            ? 'absolute -left-4 top-3 h-1.5 w-1.5 rounded-full bg-bad shadow-glow-bad'
                            : 'absolute -left-4 top-3 h-1.5 w-1.5 rounded-full bg-good shadow-glow-good'
                      }
                    />
                    <div className="flex items-center gap-3">
                      <div className="flex-1">
                        <CheckRow label={typeLabel(r) ?? ''} state={STATUS_CHECK_STATE[r.status]} bordered size="sm" />
                      </div>
                      <Badge tone={STATUS_TONE[r.status]} size="sm">
                        {r.status}
                      </Badge>
                    </div>
                    <div className="mt-3 rounded-lg border border-line/60 bg-canvas-2/40 px-3 py-2.5">
                      <WorkflowTimeline steps={buildCertificateRequestSteps(r)} />
                    </div>

                    {r.status === 'pending' && (
                      <div className="mt-2">
                        {rejectingId === r.id ? (
                          <div className="space-y-2">
                            <textarea
                              value={rejectReason}
                              onChange={(e) => setRejectReason(e.target.value)}
                              placeholder="Reason for rejection"
                              rows={2}
                              disabled={busyId === r.id}
                              className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none focus:border-primary disabled:opacity-60"
                            />
                            <div className="flex gap-2">
                              <Button variant="outline" size="sm" disabled={busyId === r.id} onClick={() => handleCancelReject()}>
                                Cancel
                              </Button>
                              <Button variant="solid" size="sm" loading={busyId === r.id} onClick={() => handleReject(r.id)}>
                                Confirm Reject
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="solid"
                              size="sm"
                              loading={issuingId === r.id}
                              disabled={busyId === r.id}
                              onClick={() => handleApproveAndIssue(r)}
                            >
                              Approve & Issue
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              loading={busyId === r.id}
                              disabled={issuingId === r.id}
                              onClick={() => handleApprove(r.id)}
                            >
                              Approve
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={busyId === r.id || issuingId === r.id}
                              onClick={() => handleStartReject(r.id)}
                            >
                              Reject
                            </Button>
                          </div>
                        )}
                      </div>
                    )}

                    {r.status === 'approved' && (
                      <div className="mt-2">
                        <Button variant="solid" size="sm" onClick={() => navigate(issueUrl(r))}>
                          Issue Credential
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
